#!/bin/bash
# Install/refresh the LaunchAgent that keeps the iPhone app from expiring
# (runs scripts/reinstall-iphone.sh every 2 h). Remove with:
#   launchctl bootout gui/$(id -u)/com.visionclaw.hermes-glasses-reinstall
#   rm ~/Library/LaunchAgents/com.visionclaw.hermes-glasses-reinstall.plist
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LABEL="com.visionclaw.hermes-glasses-reinstall"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
mkdir -p "$ROOT/.runtime"

cat >"$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>Label</key>
	<string>$LABEL</string>
	<key>ProgramArguments</key>
	<array>
		<string>/bin/bash</string>
		<string>$ROOT/scripts/reinstall-iphone.sh</string>
	</array>
	<key>EnvironmentVariables</key>
	<dict>
		<key>PATH</key>
		<string>/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin:/usr/local/bin</string>
	</dict>
	<key>StartInterval</key>
	<integer>7200</integer>
	<key>RunAtLoad</key>
	<true/>
	<key>ProcessType</key>
	<string>Background</string>
	<key>StandardOutPath</key>
	<string>$ROOT/.runtime/reinstall.log</string>
	<key>StandardErrorPath</key>
	<string>$ROOT/.runtime/reinstall.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "installed $LABEL (every 2 h); log: $ROOT/.runtime/reinstall.log"
