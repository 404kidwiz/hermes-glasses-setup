#!/usr/bin/env python3
"""
Hermes Glasses Dashboard - chat history + photo gallery for the glasses bridge.

Reads:
  ~/.hermes_glasses_history/turns.jsonl   (live turns, written by hermes_bridge.log_turn)
  ~/.hermes_glasses_history/photos/*.jpg  (glasses photos, kept per turn)
  ~/.hermes/state.db                      (backfill: past bridge Hermes sessions)

Run:  python3 dashboard.py            → http://localhost:8770
Auth: same HERMES_BRIDGE_TOKEN as the bridge (?token=...) on non-localhost.
"""

import json
import os
import re
import sqlite3
import sys
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HISTORY_DIR = os.environ.get(
    "HERMES_GLASSES_HISTORY_DIR",
    os.path.expanduser("~/.hermes_glasses_history"),
)
PHOTO_DIR = os.path.join(HISTORY_DIR, "photos")
TURNS_FILE = os.path.join(HISTORY_DIR, "turns.jsonl")
STATE_DB = os.path.expanduser("~/.hermes/state.db")

AUTH_TOKEN = os.environ.get("HERMES_BRIDGE_TOKEN", "")
PORT = int(os.environ.get("HERMES_GLASSES_DASHBOARD_PORT", "8770"))
HOST = os.environ.get("HERMES_GLASSES_DASHBOARD_HOST", "0.0.0.0")

# Matches the bridge's VOICE_PERSONA prefix on the first user message of a
# glasses session in state.db (used only for backfill).
PERSONA_MARKERS = [
    "voice assistant running on smart glasses",
    "voice-optimized",
]
# Backfilled sessions have no photos; live turns carry photo filenames.
BACKFILL_SOURCE = "hermes-session"

_turns_cache: list[dict] = []
_turns_mtime = 0.0
_lock = threading.Lock()


def _read_live_turns() -> list[dict]:
    """Load turns.jsonl if it changed since last read."""
    global _turns_mtime
    try:
        mtime = os.path.getmtime(TURNS_FILE)
    except OSError:
        return []
    with _lock:
        if mtime == _turns_mtime and _turns_cache:
            return _turns_cache
    turns = []
    try:
        with open(TURNS_FILE) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    turns.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    with _lock:
        _turns_cache[:] = turns
        _turns_mtime = mtime
    return turns


_PERSONA_RE = re.compile(
    r"^\(You are a voice assistant running on smart glasses\..*?\)\s*",
    re.DOTALL,
)


def _strip_persona(text: str) -> str:
    return _PERSONA_RE.sub("", text or "")


def _backfill_sessions() -> list[dict]:
    """Pull past glasses bridge sessions out of the Hermes state DB."""
    turns = []
    try:
        con = sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        cur = con.cursor()
        # Sessions whose first user message carries the voice persona.
        rows = cur.execute(
            """
            SELECT m.session_id,
                   MIN(m.timestamp) AS first_ts,
                   MAX(m.timestamp) AS last_ts,
                   COUNT(*) AS n_msgs
            FROM messages m
            WHERE m.content LIKE '%voice assistant running on smart glasses%'
            GROUP BY m.session_id
            ORDER BY first_ts DESC
            """
        ).fetchall()
        for meta in rows:
            sid = meta["session_id"]
            msgs = cur.execute(
                """
                SELECT role, content, timestamp
                FROM messages
                WHERE session_id = ? AND role IN ('user','assistant')
                  AND content IS NOT NULL AND content != ''
                ORDER BY timestamp
                """,
                (sid,),
            ).fetchall()
            # First user message carries the persona; drop it from display.
            first_user_seen = False
            for m in msgs:
                content = m["content"]
                if m["role"] == "user" and not first_user_seen:
                    content = _strip_persona(content)
                    first_user_seen = True
                    if not content.strip():
                        continue
                turns.append(
                    {
                        "ts": m["timestamp"],
                        "role": m["role"],
                        "text": content,
                        "session": sid,
                        "photo": None,
                        "source": BACKFILL_SOURCE,
                    }
                )
        con.close()
    except sqlite3.Error as error:
        print(f"[dashboard] state.db backfill failed: {error}", file=sys.stderr)
    return turns


