# Acceptance and reproducibility

Record date, versions, network, prompt, observed result and actual execution route. Use synthetic text/images; redact tokens, personal location and conversation content before sharing evidence.

## Automated checks

From the included `app/` directory:

```bash
bridge/.venv/bin/python -m unittest discover -s bridge -p 'test_hermes_bridge.py'
swiftc HermesGlasses/Services/BridgeEndpointConfig.swift tests/bridge-endpoint/main.swift -o /tmp/hermes-endpoint-tests
/tmp/hermes-endpoint-tests -hermes_endpoint 'ws://mac.local:8765/voice?token=t1' -endpoint_presets '{Home="ws://mac.local:8765/voice?token=t1";}'
bash -n scripts/reinstall-iphone.sh
git diff --check
```

The test token above is a dummy used only by local preferences tests. Expected baseline: 71 Python tests and 25 Swift assertions. Also build the signed iOS target with your real device/team settings; a unit test cannot prove signing or launch works.

The upstream `scripts/smoke-bridge.py` makes real paid model/tool calls and asks for server audio. Its `--only=plain` tests a short reply; `--only=search,visual` tests search and a synthetic image. It reads the bridge token locally. The image helper requires a macOS test wallpaper; replace with a nonpersonal fixture if absent. These are bridge-protocol checks, not physical glasses capture or on-device speech tests. Do not run them against an active user conversation: the reference bridge shares its conversation state.

## Acceptance matrix

| Check | Procedure | Pass condition | Reference status |
|---|---|---|---|
| Phone signing | Install then launch from icon | No trust/signature rejection, app stays running | Passed |
| Bridge authentication | Connect with valid token, reject invalid token | Valid welcome; invalid client denied | Valid live path passed; independently test rejection on new setup |
| Phone voice | Ask “Reply with hello” | Text and audible answer | Passed by user |
| Wi-Fi | Same test on home Wi-Fi | Completed answer | Passed by user |
| Cellular | Wi-Fi off, Tailscale on | Completed answer | Passed by user |
| Tool request | Harmless current-information lookup | Tool activity and completed reply | Bridge smoke passed; factual answer accuracy separately assessed |
| Synthetic vision | Send known nonpersonal image | Image path exercised, relevant answer | Bridge smoke passed |
| Actual glasses camera | Ask about a known object while wearing glasses | Actual glasses capture and correct description | Passed by reference wearer on 2026-11-02 with iPhone cameras covered |
| Glasses audio | Phone away, selected glasses microphone/speakers | Speech captured and reply heard through glasses | Passed by reference wearer on 2026-11-02 with iPhone about 10 feet away |
| Long tool turn | A task taking more than 10s | No premature disconnection, completion | Timeout mitigation installed; systematic acceptance pending |
| Wi-Fi/cellular handover | Switch networks between turns, then during a harmless turn | Document recovery/no duplicate action | Initial reference test required Start; fresh idle retest on 2026-11-02 automatically reconnected by wearer confirmation. Spoken reply after recovery and in-flight handover remain unverified |
| Sustained foreground session | Keep screen awake; ask at minutes 0, 5 and 10 | All replies through glasses without Start/restart | Passed by reference wearer on 2026-11-02; does not establish locked-screen or longer endurance |
| Locked/background phone | Test intended real usage with screen locked | Record actual behavior; do not assume indefinite iOS background execution | Passed by reference wearer on 2026-11-03 after 2 minutes locked; longer background use untested |
| Restart recovery | Restart bridge/gateway and reboot Mac after saving work | Services return after login; phone reconnects | Pending for clean colleague install |
| Renewal | Force one renewal with unlocked phone | New profile installed, expiry recorded, app launches | Passed on reference device |
| Council | Validate advisors then real fan-out | Both advisors and synthesis evidenced | Separate Hermes test passed; glasses-specific test pending |

## Latency: avoid misleading comparisons

Compare identical prompts on Wi-Fi and cellular, with similar session history, model, speech mode and cache state. Alternate networks, repeat at least five times, and record median/range rather than one best result. Separate speech-recognition pause, network handshake, first text, first audible word, completion and tool time.

Reference observations: short VPN response first token 4.43s; a different tool-heavy request took 45.52s and disconnected. These do not isolate network speed. A short server-speech preparation test took 1.82s after text existed. On-device speech bypasses that server work, but its audible latency was not instrumented; the user reported quick responses on both networks.

## Handoff acceptance record

Create a private record with: operator, date, app/Hermes/SDK versions, sanitized configuration, checks passed/failed, unresolved issues and recovery owner. Never label the complete system “verified” while hardware checks remain pending. Do not store credentials or precise location in the public issue tracker.

## Public snapshot publication checks

The included sanitized snapshot passed a clean unsigned generic-iOS build (signing is intentionally left to the receiving user), 71 bridge tests and 25 Swift endpoint/preferences assertions. The paired map-token test fixture was made explicitly synthetic and its tests rerun. Shell syntax, documentation relative links, archival patch application against the original local baseline, known-private-value scanning and staged Gitleaks scanning passed. No provider authentication or live physical-device acceptance was performed with a colleague's accounts. The signed installed reference app was tested separately before sanitization.

## Recovery update acceptance

