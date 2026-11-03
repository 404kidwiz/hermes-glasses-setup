# Coding-agent handoff prompt

Give the following task to an agent with terminal access to the new user's Mac. This is an installation task, not an instruction to merely produce another prompt.

---

Set up Hermes Glasses for this user using this repository's README, VERSIONS, SETUP, MODELS, VERIFICATION and OPERATIONS documents. Implement and verify the setup; keep a checklist of completed steps and remaining blockers.

## Required outcome

A separately owned Hermes gateway and authenticated glasses bridge; signed iPhone app using Bridge mode and on-device speech; private Tailscale connectivity; verified short replies on Wi-Fi and cellular; documented hardware acceptance, renewal and recovery. Never claim a physical-device check passed without evidence.

## Inspect before asking

Read the host/repository instructions and relevant skills. Inventory Xcode, iPhone connectivity/lock state, Hermes version/provider capability, existing gateway/bridge listeners and Tailscale state. Inspect Git status and preserve unrelated edits. Use the included app snapshot and VERSIONS rather than assuming upstream latest has these fixes.

Ask only for genuinely missing choices/access: which physical iPhone, the user's Apple/Meta accounts and enrollment path, desired provider and budget, intended Tailscale account, and whether required devices are available. Never ask for passwords or tokens in chat. Have the user complete account sign-in, trust, security, camera/microphone and other device permission prompts themselves.

## Work sequence

1. Use the included `app/` source, which already contains the fixes. Do not apply the archival patch again. Record the setup repository commit and pinned SDK version.
2. Establish a working Hermes model and harmless tool request. Enable the authenticated local API server and test it independently.
3. Create unique secrets locally, configure the bridge with inherited Hermes routing, install dependencies, and verify authenticated WebSocket connectivity. Do not change the user's global primary model solely to accelerate voice.
4. Personalize all hardcoded usernames, local paths, phone IDs, bundle IDs and signing teams. Keep those personal settings private. Check generated LaunchAgents before loading them. Do not assume a shell export reaches launchd.
5. Build, sign, install and launch on the unlocked phone; preserve app data. Use real-device provisioning registration when needed. Keep the pinned DAT SDK for the first reproduction.
6. Configure Bridge mode, on-device speech and the private Tailscale endpoint. Validate home Wi-Fi and cellular with the same short prompt, then perform physical glasses and long-turn tests with the wearer.
7. Enable the personalized renewal helper only after one successful install. Verify its actual result and expiry. Document gateway/bridge startup and what happens when the Mac sleeps or the phone is unreachable.

## Boundaries

- Do not copy the reference operator's credentials, memory, conversation logs, device identifiers or personal config. Never print token-bearing URLs.
- Do not disable authentication, certificate checks, device trust, firewalls or security policies; do not expose a public port or configure Funnel as a convenience workaround.
- Do not remove/uninstall the app or erase data without explicit authorization and a recovery plan.
- Do not send messages, invite collaborators, create paid subscriptions, accept new legal terms or publish user information without the user's authority.
- Do not guess provider/model IDs, assume subscription access equals API access, or label a temporarily rate-limited provider permanently broken.
- New feature development and SDK upgrades are separate from reproducing the baseline.

## Failure handling

Read the actual error and identify the failing layer. Correct the cause and rerun the smallest relevant check. When user sign-in, trust, unlocking or hardware interaction is required, finish independent work, state the exact blocker and ask for one concrete action. Do not bypass the control or report the task complete.

## Deliverables

Provide a private, sanitized installation report: source versions, configured service names, enabled capabilities, tests with evidence, signing expiry, startup/recovery commands, unresolved issues and one next action if blocked. Run the relevant existing tests and signed build. Mark automated, live API, phone and physical-glasses evidence separately. Confirm nothing secret or user-specific is staged before any authorized Git push.

---

## Acceptance checklist for the receiving colleague

- [ ] Own accounts and unique secrets; no inherited personal data.
- [ ] Correct provider/tool route and sensible cost controls.
- [ ] iPhone launch + spoken reply on Wi-Fi and cellular.
- [ ] Physical glasses camera/audio and longer/background behavior recorded honestly.
- [ ] Renewal/recovery procedure demonstrated and credentials excluded from shared artifacts.
