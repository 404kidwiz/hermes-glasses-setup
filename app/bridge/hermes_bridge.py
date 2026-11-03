#!/usr/bin/env python3
"""
Hermes Glasses Bridge - WebSocket server connecting the Hermes Glasses iOS
app to a Hermes Agent. STT happens on the phone; this bridge handles text
queries, photo requests, conversation memory, and TTS.

Protocol (JSON text frames):
  app → bridge: {"type":"query","text":...}      transcribed utterance
  app → bridge: {"type":"new_session"}           forget the conversation
  app → bridge: {"type":"photo","data":<b64>}    reply to capture_photo
  app → bridge: {"type":"photo_error", ...}
  bridge → app: {"type":"welcome"} / {"type":"capture_photo"} /
                {"type":"response_delta","text":...} (first speakable chunk;
                  may repeat until the turn is done) /
                {"type":"response","text":...,"tts":bool,"streamed":bool} /
                {"type":"session_reset"} /
                {"type":"ack","text":...} (at most once per turn, before
                  any reply text: "Let me look." / "Searching now." /
                  "One sec."; with bridge TTS its audio is the first clip) /
                audio_start + binary PCM16 mono 24kHz TTS
                + optional {"type":"audio_clip"} between sentences
                + audio_end
"""

import asyncio
import base64
import datetime
import hmac
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import wave
import urllib.error
import urllib.request
from urllib.parse import parse_qs, urlparse

try:
    import websockets
except ImportError:
    print("Install websockets: pip install websockets")
    sys.exit(1)

# ── Configuration ──────────────────────────────────────────────────────────
HOST = os.environ.get("HERMES_BRIDGE_HOST", "0.0.0.0")
PORT = int(os.environ.get("HERMES_BRIDGE_PORT", "8765"))
HERMES_BIN = os.environ.get(
    "HERMES_BIN",
    os.path.expanduser("~/.hermes/hermes-agent/venv/bin/hermes"),
)

# Shared-secret auth. When set (HERMES_BRIDGE_TOKEN env), clients must
# connect with ws://host:8765/voice?token=<value>. REQUIRED on any bridge
# reachable from the internet - hermes has tool access, so an open bridge
# is remote code execution for anyone who finds the port.
AUTH_TOKEN = os.environ.get("HERMES_BRIDGE_TOKEN", "")

# Bridge-side TTS (edge-tts/say → PCM streaming). Default OFF: the app
# speaks replies on-device with AVSpeechSynthesizer. Set HERMES_BRIDGE_TTS=1
# to fall back to server TTS for clients that can't speak locally.
BRIDGE_TTS = os.environ.get("HERMES_BRIDGE_TTS", "") == "1"

# Spoken "one sec" ack so slow turns don't sit in silence: sent the moment a
# photo is requested or Hermes starts a web tool (search/browse), else after
# ACK_AFTER_S with no reply text. Plain chat's first token lands ~6-9 s, so
# the timer only catches turns that are unusually slow. HERMES_BRIDGE_ACK=0
# turns it off.
ACK_ENABLED = os.environ.get("HERMES_BRIDGE_ACK", "1") != "0"
ACK_AFTER_S = float(os.environ.get("HERMES_BRIDGE_ACK_AFTER_S", "10"))

# Which brain answers queries:
#   "hermes" (default) - spawn the hermes CLI per query (agent with tools;
#                        slower: pays agent boot every question)
#   "claude"           - call the Claude API directly (fast conversational
#                        answers + vision; needs ANTHROPIC_API_KEY)
#   "anthropic" / "openai" / "gemini" - call the provider's HTTP API
#                        directly (fast conversational answers + vision;
#                        needs the matching *_API_KEY). "claude" is kept as
#                        an alias for "anthropic" (back-compat).
BRAIN = os.environ.get("HERMES_BRIDGE_BRAIN", "hermes")
CLAUDE_MODEL = os.environ.get("HERMES_BRIDGE_MODEL", "claude-opus-4-8")

# Warm Hermes gateway (OpenAI-compatible API on :8642). Default ON so glasses
# turns skip the per-query CLI boot (~2–8s) and stream tokens as they generate.
# Set HERMES_BRIDGE_API=0 to force the CLI. Key: HERMES_API_KEY, else
# API_SERVER_KEY from this process env or ~/.hermes/.env.
HERMES_API_BASE = os.environ.get("HERMES_API_URL", "http://127.0.0.1:8642").rstrip("/")
HERMES_API_ENABLED = os.environ.get("HERMES_BRIDGE_API", "1") != "0"
HERMES_SESSION_KEY = os.environ.get("HERMES_BRIDGE_SESSION_KEY", "glasses-bridge")
CLI_TIMEOUT_S = int(os.environ.get("HERMES_BRIDGE_CLI_TIMEOUT", "180"))

# Empty overrides use the active Hermes gateway/CLI configuration, including
# its tools, memory and delegation. Explicit values remain available for a
# glasses-specific route. Do not ship provider/model names that age out.
HERMES_AGENT_MODEL = os.environ.get("HERMES_AGENT_MODEL", "")
HERMES_AGENT_PROVIDER = os.environ.get("HERMES_AGENT_PROVIDER", "")
HERMES_AGENT_FALLBACK_MODEL = os.environ.get("HERMES_AGENT_FALLBACK_MODEL", "")
HERMES_AGENT_FALLBACK_PROVIDER = os.environ.get("HERMES_AGENT_FALLBACK_PROVIDER", "")