def build_feed() -> dict:
    """Merge backfilled sessions with live logged turns, newest session first."""
    live = _read_live_turns()
    live_by_session: dict[str, list[dict]] = {}
    for t in live:
        sid = t.get("session") or "live"
        live_by_session.setdefault(sid, []).append(
            {
                "ts": t.get("ts", 0),
                "role": "user" if t.get("user") is not None else "assistant",
                "text": t.get("user") or t.get("reply") or "",
                "photo": t.get("photo"),
                "session": sid,
                "source": "live",
            }
        )
    # A live session and a backfilled one may share the session id: merge
    # message lists on ts order, live entries win on collision.
    backfill = _backfill_sessions()
    sessions: dict[str, list[dict]] = {}
    for t in backfill:
        sessions.setdefault(t["session"], []).append(t)
    for sid, items in live_by_session.items():
        sessions.setdefault(sid, []).extend(items)
    out = []
    for sid, items in sessions.items():
        items.sort(key=lambda x: x["ts"])
        # Dedupe identical (ts, role, text) pairs from live+backfill overlap.
        seen = set()
        merged = []
        for item in items:
            key = (round(item["ts"], 3), item["role"], item["text"])
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        out.append({"session": sid, "messages": merged})
    out.sort(key=lambda s: s["messages"][-1]["ts"] if s["messages"] else 0, reverse=True)
    return {"sessions": out}


def local_ip() -> str:
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Hermes Glasses — Dashboard</title>
<style>
  :root {
    --bg: #0b0d12; --panel: #12151d; --panel2: #171b26; --line: #232939;
    --text: #e8ebf2; --dim: #8a93a8; --accent: #5eead4; --accent2: #a78bfa;
    --you: #1d2b3a; --hermes: #1a222f;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  header {
    position: sticky; top: 0; z-index: 10; display: flex; align-items: center;
    gap: 12px; padding: 14px 20px; background: rgba(11,13,18,.85);
    backdrop-filter: blur(12px); border-bottom: 1px solid var(--line);
  }
  header h1 { font-size: 17px; margin: 0; font-weight: 650; letter-spacing: .2px; }
  header .dot { width: 9px; height: 9px; border-radius: 50%; background: var(--accent);
    box-shadow: 0 0 10px var(--accent); animation: pulse 2.2s infinite; }
  @keyframes pulse { 0%,100% {opacity:1} 50% {opacity:.45} }
  header .sub { color: var(--dim); font-size: 12px; margin-left: auto; }
  main { max-width: 860px; margin: 0 auto; padding: 20px 16px 80px; }
  .session {
    background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
    margin-bottom: 22px; overflow: hidden;
  }
  .session-head {
    display: flex; align-items: center; gap: 10px; padding: 12px 16px;
    background: var(--panel2); border-bottom: 1px solid var(--line);
    font-size: 13px; color: var(--dim); cursor: pointer; user-select: none;
  }
  .session-head b { color: var(--text); font-weight: 600; }
  .session-head .n { margin-left: auto; font-size: 12px; }
  .session-body { padding: 16px; display: flex; flex-direction: column; gap: 12px; }
  .session.collapsed .session-body { display: none; }
  .turn { display: flex; flex-direction: column; gap: 4px; }
  .turn .meta { font-size: 11px; color: var(--dim); display: flex; gap: 8px; align-items: center; }
  .turn .who { font-weight: 600; font-size: 11px; letter-spacing: .8px; text-transform: uppercase; }
  .turn.you .who { color: var(--accent); }
  .turn.hermes .who { color: var(--accent2); }
  .bubble {
    padding: 10px 14px; border-radius: 12px; font-size: 15px; line-height: 1.45;
    white-space: pre-wrap; word-break: break-word;
  }
  .turn.you .bubble { background: var(--you); border-top-left-radius: 4px; }
  .turn.hermes .bubble { background: var(--hermes); border-top-left-radius: 4px; }
  .turn img.photo {
    max-width: 320px; width: 100%; border-radius: 10px; margin-top: 6px;
    border: 1px solid var(--line); cursor: zoom-in; display: block;
  }
  .empty { text-align: center; color: var(--dim); padding: 60px 20px; font-size: 14px; }
  #lightbox {
    position: fixed; inset: 0; background: rgba(0,0,0,.88); display: none;
    align-items: center; justify-content: center; z-index: 100; cursor: zoom-out;
  }
  #lightbox img { max-width: 94vw; max-height: 92vh; border-radius: 8px; }
  .tabs { display: flex; gap: 8px; margin: 0 0 18px; }
  .tab {
    padding: 7px 16px; border-radius: 999px; border: 1px solid var(--line);
    background: var(--panel); color: var(--dim); font-size: 13px; cursor: pointer;
  }
  .tab.active { background: var(--accent); color: #071312; border-color: var(--accent); font-weight: 600; }
  .gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); gap: 12px; }
  .gallery .cell { position: relative; border-radius: 10px; overflow: hidden; border: 1px solid var(--line); }
  .gallery img { width: 100%; height: 180px; object-fit: cover; display: block; cursor: zoom-in; }
  .gallery .cap { position: absolute; bottom: 0; left: 0; right: 0; padding: 6px 8px;
    font-size: 11px; color: var(--text); background: linear-gradient(transparent, rgba(0,0,0,.85)); }
  .badge { font-size: 10px; padding: 2px 7px; border-radius: 999px; border: 1px solid var(--line); color: var(--dim); }
  .badge.live { color: var(--accent); border-color: var(--accent); }
