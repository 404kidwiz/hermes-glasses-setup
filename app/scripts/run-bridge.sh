#!/usr/bin/env bash
# Hermes Glasses Mac bridge. Phone talks to ws://<lan-ip>:8765/voice
# This is the pivot app, not VisionClaw Agent Bridge (:8788).
set -euo pipefail
echo "[bridge] script $(date '+%Y-%m-%d %H:%M:%S') pid=$$" >&2
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BRIDGE="$ROOT/bridge"
cd "$BRIDGE"

if [[ ! -x .venv/bin/python ]]; then
  echo "Missing $BRIDGE/.venv. From this directory: uv venv .venv && uv pip install --python .venv/bin/python websockets edge-tts"
  exit 1
fi

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

export PYTHONUNBUFFERED=1
export PATH="${HOME}/.local/bin:/opt/homebrew/bin:/usr/bin:/bin:${PATH}"
export LANG="${LANG:-en_US.UTF-8}"
export USER="${USER:-$(id -un)}"
export LOGNAME="${LOGNAME:-$(id -un)}"
export TMPDIR="${TMPDIR:-/tmp}"
echo "[bridge] starting $(date '+%Y-%m-%d %H:%M:%S') pid=$$"
exec .venv/bin/python -u hermes_bridge.py