def _read_hermes_api_key() -> str:
    for candidate in (
        os.environ.get("HERMES_API_KEY", ""),
        os.environ.get("API_SERVER_KEY", ""),
    ):
        if candidate.strip():
            return candidate.strip()
    try:
        with open(os.path.expanduser("~/.hermes/.env")) as env_file:
            for line in env_file:
                if line.startswith("API_SERVER_KEY="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


HERMES_API_KEY = _read_hermes_api_key()

# ── Provider brains (direct API, BRAIN="anthropic"|"openai"|"gemini") ──────
BASE_URLS = {
    "anthropic": "https://api.anthropic.com",
    "openai": "https://api.openai.com",
    "gemini": "https://generativelanguage.googleapis.com",
}
PROVIDER_API_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def _canon_brain(brain: str) -> str:
    return "anthropic" if brain == "claude" else brain


def build_provider_request(
    brain: str, model: str, base_url: str, api_key: str, prompt: str,
    image_b64: str | None, system: str | None = None,
) -> tuple[str, dict, dict]:
    """Return (url, headers, body_dict) for a one-shot chat+vision request.

    `system` defaults to CLAUDE_SYSTEM (the voice persona: 1-3 spoken
    sentences) so provider-brain answers stay voice-optimized, same as the
    legacy ask_claude() path.
    """
    system = system if system is not None else CLAUDE_SYSTEM
    brain = _canon_brain(brain)
    headers = {"Content-Type": "application/json"}
    if brain == "anthropic":
        content = []
        if image_b64:
            content.append({"type": "image", "source": {
                "type": "base64", "media_type": "image/jpeg", "data": image_b64}})
        content.append({"type": "text", "text": prompt})
        headers["x-api-key"] = api_key
        headers["anthropic-version"] = "2023-06-01"
        body = {"model": model, "max_tokens": 1024, "system": system,
                "messages": [{"role": "user", "content": content}]}
        return base_url + "/v1/messages", headers, body
    if brain == "openai":
        if image_b64:
            content = [{"type": "text", "text": prompt},
                       {"type": "image_url", "image_url": {
                           "url": "data:image/jpeg;base64," + image_b64}}]
        else:
            content = prompt
        if api_key:
            headers["Authorization"] = "Bearer " + api_key
        body = {"model": model, "max_tokens": 1024,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": content}]}
        return base_url + "/v1/chat/completions", headers, body
    if brain == "gemini":
        parts = []
        if image_b64:
            parts.append({"inline_data": {"mime_type": "image/jpeg", "data": image_b64}})
        parts.append({"text": prompt})
        body = {"contents": [{"role": "user", "parts": parts}],
                "systemInstruction": {"parts": [{"text": system}]}}
        # The key travels in a header, never in the URL: query strings end up
        # in proxy logs, crash reports and error messages.
        if api_key:
            headers["x-goog-api-key"] = api_key
        url = "%s/v1beta/models/%s:generateContent" % (base_url, model)
        return url, headers, body
    raise ValueError("unknown brain: %s" % brain)


def parse_provider_reply(brain: str, status: int, body_bytes: bytes) -> str:
    brain = _canon_brain(brain)
    data = json.loads(body_bytes.decode("utf-8"))
    if status != 200:
        raise RuntimeError(data.get("error", {}).get("message", "API error %s" % status))
    if brain == "anthropic":
        return next(b["text"] for b in data["content"] if b.get("type") == "text")
    if brain == "openai":
        return data["choices"][0]["message"]["content"]
    if brain == "gemini":
        return data["candidates"][0]["content"]["parts"][0]["text"]
    raise ValueError("unknown brain: %s" % brain)


def ask_provider(brain: str, text: str, photo: bytes | None = None) -> str:
    """Answer via a direct provider HTTP API (anthropic/openai/gemini).

    Stdlib-only (urllib), stateless single-turn request built with
    build_provider_request() and parsed with parse_provider_reply(). Unlike
    the legacy SDK-based ask_claude() below, this path carries no cross-turn
    history - each query is answered independently.
    """
    brain = _canon_brain(brain)
    base_url = os.environ.get("HERMES_BRIDGE_BASE_URL", BASE_URLS[brain])
    key_env = PROVIDER_API_KEY_ENV[brain]
    api_key = os.environ.get(key_env, "")
    if not api_key:
        return f"The {brain} brain needs an API key. Set {key_env} for the bridge."

    image_b64 = base64.b64encode(photo).decode() if photo else None
    url, headers, body = build_provider_request(
        brain, CLAUDE_MODEL, base_url, api_key, text, image_b64)

    request = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=30) as resp:
            status, body_bytes = resp.status, resp.read()
    except urllib.error.HTTPError as e:
        status, body_bytes = e.code, e.read()
    except urllib.error.URLError as e:
        print(f"[{brain}] Connection error: {e}")
        return f"Sorry, I couldn't reach the {brain} API."

    try:
        return parse_provider_reply(brain, status, body_bytes)
    except Exception as e:
        print(f"[{brain}] API error ({status}): {e}")
        return f"Sorry, the {brain} API returned an error."


# Utterances containing any of these ask about something the user sees;
# the bridge then requests a photo from the glasses. Phrases, not bare
# words: "picture" alone would fire on "why did you take a picture?"
VISUAL_KEYWORDS = [
    "look at", "looking at", "see this", "what am i seeing",
    "what is this", "what's this", "read this", "in front of me",
    "take a picture", "take a photo", "snap a photo", "use the camera",
    "through the camera",
]


def is_visual_query(text: str) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in VISUAL_KEYWORDS)


# "this drink", "that building", "the one on the left" - references to
# something the user is (probably) looking at
DEICTIC_RE = re.compile(r"\b(this|that|these|those)\s+([a-z]+)|\bthe one\b",
                        re.IGNORECASE)


# "this morning", "that question" - deictic in grammar but not about
# anything visible. Nouns here never trigger a photo.
DEICTIC_STOP_NOUNS = {
    "morning", "afternoon", "evening", "night", "time", "day", "week",
    "month", "year", "moment", "question", "answer", "idea", "point",
    "case", "way", "reason", "sense", "stuff", "conversation", "chat",
    "session", "app", "voice", "sound", "response", "reply", "much",
    "long", "short", "many", "far", "fast", "slow", "bit", "lot", "kind",
    "sort", "type",
    # Auxiliary/copular verbs: "this is a test", "that was fun" are not
    # about anything visible
    "is", "was", "are", "were", "be", "being", "been", "isn", "wasn",
    "will", "would", "can", "could", "should", "might", "may", "must",
    "does", "did", "done", "has", "had", "have", "gets", "got", "goes",
    "went", "seems", "means", "works", "sounds", "feels", "happened",
}


# Deictic follow-up captures only when no photo was taken within this many
# seconds - within the window, conversation memory already knows what the
# user is looking at.
PHOTO_MEMORY_WINDOW_S = 120.0