</style>
</head>
<body>
<header>
  <div class="dot"></div>
  <h1>Hermes Glasses</h1>
  <span class="sub" id="hdr-sub">loading…</span>
</header>
<main>
  <div class="tabs">
    <button class="tab active" id="tab-chat" onclick="switchTab('chat')">Chat</button>
    <button class="tab" id="tab-photos" onclick="switchTab('photos')">Photos</button>
  </div>
  <div id="view-chat"></div>
  <div id="view-photos" style="display:none"><div class="gallery" id="gallery"></div></div>
</main>
<div id="lightbox" onclick="this.style.display='none'"><img id="lightbox-img"></div>
<script>
let feed = { sessions: [] };
let activeTab = 'chat';

async function refresh() {
  try {
    const res = await fetch('/api/feed');
    feed = await res.json();
    render();
  } catch (e) {
    document.getElementById('hdr-sub').textContent = 'offline — retrying';
  }
}

function fmtTime(ts) {
  const d = new Date(ts * 1000);
  return d.toLocaleString([], {month:'short', day:'numeric', hour:'2-digit', minute:'2-digit'});
}

function render() {
  const chat = document.getElementById('view-chat');
  const photos = [];
  const sessions = feed.sessions || [];
  if (!sessions.length) {
    chat.innerHTML = '<div class="empty">No glasses conversations yet.<br>Ask the glasses something — turns appear here live.</div>';
  } else {
    chat.innerHTML = sessions.map((s, si) => {
      const msgs = s.messages || [];
      const first = msgs[0], last = msgs[msgs.length - 1];
      const anyLive = msgs.some(m => m.source === 'live');
      const body = msgs.map(m => {
        if (m.photo) photos.push({photo: m.photo, text: m.text, ts: m.ts});
        const who = m.role === 'user' ? 'you' : 'hermes';
        const img = m.photo ? `<img class="photo" src="/photos/${encodeURIComponent(m.photo)}" onclick="zoom(this.src)" loading="lazy">` : '';
        return `<div class="turn ${who}">
          <div class="meta"><span class="who">${who === 'you' ? 'You' : 'Hermes'}</span><span>${fmtTime(m.ts)}</span></div>
          <div class="bubble">${escapeHtml(m.text)}${img}</div>
        </div>`;
      }).join('');
      return `<section class="session" id="s-${si}">
        <div class="session-head" onclick="this.parentElement.classList.toggle('collapsed')">
          <b>${first ? fmtTime(first.ts) : ''}</b>
          <span class="badge ${anyLive ? 'live' : ''}">${anyLive ? 'live log' : 'hermes session'}</span>
          <span class="n">${msgs.length} messages</span>
        </div>
        <div class="session-body">${body}</div>
      </section>`;
    }).join('');
  }
  // Photos tab: live turns only (backfill has none), newest first.
  const gallery = document.getElementById('gallery');
  const livePhotos = (feed.sessions || []).flatMap(s => (s.messages || []).filter(m => m.photo && m.source === 'live'));
  if (!livePhotos.length) {
    gallery.innerHTML = '<div class="empty">No glasses photos saved yet.</div>';
  } else {
    gallery.innerHTML = livePhotos.map(m =>
      `<div class="cell"><img src="/photos/${encodeURIComponent(m.photo)}" loading="lazy" onclick="zoom(this.src)">
       <div class="cap">${escapeHtml((m.text || '').slice(0, 60))}</div></div>`).join('');
  }
  const total = (feed.sessions || []).reduce((a, s) => a + (s.messages || []).length, 0);
  document.getElementById('hdr-sub').textContent =
    `${(feed.sessions || []).length} sessions · ${total} messages · ${livePhotos.length} photos`;
}

