# Recorded baseline — 2026-11-02 (America/New_York)

| Component | Recorded version/revision |
|---|---|
| Glasses application upstream | https://github.com/prasanthsasikumar/hermes-glasses |
| Local baseline commit for archival patch | `15556bf0e0cca5d65a8f1073b6cfea60cf8bd2b3` |
| Hermes Agent source inspected | `f0d94882e89ab8d4098b5bb2f166adfb9ee0a0ab` |
| Hermes Agent upstream | https://github.com/NousResearch/hermes-agent |
| App version | 0.4 |
| Meta DAT iOS lockfile | 0.8.0, revision `2e30f1253ab76ee3c448a29dce39114ab09763c3` |
| Xcode used for signed build | 27.1 |
| Physical test phone | iPhone 15 Pro Max, iOS 27.2 |
| Project minimum deployment target | iOS 17.0; this is not proof of acceptance on every iOS version |
| Bridge Python | 3.13.12 |
| websockets / aiohttp / edge-tts | 17.0.1 / 3.14.3 / 7.2.8 |

Use the upstream `Package.resolved`; do not silently upgrade DAT while reproducing this baseline. The source snapshot and patch are reproducible inputs, not a guarantee that third-party services or historical package versions remain downloadable. The local baseline commit is not available from upstream GitHub. Use the included sanitized `app/` source; the archival patch is for review, not installation. Personal signing team/device identifiers are removed and service username/path handling is portable in this snapshot.

Hermes itself may have local configuration/extensions. This repository does not copy that personal installation. Establish and test a working standard Hermes gateway first, then configure optional providers and council routing supported by that installation.