def should_capture_photo(text: str, last_photo_at: float, now: float) -> bool:
    """Decide whether a query needs a fresh photo.

    Explicit visual keywords always capture. Deictic references ("this X")
    capture only for plausibly-visible nouns, and only when no photo was
    taken recently - within the window, conversation memory already knows
    what the user is looking at.
    """
    if is_visual_query(text):
        return True
    for match in DEICTIC_RE.finditer(text):
        noun = (match.group(2) or "").lower()
        if match.group(0).lower() == "the one" or (
            noun and noun not in DEICTIC_STOP_NOUNS
        ):
            return (now - last_photo_at) > PHOTO_MEMORY_WINDOW_S
    return False


# ── Conversation memory (same-day hermes session) ──────────────────────────
SESSION_FILE = os.path.expanduser("~/.hermes_glasses_bridge_session.json")

# ── Turn history for the glasses dashboard ─────────────────────────────────
# Every answered query is appended (user text, reply, brain, photo path) to
# turns.jsonl, and glasses photos are kept (the pre-dashboard bridge deleted
# them after each turn). Failures here must never break the voice loop.
HISTORY_DIR = os.environ.get(
    "HERMES_GLASSES_HISTORY_DIR",
    os.path.expanduser("~/.hermes_glasses_history"),
)
HISTORY_PHOTO_DIR = os.path.join(HISTORY_DIR, "photos")
HISTORY_TURNS_FILE = os.path.join(HISTORY_DIR, "turns.jsonl")


def log_turn(user_text: str, response_text: str, photo: bytes | None,
             brain: str, session_id: str | None = None) -> None:
    """Persist one turn (+ photo bytes) for the dashboard. Best-effort."""
    try:
        os.makedirs(HISTORY_PHOTO_DIR, exist_ok=True)
        photo_name = None
        if photo:
            photo_name = f"{int(time.time() * 1000)}.jpg"
            with open(os.path.join(HISTORY_PHOTO_DIR, photo_name), "wb") as f:
                f.write(photo)
        entry = {
            "ts": time.time(),
            "user": user_text,
            "reply": response_text,
            "brain": brain,
            "photo": photo_name,
            "session": session_id,
        }
        with open(HISTORY_TURNS_FILE, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as error:  # noqa: BLE001 - history must never kill a turn
        print(f"[Bridge] Could not persist turn history: {error}")

VOICE_PERSONA = (
    "(You are a voice assistant running on smart glasses. Your answers are "
    "spoken aloud - keep them to 1-3 conversational sentences unless the "
    "user asks for detail. The user may reference things they see; photos "
    "may be attached to queries. Do not mention codebases or files unless "
    "asked.) "
)


def _today() -> str:
    return datetime.date.today().isoformat()


def _valid_session_data() -> dict | None:
    """Today's glasses session, only if it belongs to the current model chain.

    Hermes /v1/chat/completions does not lock a session to the model that
    created it — the bridge does, by only passing resume to the matching
    pair. Unknown models (including pre-Flash files with no model field)
    must not resume.
    """
    try:
        with open(SESSION_FILE) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if data.get("date") != _today() or not data.get("session_id"):
        return None
    pair = (data.get("model"), data.get("provider"))
    if pair not in agent_model_chain():
        return None
    return data


def load_session() -> str | None:
    """Stored hermes session ID, if it is from today and a chain model."""
    data = _valid_session_data()
    return data["session_id"] if data else None


def load_session_pair() -> tuple[str | None, str | None]:
    """Model/provider that created the stored session, or (None, None)."""
    data = _valid_session_data()
    if not data:
        return None, None
    return data.get("model"), data.get("provider")


def store_session(
    session_id: str,
    source: str = "cli",
    model: str | None = None,
    provider: str | None = None,
):
    stamp_model = (model or "").strip() or HERMES_AGENT_MODEL
    stamp_provider = (provider or "").strip() or HERMES_AGENT_PROVIDER
    try:
        with open(SESSION_FILE, "w") as f:
            json.dump(
                {
                    "session_id": session_id,
                    "date": _today(),
                    "source": source,
                    "model": stamp_model,
                    "provider": stamp_provider,
                },
                f,
            )
    except OSError as e:
        print(f"[Bridge] Could not persist session: {e}")


def load_session_source() -> str | None:
    """How the stored session was created: 'api', 'cli', or None."""
    data = _valid_session_data()
    if not data:
        return None
    return data.get("source") or "cli"


def resume_for_pair(
    resume: str | None,
    resume_source: str | None,
    resume_model: str | None,
    resume_provider: str | None,
    model: str,
    provider: str,
    source: str,
) -> str | None:
    """Resume only the model/provider that created this session id."""
    if not resume or resume_source != source:
        return None
    if (model, provider) != (resume_model, resume_provider):
        return None
    return resume


def clear_session():
    try:
        os.unlink(SESSION_FILE)
    except OSError:
        pass


def extract_session_id(stderr_text: str) -> str | None:
    match = re.search(r"session_id:\s*(\S+)", stderr_text)
    return match.group(1) if match else None


# ── Legacy Claude SDK brain (unused by the request path below, which now
# routes anthropic/openai/gemini through ask_provider(); kept for its
# tested same-day history helpers) ──────────────────────────────────────────
CLAUDE_HISTORY_FILE = os.path.expanduser("~/.hermes_glasses_claude_history.json")
CLAUDE_MAX_HISTORY = 40  # messages kept (20 turns)

CLAUDE_SYSTEM = (
    "You are a voice assistant running on the user's smart glasses. Your "
    "answers are spoken aloud: keep them to 1-3 conversational sentences "
    "unless the user asks for detail. The user may reference things they "
    "see; photos from the glasses camera may be attached to queries. Be "
    "direct, natural, and helpful."
)


def load_claude_history() -> list:
    """Same-day conversation history for the Claude brain."""
    try:
        with open(CLAUDE_HISTORY_FILE) as f:
            data = json.load(f)
        if data.get("date") == _today():
            return data.get("messages", [])
    except (OSError, ValueError):
        pass
    return []


def store_claude_history(messages: list):
    try:
        with open(CLAUDE_HISTORY_FILE, "w") as f:
            json.dump({"date": _today(), "messages": messages}, f)
    except OSError as e:
        print(f"[Bridge] Could not persist Claude history: {e}")


def clear_claude_history():
    try:
        os.unlink(CLAUDE_HISTORY_FILE)
    except OSError:
        pass


def trim_claude_history(messages: list, max_messages: int = CLAUDE_MAX_HISTORY) -> list:
    return messages[-max_messages:] if len(messages) > max_messages else messages


def build_claude_user_content(text: str, photo: bytes | None) -> list:
    """User content blocks: optional glasses photo first, then the words."""
    content = []
    if photo:
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.b64encode(photo).decode(),
            },
        })
    content.append({"type": "text", "text": text})
    return content


