#!/bin/bash
# Keep Hermes Glasses installed on the iPhone. A free Apple team signs apps
# with 7-day profiles; once one lapses the app stops opening. Run by the
# LaunchAgent com.visionclaw.hermes-glasses-reinstall every 2 h (see
# install-reinstall-service.sh). Each run exits fast unless the installed
# profile is within RENEW_DAYS of expiring; then it forces Xcode to mint a
# fresh profile, builds, and installs - if the phone is reachable and
# unlocked. Missed runs just retry 2 h later.
#
#   scripts/reinstall-iphone.sh            # renew if due
#   scripts/reinstall-iphone.sh --force    # renew now
#   scripts/reinstall-iphone.sh --status   # print expiry, change nothing
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DEVICE="${HERMES_IPHONE_UDID:-YOUR_IPHONE_UDID}"   # iPhone 15 Pro Max
BUNDLE_ID="com.example.HermesGlasses"
DERIVED="${HERMES_REINSTALL_DERIVED:-$HOME/Library/Caches/hermes-glasses-reinstall}"
PROFILES="$HOME/Library/Developer/Xcode/UserData/Provisioning Profiles"
STATE="$ROOT/.runtime/reinstall-expiry"   # epoch seconds of installed profile expiry
RENEW_DAYS="${HERMES_RENEW_DAYS:-3}"
APP="$DERIVED/Build/Products/Debug-iphoneos/Hermes Glasses.app"

log() { echo "[reinstall] $(date '+%F %T') $*"; }
notify() {  # Mac banner so a failing renewal isn't silent; at most one per 6 h
    local stamp="$ROOT/.runtime/reinstall-notified" last
    last=$(cat "$stamp" 2>/dev/null); [[ "$last" =~ ^[0-9]+$ ]] || last=0
    (( $(date +%s) - last < 21600 )) && return 0
    date +%s >"$stamp"
    /usr/bin/osascript -e "display notification \"$1\" with title \"Hermes Glasses\"" >/dev/null 2>&1 || true
}
with_timeout() {  # with_timeout <seconds> <cmd...>; macOS has no timeout(1)
    # Own process group, killed whole on timeout: xcodebuild's build service
    # and compilers would otherwise outlive it and hold the DerivedData lock.
    /usr/bin/perl -e '
        my $t = shift;
        my $pid = fork // die "fork: $!";
        if (!$pid) { setpgrp(0, 0); exec @ARGV or die "exec: $!" }
        $SIG{ALRM} = sub { kill "TERM", -$pid; sleep 5; kill "KILL", -$pid; exit 142 };
        alarm $t;
        waitpid $pid, 0;
        exit($? & 127 ? 128 + ($? & 127) : $? >> 8);
    ' "$@"
}
profile_info() {  # prints "<app-id> <expiry-epoch> <device-udid>..."
    security cms -D -i "$1" 2>/dev/null | /usr/bin/python3 -c '
import datetime, plistlib, sys
p = plistlib.loads(sys.stdin.buffer.read())
exp = p["ExpirationDate"].replace(tzinfo=datetime.timezone.utc)  # naive UTC
print(p["Entitlements"]["application-identifier"], int(exp.timestamp()),
      *p.get("ProvisionedDevices", []))' 2>/dev/null
}

mkdir -p "$ROOT/.runtime" "$DERIVED"
now=$(date +%s)
expires=$(cat "$STATE" 2>/dev/null)
[[ "$expires" =~ ^[0-9]+$ ]] || expires=0   # missing/corrupt state = unknown, renew
last_day=$(( expires > 0 && expires - now < 86400 ))
days_left=$(( (expires - now) / 86400 ))

if [[ "${1:-}" == "--status" ]]; then
    if (( expires > 0 )); then
        log "installed profile expires $(date -r "$expires" '+%F %T') (${days_left}d left)"
    else
        log "no install recorded yet"
    fi
    exit 0
fi

if [[ "${1:-}" != "--force" ]] && (( expires - now > RENEW_DAYS * 86400 )); then
    exit 0  # not due; stay quiet so the log only shows real work
fi

# Phone must be paired, reachable (USB or Wi-Fi) and in Developer Mode.
details="$(xcrun devicectl device info details --device "$DEVICE" 2>&1)"
if ! grep -q 'Developer Mode Status: Enabled' <<<"$details"; then
    log "phone $DEVICE not reachable - retrying next run (${days_left}d left)"
    (( last_day )) && \
        notify "App expires within a day and the iPhone isn't reachable. Plug it into the Mac and unlock it."
    exit 0