The reference installed app passed wearer-confirmed glasses microphone/speaker and camera tests, a fresh idle Wi-Fi-to-cellular automatic reconnect, a 10-minute screen-awake session with replies at minutes 0/5/10, and a reply after 2 minutes with the phone locked. Initial handover required manual Start; the fresh-session retest recovered automatically. These are bounded user-reported checks, not an all-day endurance guarantee.

Connection diagnostics show a sanitized endpoint, transport event, pending-request status, first-text timing, and the reason automatic recovery was skipped. Recovery makes one attempt after a two-second delay only when listening, no request is pending, and recording is inactive. It never resends an interrupted query. Start resets the retry allowance. The reconnecting notice is informational.

Run `bash tests/bridge-recovery/run.sh` from `app/` for controlled transport checks, including a 65-second reply, invalid welcome, cancellation before a delayed welcome, redaction, and single delivery on interruption. `--short` skips the long response case. The fixture uses local port 19876 and requires the bridge virtual environment. This does not simulate physical Bluetooth or iOS background suspension.

## Lens repair — 2026-11-03

A reported Lens `videoStreamingError` exposed an asynchronous failure path that left the failed stream allocated. The repair releases it, clears the stale preview, retries that error once, and uses low-resolution live streaming. Generation checks protect against stale callbacks and late startup cleanup after Stop or replacement. Permission and thermal errors are not automatically retried.

Signed reference-device build/install/launch and focused independent static review passed. With iPhone cameras covered, the wearer confirmed the glasses preview followed their view for 30 seconds without the error. This validates the repaired path in that test; it does not identify the underlying SDK/hardware cause or establish long-duration video reliability. Fault-injected recovery and Stop-during-start hardware tests remain unverified.

## Conversation preview acceptance — 2026-11-03

The optional conversation preview passed the signed reference-device build and focused independent static ownership review. The wearer confirmed simultaneous live glasses video and a spoken reply with iPhone cameras covered, then confirmed voice still worked after Hide camera and the preview returned to Live after Show camera. Cleanup uses a stream owner UUID so rejected/obsolete preview work cannot stop a different feature's stream. A starting preview reserves the camera against competing still capture until frames are available.

The public unsigned build and secret scan are publication checks; they do not substitute for colleague-device testing. Rapid repeated toggles, background/foreground preview transitions, and extended simultaneous video/voice endurance remain untested on hardware. Existing voice-only locked-screen acceptance does not prove background camera operation; the preview deliberately hides when the app becomes inactive.

## 2026-11-03 GUI update
Signed reference-device and simulator builds passed; updated reference app installed. Phone locked before automatic launch, so physical status-sound acceptance is pending. Short transport regression and isolated cue PCM checks passed; independent source recheck cleared scoped blockers. Targeted simulator renders cover home, setup, Tools and connection sheet in light/dark/enlarged text. This does not establish full VoiceOver, all-screen text scaling, or all-day endurance. See [GUI audit](GUI-UX-AUDIT.md).

## Lens recovery UI — 2026-11-03
Implemented terminal camera error panel with full error text, Retry camera, Back to conversation and voice-state-specific text. No indefinite spinner for terminal errors. Permission and automatic-reconnect states retain separate handling; retry preserves voice and saved captures. Cancelled camera-session startup now stops uncommitted SDK sessions. Signed build, terminal-state checks, source-derived SDK-double cancellation/failure/success regression and independent source recheck passed. Simulator fault injection rendered the panel; physical Lens/retry acceptance remains pending.

Status-sound follow-up: wearer confirmed manual test tone and automatic processing tone plus spoken reply. Recovery/error tones remain individually unverified.

- Physical acceptance follow-up: wearer confirmed Lens preview works and voice replies still work after closing Lens with Done. Normal preview/voice continuity passes by user report. No camera failure occurred in this check; Retry camera after a real failure remains unverified.

## Conversation GUI polish — 2026-11-03

Implemented compact header and scrollable conversation camera; explicit microphone menu and independent Stop speaking action; consistent Tools/Setup/Lens shortcuts; scalable semantic text, adaptive accessibility layouts and larger shared touch targets; confirmation before People/Object Log deletion, with Cancel preserving records and deleted People entries protected from dismissal autosave.

Simulator and signed-device builds passed during integration; EncounterStore and LensSessionStore suites passed. Independent source review found no blockers. Normal light and accessibility-large dark conversation fixtures were inspected; these use synthetic messages, not live audio. Large text revealed cramped controls, corrected with a scrollable shortcut row, vertically arranged speech controls and a scrollable screen. Full VoiceOver, largest-size interaction and physical acceptance of the new controls remain open.

Final GUI candidate: simulator, signed reference device and unsigned public builds passed; physical install/launch succeeded. Gitleaks directory scan passed. Tools sheet and accessibility-large conversation render inspected. No live record deletion was performed. Cancel/confirmation interaction and VoiceOver remain pending. Wearer audio-control acceptance passed: Stop speaking stopped playback while preserving the connection.

Physical GUI acceptance follow-up (2026-11-03): wearer selected “Glasses Mic (call screen),” requested “Count to twenty,” and confirmed Stop speaking stopped playback while the session stayed connected. This verifies the tested control flow by user report; it does not establish full accessibility or long-session endurance.