# Retained legacy SDK helper - no longer on the request path (provider
# brains now go through ask_provider()/build_provider_request()); kept for
# reference and its tested same-day history helpers.
def ask_claude(text: str, photo: bytes | None = None) -> str | None:
    """Answer via the Claude API with same-day conversation memory.

    Fast path: no process spawn, no agent boot - typically 2-4s for a
    spoken-length reply. Photos go in as native image blocks.
    """
    try:
        import anthropic
    except ImportError:
        return "The Claude brain needs the anthropic package: pip install anthropic"

    history = load_claude_history()
    user_message = {"role": "user", "content": build_claude_user_content(text, photo)}

    try:
        client = anthropic.Anthropic()
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1024,
            # Stable prefix cached; history rides behind it
            system=[{
                "type": "text",
                "text": CLAUDE_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=trim_claude_history(history + [user_message]),
        )
        reply = next(
            (b.text for b in response.content if b.type == "text"), None
        )
        if reply:
            # Persist text-only user turn (images would bloat the file and
            # re-bill on every later request)
            history.append({"role": "user", "content": text})
            history.append({"role": "assistant", "content": reply})
            store_claude_history(trim_claude_history(history))
        return reply
    except anthropic.AuthenticationError:
        return ("The Claude API key is missing or invalid. Set "
                "ANTHROPIC_API_KEY for the bridge.")
    except anthropic.APIStatusError as e:
        print(f"[Claude] API error {e.status_code}: {e.message}")
        return "Sorry, the Claude API returned an error."
    except anthropic.APIConnectionError:
        return "Sorry, I couldn't reach the Claude API."
    except Exception as e:
        print(f"[Claude] Error: {e}")
        return f"Error: {e}"

# ── Hermes Agent ────────────────────────────────────────────────────────────

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
BOX_CHARS = set("╭╮╰╯│─═╞╡┌┐└┘┤├")


def extract_hermes_reply(raw: str) -> str | None:
    """Pull just the assistant's reply out of the hermes CLI output.

    The CLI prints: a Query echo, spinner lines, then the reply inside a
    box whose top border contains 'Hermes', then a session footer.
    """
    text = ANSI_RE.sub("", raw).replace("\r", "\n")
    lines = text.split("\n")

    reply_lines = []
    in_box = False
    for line in lines:
        stripped = line.strip()
        if not in_box:
            if "Hermes" in stripped and BOX_CHARS & set(stripped):
                in_box = True
            continue
        # Bottom border (or any pure box-drawing line) ends the reply
        if stripped and set(stripped) <= (BOX_CHARS | set(" ")):
            break
        cleaned = stripped.strip("│").strip()
        reply_lines.append(cleaned)

    reply = "\n".join(reply_lines).strip()
    return reply or None


# `hermes chat --cli` prints this on stdout during CLI init when
# ~/.hermes/config.yaml platform_toolsets.cli lists names that are not
# real toolsets (moa is a model preset, messaging is a platform family,
# mcp-codegraph is not the mcp_servers key). The glasses app was speaking it.
_UNKNOWN_TOOLSETS_RE = re.compile(
    r"(?:\[/?[^\]]+\])?Warning:\s*Unknown toolsets:\s*[^\n]*(?:\[/?[^\]]+\])?",
    re.IGNORECASE,
)


def strip_cli_warnings(text: str) -> str:
    """Drop Hermes CLI toolset warnings so they never reach glasses TTS."""
    if not text:
        return text
    cleaned = ANSI_RE.sub("", text)
    cleaned = _UNKNOWN_TOOLSETS_RE.sub("", cleaned)
    return "\n".join(line for line in cleaned.splitlines() if line.strip()).strip()


def agent_model_chain() -> list[tuple[str, str]]:
    """Primary glasses model, then optional fallback. Dedupes identical pairs."""
    chain: list[tuple[str, str]] = []
    if not HERMES_AGENT_MODEL.strip():
        chain.append(("", ""))
    for model, provider in (
        (HERMES_AGENT_MODEL, HERMES_AGENT_PROVIDER),
        (HERMES_AGENT_FALLBACK_MODEL, HERMES_AGENT_FALLBACK_PROVIDER),
    ):
        model = (model or "").strip()
        provider = (provider or "").strip()
        if not model:
            continue
        pair = (model, provider)
        if pair not in chain:
            chain.append(pair)
    return chain


def ask_hermes(
    text: str,
    image_path: str | None = None,
    resume: str | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> tuple[str | None, str | None]:
    """Send text (and optionally an image) to Hermes Agent.

    Returns (reply, session_id). session_id enables conversation memory
    via --resume on the next query; either value may be None.
    """
    cmd = [HERMES_BIN, "chat", "-q", text, "-Q", "--cli", "--accept-hooks"]
    if model:
        cmd += ["-m", model]
    if provider:
        cmd += ["--provider", provider]
    if image_path:
        cmd += ["--image", image_path]
    if resume:
        cmd += ["--resume", resume]
    timeout_s = CLI_TIMEOUT_S if image_path else max(60, CLI_TIMEOUT_S)
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env={**os.environ, "HERMES_NO_COLOR": "1"},
        )
        session_id = extract_session_id(result.stderr)
        if result.returncode != 0:
            return "Error: Hermes could not complete the request.", None
        output = strip_cli_warnings(result.stdout.strip())
        if output:
            # -Q should print only the reply; if box UI sneaks in, unwrap it
            if BOX_CHARS & set(output):
                reply = extract_hermes_reply(output)
                if reply:
                    return strip_cli_warnings(reply), session_id
            return output, session_id
        if result.stderr.strip():
            # No reply on stdout - return the error text sans session line
            err = "\n".join(
                line for line in result.stderr.strip().splitlines()
                if not line.startswith("session_id:")
            ).strip()
            err = strip_cli_warnings(err)
            return ("Error: Hermes returned no answer." if err else None), None
        return None, session_id
    except subprocess.TimeoutExpired:
        return "Sorry, Hermes took too long to respond.", None
    except Exception as e:
        print(f"[Hermes] Error: {e}")
        return f"Error: {e}", None


# ── Streaming Hermes (warm API, CLI fallback) ──────────────────────────────

# Sentence boundary: end punctuation plus space, or end of string.
_SPEAK_BOUNDARY_RE = re.compile(r'[\.!\?…]["\'\)\]]*(?:\s+|$)')


def is_search_tool(tool: str | None) -> bool:
    """Web lookups: slow enough (seconds) to ack the moment they start."""
    name = (tool or "").lower()
    return any(k in name for k in ("search", "web", "browser", "extract", "fetch"))


def ack_phrase(tool: str | None, visual: bool) -> str:
    """Short spoken filler while a slow turn works (see ACK_ENABLED)."""
    if visual:
        return "Let me look."
    if is_search_tool(tool):
        return "Searching now."
    return "One sec."


def split_speakable(buffer: str) -> tuple[str, str]:
    """Peel the first finished sentence off a growing buffer.

    Returns (speak_now, remainder). speak_now is empty until a sentence
    boundary lands, so TTS can start on the first finished sentence.
    """
    if not buffer:
        return "", ""
    match = _SPEAK_BOUNDARY_RE.search(buffer)
    if not match:
        return "", buffer
    spoken = buffer[:match.end()].strip()
    rest = buffer[match.end():]
    return (spoken, rest) if spoken else ("", buffer)


def sse_delta_text(payload: dict) -> str:
    """Extract assistant text from an OpenAI chat.completion.chunk payload."""
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    delta = choices[0].get("delta") or {}
    content = delta.get("content")
    return content if isinstance(content, str) else ""


def _api_user_content(text: str, photo: bytes | None) -> str | list:
    if not photo:
        return text
    return [
        {"type": "text", "text": text},
        {
            "type": "image_url",
            "image_url": {
                "url": "data:image/jpeg;base64," + base64.b64encode(photo).decode(),
            },
        },
    ]


async def ask_hermes_api(
    text: str,
    photo: bytes | None,
    resume: str | None,
    on_text,
    model: str | None = None,
    provider: str | None = None,
    on_tool=None,
) -> tuple[str | None, str | None]:
    """Stream a turn through the warm Hermes API server.

    on_text is called with each token/string delta. Raises on transport or
    HTTP errors so the caller can fall back to the CLI.
    """
    try:
        import aiohttp
    except ImportError as exc:
        raise RuntimeError("aiohttp not installed") from exc

    if not HERMES_API_KEY:
        raise RuntimeError("no API_SERVER_KEY")

    headers = {
        "Authorization": "Bearer " + HERMES_API_KEY,
        "Content-Type": "application/json",
        "X-Hermes-Session-Key": HERMES_SESSION_KEY,
    }
    if resume:
        headers["X-Hermes-Session-Id"] = resume

    body: dict = {
        "stream": True,
        "messages": [
            {"role": "system", "content": CLAUDE_SYSTEM},
            {"role": "user", "content": _api_user_content(text, photo)},
        ],
    }
    if model:
        body["model"] = model
    else:
        body["model"] = "hermes-agent"
    if provider:
        # Explicit provider makes the API honor `model` even when
        # direct_model_requests is off (bare model names are ignored).
        body["provider"] = provider
    timeout = aiohttp.ClientTimeout(total=CLI_TIMEOUT_S, sock_read=90)
    collected: list[str] = []
    session_id = resume

    async with aiohttp.ClientSession(timeout=timeout) as http:
        async with http.post(
            HERMES_API_BASE + "/v1/chat/completions",
            headers=headers,
            json=body,
        ) as resp:
            if resp.status != 200:
                err = await resp.text()
                raise RuntimeError(f"HTTP {resp.status}: {err[:240]}")
            session_id = resp.headers.get("X-Hermes-Session-Id") or resume
            buf = b""
            async for chunk in resp.content.iter_any():
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    raw = line.decode("utf-8", "replace").strip()
                    if not raw or raw.startswith("event:"):
                        continue
                    if not raw.startswith("data:"):
                        continue
                    data = raw[5:].strip()
                    if data == "[DONE]":
                        buf = b""
                        break
                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if payload.get("error"):
                        raise RuntimeError("Hermes API reported a stream error")
                    # Hermes interleaves `event: hermes.tool.progress`
                    # frames ({"tool":..., "status":"running"}) with the
                    # completion chunks.
                    if on_tool and payload.get("tool"):
                        await on_tool(payload)
                        continue
                    piece = sse_delta_text(payload)
                    if piece:
                        collected.append(piece)
                        await on_text(piece)

    reply = strip_cli_warnings("".join(collected).strip()) or None
    return reply, session_id


async def stream_hermes_reply(
    text: str,
    photo: bytes | None,
    image_path: str | None,
    resume: str | None,
    resume_source: str | None,
    on_text,
    resume_model: str | None = None,
    resume_provider: str | None = None,
    on_tool=None,
) -> tuple[str | None, str | None, str, str | None, str | None]:
    """Prefer the warm streaming API; fall back to a CLI spawn.

    Returns (reply, session_id, path, model, provider). Resume is only sent
    to the model/provider that created the stored session — a Flash failure
    must not hand that session id to Gemini.
    """
    chain = agent_model_chain()
    if HERMES_API_ENABLED:
        last_error = None
        for model, provider in chain:
            streamed_any = False
            tool_started = False
            this_resume = resume_for_pair(
                resume, resume_source, resume_model, resume_provider,
                model, provider, "api",
            )

            async def _tap(piece: str):
                nonlocal streamed_any
                streamed_any = True
                await on_text(piece)

            async def _tool_tap(event: dict):
                nonlocal tool_started
                tool_started = True
                if on_tool:
                    await on_tool(event)

            print(f"[Bridge] API try {model}" + (f"/{provider}" if provider else ""))
            try:
                reply, session_id = await ask_hermes_api(
                    text, photo, this_resume, _tap,
                    model=model, provider=provider or None, on_tool=_tool_tap,
                )
                if not reply:
                    raise RuntimeError("empty API stream")
                return reply, session_id, "api", model, provider
            except Exception as error:  # noqa: BLE001 - next model or CLI
                last_error = error
                if tool_started:
                    # Retrying could repeat an email, file write or other action.
                    warning = " The connection stopped after a tool started. Please check the action before retrying."
                    await on_text(warning)
                    return warning.strip(), this_resume, "api", model, provider
                if streamed_any:
                    print(f"[Bridge] API stream died after tokens ({error})")
                    return None, this_resume, "api", model, provider
                print(f"[Bridge] API {model} failed ({error})")
        print(f"[Bridge] API unavailable ({last_error}); CLI fallback")

    last_cli_error = None
    for model, provider in chain:
        this_resume = resume_for_pair(
            resume, resume_source, resume_model, resume_provider,
            model, provider, "cli",
        )
        cli_text = text
        if not this_resume and VOICE_PERSONA not in text:
            cli_text = VOICE_PERSONA + text
        print(f"[Bridge] CLI try {model}" + (f"/{provider}" if provider else ""))
        reply, session_id = await asyncio.to_thread(
            ask_hermes, cli_text, image_path, this_resume, model, provider or None,
        )
        if reply and not str(reply).startswith("Error:") and reply != (
            "Sorry, Hermes took too long to respond."
        ):
            await on_text(reply)
            return reply, session_id, "cli", model, provider
        last_cli_error = reply
    if last_cli_error:
        await on_text(last_cli_error)
        return last_cli_error, None, "cli", None, None
    return None, None, "cli", None, None


# ── Text-to-Speech ─────────────────────────────────────────────────────────

def synthesize_speech(text: str) -> bytes | None:
    """Convert text to speech. Always returns raw PCM16 mono 24kHz -
    the only format the app can play."""
    # Try Edge TTS first (better quality)
    try:
        import edge_tts

        mp3_tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        mp3_tmp.close()
        wav_tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        wav_tmp.close()
        try:
            async def _synth():
                communicate = edge_tts.Communicate(text, "en-US-AriaNeural")
                await communicate.save(mp3_tmp.name)

            asyncio.run(_synth())

            # Decode MP3 → PCM16 mono 24kHz WAV. afconvert on macOS,
            # ffmpeg elsewhere (Linux).
            if shutil.which("afconvert"):
                cmd = ["afconvert", "-f", "WAVE", "-d", "LEI16@24000", "-c", "1",
                       mp3_tmp.name, wav_tmp.name]
            elif shutil.which("ffmpeg"):
                cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", mp3_tmp.name,
                       "-ar", "24000", "-ac", "1", "-sample_fmt", "s16",
                       wav_tmp.name]
            else:
                cmd = None
                print("[TTS] Neither afconvert nor ffmpeg found")

            if cmd:
                result = subprocess.run(cmd, capture_output=True, timeout=30)
                if result.returncode == 0:
                    with wave.open(wav_tmp.name, "rb") as wf:
                        return wf.readframes(wf.getnframes())
                print(f"[TTS] decode failed: {result.stderr.decode()[:200]}")
        finally:
            # NamedTemporaryFile(delete=False) - always clean up, whether
            # synthesis/decode succeeded, failed, or raised.
            for path in (mp3_tmp.name, wav_tmp.name):
                try:
                    os.unlink(path)
                except OSError:
                    pass
    except ImportError:
        pass
    except Exception as e:
        print(f"[TTS] Edge TTS unavailable ({type(e).__name__}); using local speech")

    # Fallback: macOS say command, directly as PCM16 24kHz WAV
    if not shutil.which("say"):
        print("[TTS] No 'say' fallback available on this platform")
        return None
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    try:
        result = subprocess.run(
            ["say", "-o", tmp.name,
             "--file-format=WAVE", "--data-format=LEI16@24000", text],
            capture_output=True, timeout=30,
        )
        if result.returncode != 0:
            print(f"[TTS] 'say' failed: {result.stderr.decode()[:200]}")
            return None
        with wave.open(tmp.name, "rb") as wf:
            return wf.readframes(wf.getnframes())
    except Exception as e:
        print(f"[TTS] Error: {e}")
        return None
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


