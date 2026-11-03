#!/usr/bin/env bash
# Keep the Hermes Glasses bridge alive across overnight sleep / Cursor restarts.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
RUNNER="$ROOT/scripts/run-bridge.sh"
LABEL="com.visionclaw.hermes-glasses-bridge"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DOMAIN="gui/$(id -u)"
ACTION="${1:-install}"

chmod +x "$RUNNER"
mkdir -p "$ROOT/.runtime" "$HOME/Library/LaunchAgents"

if [[ "$ACTION" == "uninstall" ]]; then
  launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
  rm -f "$PLIST"
  echo "Hermes Glasses bridge service removed."
  exit 0
fi

python3 - "$PLIST" "$RUNNER" "$ROOT" <<'PY'
import plistlib
import getpass
import sys
from pathlib import Path

path, runner, root = sys.argv[1:]
payload = {
    "Label": "com.visionclaw.hermes-glasses-bridge",
    "ProgramArguments": ["/bin/bash", runner],
    "WorkingDirectory": str(Path(root) / "bridge"),
    "RunAtLoad": True,
    "KeepAlive": {"SuccessfulExit": False},
    "ThrottleInterval": 5,
    "ProcessType": "Interactive",
    "EnvironmentVariables": {
        "HOME": str(Path.home()),
        "USER": getpass.getuser(),
        "LOGNAME": getpass.getuser(),
        "LANG": "en_US.UTF-8",
        "TMPDIR": "/tmp",
        "PATH": f"/usr/bin:/bin:/opt/homebrew/bin:/usr/local/bin:{Path.home()}/.local/bin",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONFAULTHANDLER": "1",
    },
    "StandardInPath": "/dev/null",
    "StandardOutPath": f"{root}/.runtime/bridge.log",
    "StandardErrorPath": f"{root}/.runtime/bridge.error.log",
}
with open(path, "wb") as output:
    plistlib.dump(payload, output)
PY

launchctl bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
launchctl bootstrap "$DOMAIN" "$PLIST"
echo "Hermes Glasses bridge starts at login and restarts if it dies."
echo "Phone: ws://$(ipconfig getifaddr en0 2>/dev/null || echo 192.168.1.68):8765/voice"
echo "Logs: $ROOT/.runtime/bridge.log"
