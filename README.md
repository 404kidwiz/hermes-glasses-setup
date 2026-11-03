# Hermes Glasses: repeatable setup and agent handoff

Build your own voice-and-camera interface to Hermes using an iPhone, compatible Meta glasses, a Mac, and Tailscale. This repository contains setup instructions and a sanitized, patched app source snapshot in `app/`. It is **not** a one-click installer.

Start with [SETUP](docs/SETUP.md). To delegate installation, give your coding agent [AGENT_HANDOFF](AGENT_HANDOFF.md) and this repository. Allow approximately 60–120 minutes for a fresh setup; account enrollment and Apple/Meta permissions can add time.

## What this setup provides

- Full Hermes gateway access rather than direct-provider chat: configured tools, model routing, memory and delegation, subject to the gateway's actual configuration.
- A single private Tailscale endpoint for home Wi-Fi and cellular access.
- Streamed text spoken on the iPhone to avoid server speech synthesis delays.
- Signed iPhone installation and documented renewal/troubleshooting procedures.
- Protection against automatic request replay after observed tool activity; this is not a complete exactly-once execution guarantee.

## Read in this order

1. [Setup and architecture](docs/SETUP.md)
2. [Model configuration and cost policy](docs/MODELS.md)
3. [Acceptance tests and evidence](docs/VERIFICATION.md)
4. [Operations, recovery and privacy](docs/OPERATIONS.md)
5. [Recommended enhancements](docs/ROADMAP.md)

## Verified baseline

A physical iPhone successfully launched the app and answered over Wi-Fi and cellular through Tailscale. The user reported quick responses after on-device speech was enabled. A signed build, 71 bridge tests and 25 endpoint/preferences assertions passed. Physical Ray-Ban camera capture, glasses microphone/speaker routing, long background sessions and every specialist agent have **not** been fully revalidated. See the acceptance matrix; do not treat phone-mode success as glasses-hardware acceptance.

The recipe includes the app source and pins its SDK; model availability, provider pricing, Apple signing requirements and Meta enrollment can change. Follow current official instructions when they differ from the recorded baseline.

## Contents and boundaries

`app/` is the buildable source snapshot; no unavailable upstream commit is required. `patches/verified-integration.patch` is an archival review of the integration changes against the local baseline recorded in `VERSIONS.md`. Do not apply it again to `app/`. No provider keys, bridge tokens, provisioning profiles, user memories, device IDs or private logs are included. The upstream patch may refer to example model names and legacy project identifiers in unchanged context; replace identity-specific build settings before installing on another person's device.

No user invitations or collaborator access are granted automatically. The repository is intended for private collaboration. Do not upload a real `.env`, app container, phone preferences or Hermes home directory.
