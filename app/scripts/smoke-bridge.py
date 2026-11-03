#!/usr/bin/env python3
"""Live smoke test for the running bridge, speaking the app's protocol.

Runs three real turns through Hermes (costs a few model calls):
  plain   - short answer; expects no ack
  search  - forces a web search; expects "Searching now." before the reply
  visual  - camera question; answers capture_photo with a JPEG and expects
            "Let me look."
Each turn asks for bridge TTS like the phone does, and checks the ack's
audio arrives before the reply's.

  python3 scripts/smoke-bridge.py [ws://host:8765/voice] [--only=plain,search]
Token comes from bridge/.env. Exit 0 = all pass.
"""
import asyncio
import base64
import json
import os
import subprocess
import sys
import tempfile
import time

import websockets

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def token() -> str:
    with open(os.path.join(ROOT, "bridge", ".env")) as env:
        for line in env:
            if line.startswith("HERMES_BRIDGE_TOKEN="):
                return line.split("=", 1)[1].strip()
    return ""


def test_jpeg() -> bytes:
    """A small real JPEG (macOS desktop picture), so vision has pixels."""
    out = os.path.join(tempfile.gettempdir(), "smoke-bridge.jpg")
    for src in ("/System/Library/CoreServices/DefaultDesktop.heic",
                "/Library/Desktop Pictures/Solid Colors/Blue.png"):
        if os.path.exists(src) and subprocess.run(
                ["sips", "-s", "format", "jpeg", "-Z", "640", src, "--out", out],
                capture_output=True).returncode == 0:
            return open(out, "rb").read()
    raise SystemExit("no source image for the visual turn")


TURNS = {
    "plain": ("Reply with just the word pong.", None),
    "search": ("Use web search: what is the latest version of the Tailscale "
               "iOS app? Answer in one short sentence.", "Searching now."),
    "visual": ("What am I looking at?", "Let me look."),
}


async def run_turn(url: str, name: str) -> bool:
    text, want_ack = TURNS[name]
    started = time.monotonic()
    t = lambda: round(time.monotonic() - started, 1)  # noqa: E731
    events, audio_order = [], []  # audio_order: "ack"/"reply" per clip
    async with websockets.connect(url, max_size=16 * 1024 * 1024) as ws:
        assert json.loads(await ws.recv())["type"] == "welcome"
        await ws.send(json.dumps({"type": "query", "text": text, "tts": True}))
        pending_audio = False
        while True:
            msg = await asyncio.wait_for(ws.recv(), 180)
            if isinstance(msg, bytes):
                pending_audio = True
                continue
            m = json.loads(msg)
            kind = m["type"]
            if kind == "capture_photo":
                photo = base64.b64encode(test_jpeg()).decode()
                await ws.send(json.dumps({"type": "photo", "data": photo}))
            # The bridge tags the ack's clip; every other clip is reply speech.
            if kind in ("audio_clip", "audio_end") and pending_audio:
                audio_order.append("ack" if m.get("ack") else "reply")
                pending_audio = False
            events.append((t(), kind, (m.get("text") or "")[:70]))
            if kind == "audio_end" or kind == "error":
                break
    acks = [e for e in events if e[1] == "ack"]
    first_delta = next((e[0] for e in events if e[1] == "response_delta"), None)
    reply = next((e[2] for e in events if e[1] == "response"), "")
    checks = {
        "got reply": bool(reply),
        # No ack expected on a plain turn - unless Hermes itself was slower
        # than the bridge's 10 s timer, where "One sec." is correct.
        "ack as expected": (
            [a[2] for a in acks] == [want_ack] if want_ack
            else (not acks or (acks[0][2] == "One sec." and acks[0][0] >= 9.5))),
        "ack before reply text": (not acks or first_delta is None
                                  or acks[0][0] <= first_delta),
        # The ack's audio may be dropped if the reply won the race; if it
        # played, it played once and first. The reply is always spoken.
        "reply spoken, ack clip (if any) first": (
            "reply" in audio_order and audio_order.count("ack") <= 1
            and ("ack" not in audio_order or audio_order[0] == "ack")),
    }
    ok = all(checks.values())
    print(f"\n[{name}] {'PASS' if ok else 'FAIL'}  ack={[a[2] for a in acks]} "
          f"ack_at={acks[0][0] if acks else '-'}s first_text={first_delta}s "
          f"total={events[-1][0]}s audio={audio_order}")
    print(f"  reply: {reply}")
    for label, passed in checks.items():
        print(f"  {'ok ' if passed else 'BAD'} {label}")
    return ok


async def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--only")]
    base = args[0] if args else "ws://127.0.0.1:8765/voice"
    only = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--only=")),
                ",".join(TURNS))
    url = f"{base}?token={token()}"
    results = [await run_turn(url, n) for n in only.split(",")]
    print("\nALL PASS" if all(results) else "\nSOME FAILED")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    asyncio.run(main())
