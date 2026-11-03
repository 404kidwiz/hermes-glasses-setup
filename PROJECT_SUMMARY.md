# Setup repository status

Public handoff kit for the Hermes Glasses integration. Contains a sanitized app snapshot, archival integration patch, configuration templates, setup/model/operations/verification documentation, improvement roadmap and executable agent handoff prompt.

Reference acceptance: signed physical iPhone install/launch, phone voice on Wi-Fi and cellular confirmed; 71 Python bridge tests and 25 Swift configuration assertions passed. Physical glasses camera, microphone and speaker playback passed reference wearer tests on 2026-11-02. Fresh idle Wi-Fi-to-cellular retest automatically reconnected by wearer confirmation. A 10-minute screen-awake session passed with spoken replies at minutes 0, 5 and 10 without restarting. A reply after 2 minutes with the iPhone locked passed on 2026-11-03. Longer endurance and in-flight handover remain unverified. Includes sanitized diagnostics and conservative one-attempt idle recovery; uncertain requests are never replayed.

This is a source/setup kit, not a generalized installer. Signing team, bundle ID and renewal phone identity require personalization; service home/username paths are portable. Personal runtime configuration, credentials, provisioning material and logs are excluded.