function switchTab(t) {
  activeTab = t;
  document.getElementById('view-chat').style.display = t === 'chat' ? '' : 'none';
  document.getElementById('view-photos').style.display = t === 'photos' ? '' : 'none';
  document.getElementById('tab-chat').classList.toggle('active', t === 'chat');
  document.getElementById('tab-photos').classList.toggle('active', t === 'photos');
}

function zoom(src) {
  document.getElementById('lightbox-img').src = src;
  document.getElementById('lightbox').style.display = 'flex';
}

function escapeHtml(s) {
  return (s || '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

refresh();
setInterval(refresh, 4000);
</script>
</body>
</html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # quiet access log
        pass

    def _authorized(self) -> bool:
        if not AUTH_TOKEN:
            return True
        parsed = urllib.parse.urlparse(self.path)
        if self.client_address[0] in ("127.0.0.1", "::1"):
            return True
        q = urllib.parse.parse_qs(parsed.query)
        return q.get("token", [""])[0] == AUTH_TOKEN

    def _send(self, code: int, body: bytes, ctype: str, cache: bool = False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public" if cache else "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path in ("/", "/index.html"):
            if not self._authorized():
                return self._send(403, b"forbidden", "text/plain")
            return self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        if path == "/api/feed":
            if not self._authorized():
                return self._send(403, b"forbidden", "text/plain")
            return self._send(
                200,
                json.dumps(build_feed()).encode(),
                "application/json",
            )
        if path.startswith("/photos/"):
            # Photos are not secret-secret but keep the same gate for consistency.
            if not self._authorized():
                return self._send(403, b"forbidden", "text/plain")
            name = os.path.basename(urllib.parse.unquote(path[len("/photos/"):]))
            if not re.fullmatch(r"[\w.-]+\.jpe?g", name, re.IGNORECASE):
                return self._send(400, b"bad name", "text/plain")
            fpath = os.path.join(PHOTO_DIR, name)
            if not os.path.isfile(fpath):
                return self._send(404, b"not found", "text/plain")
            with open(fpath, "rb") as f:
                return self._send(200, f.read(), "image/jpeg", cache=True)
        if path == "/healthz":
            return self._send(200, b"ok", "text/plain")
        return self._send(404, b"not found", "text/plain")


def main():
    os.makedirs(PHOTO_DIR, exist_ok=True)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(
        f"\n  Hermes Glasses Dashboard\n"
        f"  http://localhost:{PORT}\n"
        f"  LAN:  http://{local_ip()}:{PORT}/?token=…\n"
        f"  history: {HISTORY_DIR}\n"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