# ── WebSocket Handler ──────────────────────────────────────────────────────

async def await_photo(websocket, timeout: float = 25.0) -> bytes | None:
    """Wait for the app to answer a capture_photo request.

    Discards mic-audio (binary) frames that arrive meanwhile. Returns the
    decoded JPEG bytes, or None on photo_error or timeout.
    """
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            print("[Bridge] Photo wait timed out")
            return None
        try:
            message = await asyncio.wait_for(websocket.recv(), timeout=remaining)
        except asyncio.TimeoutError:
            print("[Bridge] Photo wait timed out")
            return None
        if isinstance(message, bytes):
            continue  # stray binary frame while waiting - drop it
        try:
            data = json.loads(message)
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[Bridge] Malformed JSON while awaiting photo, ignored: {e}")
            continue
        if not isinstance(data, dict):
            print(f"[Bridge] Non-object JSON while awaiting photo, ignored: {data!r}")
            continue
        msg_type = data.get("type")
        if msg_type == "photo":
            try:
                return base64.b64decode(data.get("data", ""))
            except Exception as e:
                print(f"[Bridge] Bad photo payload: {e}")
                return None
        if msg_type == "photo_error":
            print(f"[Bridge] Photo error from app: {data.get('message')}")
            return None
        if msg_type == "debug":
            print(f"[App] {data.get('msg')}")
        # any other message type: keep waiting