fi
# Installing needs an unlocked phone; don't build (or mint a profile) for a
# locked one - that would repeat every 2 h all night.
if xcrun devicectl device info lockState --device "$DEVICE" 2>&1 | grep -q 'passcodeRequired: true'; then
    log "phone locked - retrying next run (${days_left}d left)"
    (( last_day )) && \
        notify "App expires within a day. Unlock the iPhone near the Mac so it can reinstall."
    exit 0
fi
# Known ceiling: installing kills the app if it's open, so a turn in progress
# at that moment is cut off (once a week at most). Deferring while "running"
# doesn't work - iOS lists suspended apps as running too - and waiting would
# only eat the renewal margin.

# Force a fresh 7-day profile: Xcode reuses a cached one until it lapses, so
# a rebuild on day 5 would otherwise ship the same expiry. Only profiles
# that are themselves near expiry are replaced (an earlier run may already
# have minted a fresh one and then failed to install); they're moved aside,
# restored if the build fails, never deleted.
aside="$DERIVED/old-profiles/$(date +%Y%m%d-%H%M%S)"
mkdir -p "$aside"
for f in "$PROFILES"/*.mobileprovision; do
    [[ -f "$f" ]] || continue
    read -r app_id profile_expires _ <<<"$(profile_info "$f")"
    [[ "$app_id" == *".$BUNDLE_ID" ]] || continue
    if [[ "${1:-}" == "--force" ]] || (( profile_expires - now <= RENEW_DAYS * 86400 )); then
        mv "$f" "$aside/"
    fi
done
rmdir "$aside" 2>/dev/null  # nothing was near expiry

log "building (profiles moved aside: $(ls "$aside" 2>/dev/null | wc -l | tr -d ' '))"
# CCC_OVERRIDE_OPTIONS: Xcode's clang SDK probe can hang in launchd/CLI
# contexts; answering it with --version skips the stall.
# 30 min cap: a hung build (e.g. a keychain prompt nobody sees) must not
# wedge every later run.
if ! CCC_OVERRIDE_OPTIONS='s/-dM/--version/' with_timeout 1800 xcodebuild \
        -project "$ROOT/HermesGlasses.xcodeproj" -scheme HermesGlasses \
        -destination "id=$DEVICE" -derivedDataPath "$DERIVED" \
        -allowProvisioningUpdates -allowProvisioningDeviceRegistration -quiet build >"$ROOT/.runtime/reinstall-build.log" 2>&1; then
    mv "$aside"/*.mobileprovision "$PROFILES/" 2>/dev/null
    log "BUILD FAILED - see .runtime/reinstall-build.log"
    grep -m5 'error:' "$ROOT/.runtime/reinstall-build.log"
    notify "Reinstall build failed. See hermes-glasses/.runtime/reinstall-build.log"
    exit 1
fi

info="$(profile_info "$APP/embedded.mobileprovision")"
new_expires=$(awk '{print $2}' <<<"$info")
if ! [[ "$new_expires" =~ ^[0-9]+$ ]] || (( new_expires <= expires )); then
    # Xcode handed back the same (or no) profile: reinstalling would change
    # nothing and repeat every 2 h.
    log "profile did not renew (built expiry: ${new_expires:-none}) - not installing"
    notify "Reinstall: Xcode didn't issue a new profile. Open Xcode > Settings > Accounts and check the Apple ID."
    exit 1
fi
if [[ " $info " != *" $DEVICE "* ]]; then
    log "built profile does not include $DEVICE - register it once with an Xcode run to that phone"
    notify "Reinstall: the new profile doesn't cover the iPhone. Run once from Xcode to register it."
    exit 1
fi

if ! with_timeout 600 xcrun devicectl device install app --device "$DEVICE" "$APP" \
        >"$ROOT/.runtime/reinstall-install.log" 2>&1; then
    log "install failed (phone locked?) - retrying next run"
    grep -m3 -i -E 'error|reason' "$ROOT/.runtime/reinstall-install.log"
    (( last_day )) && notify "Reinstall failed and the app expires within a day. Unlock the iPhone near the Mac."
    exit 1
fi

echo "$new_expires" >"$STATE"
log "installed; profile valid until $(date -r "$new_expires" '+%F %T')"
