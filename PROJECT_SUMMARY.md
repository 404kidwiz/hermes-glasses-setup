# Setup repository status

Public handoff kit for the Hermes Glasses integration. Contains a sanitized app snapshot, archival integration patch, configuration templates, setup/model/operations/verification documentation, improvement roadmap and executable agent handoff prompt.

Reference acceptance: signed physical iPhone install/launch, phone voice on Wi-Fi and cellular confirmed; 71 Python bridge tests and 25 Swift configuration assertions passed. Physical glasses camera, microphone and speaker playback passed reference wearer tests on 2026-11-02. Fresh idle Wi-Fi-to-cellular retest automatically reconnected by wearer confirmation. A 10-minute screen-awake session passed with spoken replies at minutes 0, 5 and 10 without restarting. A reply after 2 minutes with the iPhone locked passed on 2026-11-03. Longer endurance and in-flight handover remain unverified. Includes sanitized diagnostics and conservative one-attempt idle recovery; uncertain requests are never replayed.

This is a source/setup kit, not a generalized installer. Signing team, bundle ID and renewal phone identity require personalization; service home/username paths are portable. Personal runtime configuration, credentials, provisioning material and logs are excluded.

Lens streaming repair (2026-11-03): failed-stream cleanup, one bounded video-error retry, low-resolution streaming and lifecycle ownership guards. Signed reference build and focused review passed; wearer confirmed a working 30-second glasses preview with phone cameras covered. Longer video endurance remains untested.

Optional conversation preview (2026-11-03): Show camera/Hide camera, live status, local display and owner-scoped cleanup. Reference wearer confirmed simultaneous glasses video/voice and Hide/Show without interrupting voice. Extended video endurance and rapid-toggle/background preview tests remain unverified.

## 2026-11-03 GUI improvements
Implemented connection sheet, inline recovery/information, visible Tools/Setup entries, optional Bluetooth status tones, and guided connection checks with allowlisted support export. Ten-skill GUI audit plus targeted simulator renders documented in docs/GUI-UX-AUDIT.md. Signed reference and unsigned public builds passed; short recovery tests, cue generation checks and independent review passed. Reference installation passed but launch was blocked by phone lock; wearer sound/UI check pending. Broader accessibility and endurance checks remain open.

## Lens recovery UI — 2026-11-03
Implemented terminal camera error panel with full error text, Retry camera, Back to conversation and voice-state-specific text. No indefinite spinner for terminal errors. Permission and automatic-reconnect states retain separate handling; retry preserves voice and saved captures. Cancelled camera-session startup now stops uncommitted SDK sessions. Signed build, terminal-state checks, source-derived SDK-double cancellation/failure/success regression and independent source recheck passed. Simulator fault injection rendered the panel; physical Lens/retry acceptance remains pending.

Status-sound follow-up: wearer confirmed manual test tone and automatic processing tone plus spoken reply. Recovery/error tones remain individually unverified.