async def process_query(websocket, text: str, conn_state: dict | None = None,
                        want_tts: bool | None = None):
    """Answer a text query: photo capture if visual, Hermes, TTS reply.

    The app transcribes on-device and sends {"type":"query"} text.
    conn_state carries per-connection context: {"last_photo_at": float}.
    want_tts: app's per-query choice of bridge TTS; None falls back to the
    HERMES_BRIDGE_TTS env default.

    Hermes turns stream speakable chunks as ``response_delta`` (and, when
    bridge TTS is on, per-sentence PCM + ``audio_clip``) so the glasses can
    start talking before the agent finishes.
    """
    bridge_tts = BRIDGE_TTS if want_tts is None else bool(want_tts)
    if conn_state is None:
        conn_state = {"last_photo_at": 0.0}

    first_token_at = None
    audio_started = False  # an audio_start frame has gone out (ack or reply)
    reply_audio = False    # reply speech (not just the ack) has gone out
    send_lock = asyncio.Lock()
    ack_sent = False
    turn_done = False
    ack_tasks: list[asyncio.Task] = []

    async def _send_ack(phrase: str):
        nonlocal audio_started
        try:
            # Re-checked here, not just in request_ack: this task runs a beat
            # later, and reply text may have landed in between.
            if first_token_at is not None or turn_done:
                return
            print(f"[Bridge] ack: {phrase}")
            await websocket.send(json.dumps({"type": "ack", "text": phrase}))
            if not bridge_tts:
                return
            pcm = await asyncio.to_thread(synthesize_speech, phrase)
            async with send_lock:
                # Reply speech already started (or the turn ended): a late
                # "one sec" would talk over it or trail after it.
                if not pcm or reply_audio or turn_done:
                    return
                if not audio_started:
                    await websocket.send(json.dumps({"type": "audio_start"}))
                    audio_started = True
                for i in range(0, len(pcm), 16384):
                    await websocket.send(pcm[i:i + 16384])
                # "ack": true lets tools tell this clip from reply clips;
                # the app ignores the extra key.
                await websocket.send(json.dumps({"type": "audio_clip", "ack": True}))
        except Exception as error:  # noqa: BLE001 - an ack must never break a turn
            print(f"[Bridge] ack failed ({error})")

    def request_ack(phrase: str):
        """At most one ack per turn, and never once reply text exists."""
        nonlocal ack_sent
        if not ACK_ENABLED or ack_sent or turn_done or first_token_at is not None:
            return
        ack_sent = True
        ack_tasks.append(asyncio.create_task(_send_ack(phrase)))

    # ── Capture a photo for visual/deictic queries ──
    photo = None
    query_text = text
    if should_capture_photo(text, conn_state.get("last_photo_at", 0.0),
                            time.monotonic()):
        print("[Bridge] Visual query - requesting photo from glasses")
        await websocket.send(json.dumps({"type": "capture_photo"}))
        request_ack(ack_phrase(None, visual=True))
        photo = await await_photo(websocket)
        if photo:
            conn_state["last_photo_at"] = time.monotonic()
            print(f"[Bridge] Photo received: {len(photo)} bytes")
        else:
            print("[Bridge] No photo - answering text-only")
            query_text = ("(No photo could be captured from the glasses.) "
                          + text)

    canon_brain = _canon_brain(BRAIN)
    started = time.monotonic()
    buffer = ""
    streamed = False
    collected: list[str] = []

    async def emit_speakable(chunk: str):
        nonlocal audio_started, reply_audio, streamed
        streamed = True
        await websocket.send(json.dumps({
            "type": "response_delta",
            "text": chunk,
        }))
        if not bridge_tts:
            return
        print(f"[Bridge] TTS clip ({len(chunk)} chars)")
        pcm = await asyncio.to_thread(synthesize_speech, chunk)
        async with send_lock:
            reply_audio = True
            if not audio_started:
                await websocket.send(json.dumps({"type": "audio_start"}))
                audio_started = True
            if pcm:
                for i in range(0, len(pcm), 16384):
                    await websocket.send(pcm[i:i + 16384])
                await websocket.send(json.dumps({"type": "audio_clip"}))

    async def on_raw(piece: str):
        nonlocal buffer, first_token_at
        if not piece:
            return
        collected.append(piece)
        if first_token_at is None:
            first_token_at = time.monotonic()
            print(f"[Bridge] first_token {first_token_at - started:.2f}s")
        buffer += piece
        while True:
            speakable, buffer = split_speakable(buffer)
            if not speakable:
                break
            await emit_speakable(speakable)

    async def on_tool(event: dict):
        # Only web lookups ack at once; quick internal tools (memory, files)
        # would otherwise add "One sec." to fast turns. The timer still
        # covers any tool that turns out slow.
        if event.get("status") == "running" and is_search_tool(event.get("tool")):
            request_ack(ack_phrase(event.get("tool"), visual=False))

    async def _ack_if_still_silent():
        await asyncio.sleep(ACK_AFTER_S)
        request_ack(ack_phrase(None, visual=False))

    ack_timer = (asyncio.create_task(_ack_if_still_silent())
                 if ACK_ENABLED and ACK_AFTER_S > 0 else None)
    try:
        path = canon_brain
        if canon_brain in ("anthropic", "openai", "gemini"):
            print(f"[Bridge] Asking {canon_brain} ({CLAUDE_MODEL})...")
            response = await asyncio.to_thread(ask_provider, canon_brain, query_text, photo)
            if response:
                await on_raw(response)
        else:
            image_path = None
            if photo:
                img_tmp = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
                img_tmp.write(photo)
                img_tmp.close()
                image_path = img_tmp.name
            resume = load_session()
            resume_source = load_session_source()
            resume_model, resume_provider = load_session_pair()
            print(
                f"[Bridge] Asking Hermes... (session: {resume or 'new'}, "
                f"via={'api' if (HERMES_API_ENABLED and HERMES_API_KEY) else 'cli'}, "
                f"model={HERMES_AGENT_MODEL}/{HERMES_AGENT_PROVIDER}"
                f" fallback={HERMES_AGENT_FALLBACK_MODEL or '-'})"
            )
            try:
                response, session_id, path, used_model, used_provider = await stream_hermes_reply(
                    query_text, photo, image_path, resume, resume_source, on_raw,
                    resume_model=resume_model, resume_provider=resume_provider,
                    on_tool=on_tool,
                )
                if resume and not response and not collected:
                    print("[Bridge] Resume failed - retrying with a fresh session")
                    clear_session()
                    retry_text = query_text
                    if VOICE_PERSONA not in retry_text:
                        retry_text = VOICE_PERSONA + query_text
                    response, session_id, path, used_model, used_provider = await stream_hermes_reply(
                        retry_text, photo, image_path, None, None, on_raw,
                        on_tool=on_tool,
                    )
                if session_id:
                    store_session(
                        session_id,
                        source=path if path in ("api", "cli") else "cli",
                        model=used_model,
                        provider=used_provider,
                    )
            finally:
                if image_path:
                    try:
                        os.unlink(image_path)
                    except OSError:
                        pass
    finally:
        turn_done = True
        if ack_timer:
            ack_timer.cancel()

    if buffer.strip():
        await emit_speakable(buffer.strip())
        buffer = ""

    response_text = strip_cli_warnings("".join(collected).strip()) or (
        "I'm not sure what to say."
    )

    log_turn(text, response_text, photo, canon_brain,
             load_session() if canon_brain == "hermes" else None)

    elapsed = time.monotonic() - started
    first = (first_token_at - started) if first_token_at else elapsed
    print(
        f"[Bridge] Hermes via {path}: first_token={first:.2f}s "
        f"total={elapsed:.2f}s :: {response_text[:100]}..."
    )

    await websocket.send(json.dumps({
        "type": "response",
        "text": response_text,
        "tts": bridge_tts,
        "streamed": streamed,
    }))

    if bridge_tts:
        async with send_lock:
            # Keyed on reply_audio, not audio_started: an ack may have opened
            # the stream, and the reply itself must still be spoken.
            if not reply_audio:
                print("[Bridge] Generating speech...")
                if not audio_started:
                    await websocket.send(json.dumps({"type": "audio_start"}))
                    audio_started = True
                audio_data = await asyncio.to_thread(synthesize_speech, response_text)
                if audio_data:
                    for i in range(0, len(audio_data), 16384):
                        await websocket.send(audio_data[i:i + 16384])
                        await asyncio.sleep(0.01)
            await websocket.send(json.dumps({"type": "audio_end"}))
    print("[Bridge] Response complete.")


def is_authorized(websocket) -> bool:
    """When AUTH_TOKEN is set, require ?token=<AUTH_TOKEN> in the WS path."""
    if not AUTH_TOKEN:
        return True
    try:
        path = websocket.request.path if websocket.request else ""
        query = parse_qs(urlparse(path).query)
        return hmac.compare_digest(query.get("token", [""])[0], AUTH_TOKEN)
    except Exception:
        return False


async def handle_connection(websocket):
    """Handle a single glasses connection."""
    if not is_authorized(websocket):
        print(f"[Bridge] REJECTED unauthorized connection from "
              f"{websocket.remote_address}")
        await websocket.close(code=4401, reason="unauthorized")
        return

    print(f"[Bridge] Glasses connected from {websocket.remote_address}")

    # Send welcome to confirm connection
    await websocket.send(json.dumps({"type": "welcome"}))
    # Per-connection context for photo-recency suppression
    conn_state = {"last_photo_at": 0.0}

    try:
        async for message in websocket:
            if isinstance(message, bytes):
                # Binary frames were the legacy mic-audio path; the app
                # transcribes on-device now. Ignore them.
                continue

            try:
                data = json.loads(message)
            except (json.JSONDecodeError, ValueError) as e:
                print(f"[Bridge] Malformed JSON frame ignored: {e}")
                continue
            if not isinstance(data, dict):
                print(f"[Bridge] Non-object JSON frame ignored: {data!r}")
                continue
            msg_type = data.get("type")

            if msg_type == "query":
                # App transcribed on-device and sends text directly
                text = (data.get("text") or "").strip()
                if text:
                    print(f"[Bridge] Query: {text}")
                    await process_query(websocket, text, conn_state,
                                        data.get("tts"))
                else:
                    await websocket.send(json.dumps({
                        "type": "error",
                        "message": "Empty query."
                    }))

            elif msg_type == "new_session":
                # Forget the conversation; next query starts fresh
                clear_session()
                clear_claude_history()
                conn_state["last_photo_at"] = 0.0
                print("[Bridge] Conversation reset by app")
                await websocket.send(json.dumps({"type": "session_reset"}))

            elif msg_type == "debug":
                print(f"[App] {data.get('msg')}")

            elif msg_type == "ping":
                await websocket.send(json.dumps({"type": "pong"}))

    except websockets.exceptions.ConnectionClosed:
        print("[Bridge] Glasses disconnected")
    except Exception as e:
        print(f"[Bridge] Error: {e}")
    finally:
        print("[Bridge] Connection closed")


def local_ip() -> str:
    """Best-effort LAN IP for the connection hint."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "<your-mac-ip>"


async def main():
    if not AUTH_TOKEN:
        print(f"""
!!! WARNING: no HERMES_BRIDGE_TOKEN set - this bridge is UNAUTHENTICATED.
!!! It is listening on ws://{HOST}:{PORT}/voice - anyone who can reach
!!! that address on the network can drive the agent (tool access
!!! included) with no credentials. Set HERMES_BRIDGE_TOKEN before
!!! exposing this beyond localhost.
""")
    if _canon_brain(BRAIN) == "hermes":
        primary = f"{HERMES_AGENT_MODEL}/{HERMES_AGENT_PROVIDER}"
        fb = (f" fallback {HERMES_AGENT_FALLBACK_MODEL}"
              if HERMES_AGENT_FALLBACK_MODEL else "")
        if HERMES_API_ENABLED and HERMES_API_KEY:
            hermes_path = f"hermes API {primary}{fb}"
        elif HERMES_API_ENABLED:
            hermes_path = f"hermes CLI {primary} (no API key)"
        else:
            hermes_path = f"hermes CLI {primary}"
    else:
        hermes_path = f"{BRAIN} ({CLAUDE_MODEL})"
    print(f"""
╔══════════════════════════════════════════════════════════╗
║              Hermes Glasses Bridge Server                ║
║                                                          ║
║  Listening on ws://{HOST}:{PORT}/voice                       ║
║  STT: on the phone - the app sends text queries          ║
║  Brain: {hermes_path}
║                                                          ║
║  Connect your glasses app to:                            ║
║  ws://{local_ip()}:{PORT}/voice                             ║
╚══════════════════════════════════════════════════════════╝
""")
    # Glasses photos arrive as a single large base64-encoded JSON text frame
    # (a 1-3 MB raw JPEG becomes an even bigger base64 string), so raise
    # max_size well above the websockets default of 1 MiB to avoid a 1009
    # close before the frame is fully received.
    async with websockets.serve(handle_connection, HOST, PORT, max_size=16 * 1024 * 1024):
        await asyncio.Future()  # run forever


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[Bridge] Shutting down.")
