# Installation runbook

## 1. Understand the architecture

```text
Meta glasses ↔ paired iPhone
  microphone → Apple speech recognition → text
  camera → requested image
       ↓ authenticated WebSocket over Tailscale
Mac glasses bridge :8765
       ↓ authenticated local HTTP/SSE
Hermes gateway 127.0.0.1:8642 → configured model + tools/memory/delegation
       ↓ streamed text
 iPhone speech synthesis → selected audio output / glasses
```

USB is for pairing, signing and installation. It does not carry the normal voice connection. Tailscale uses the phone's Wi-Fi or cellular connection. Keep the Mac online and awake; a login LaunchAgent does not run before login or while the machine sleeps. Standard Ray-Ban audio/camera models do not acquire a display through software; display features require display-capable hardware.

## 2. Prerequisites and accounts

- Mac with compatible Xcode installed, required components completed, and an Apple Account signed in under Xcode → Settings → Apple Accounts.
- iPhone connected and trusted over USB, unlocked for installation, with Developer Mode enabled when required. Personal-team builds expire; signing must be maintained.
- Compatible Meta glasses paired through the Meta companion app. Meta glasses developer mode and iPhone Developer Mode are different settings.
- Tailscale installed on Mac and iPhone, signed into the intended tailnet with connectivity allowed between them.
- A working Hermes installation and your own authorized model/provider credentials. A ChatGPT or Claude subscription does not automatically imply API or SDK access for every integration.

Do not copy another person's accounts, tokens, signing team, bundle ID, phone identifier or Hermes history.

## 3. Obtain the included source

```bash
git clone https://github.com/404kidwiz/hermes-glasses-setup.git
cd hermes-glasses-setup
export SETUP_REPO="$PWD"
cd app
```

The sanitized `app/` directory already includes the tested integration fixes. Do **not** apply `patches/verified-integration.patch` again. That patch records changes against a local baseline commit which is not available from upstream GitHub. The source snapshot avoids that dependency. Open `app/HermesGlasses.xcodeproj` in Xcode.

## 4. Configure Hermes before the phone

Install Hermes using the [official installation guide](https://hermes-agent.nousresearch.com/docs/getting-started/installation). Configure one provider with `hermes setup`; validate a short text request and a harmless tool request from Hermes itself. Set up required tool backends separately: a working chat model does not prove web search or vision works.

Merge `templates/hermes-api.env.example` into `~/.hermes/.env`. Generate a unique API key, for example using Python `secrets.token_urlsafe(32)` in a private local setup process. Never use the example placeholder as a real key.

Start the gateway using the command supported by your installed version (the inspected version documents `hermes gateway`). It should listen on **127.0.0.1:8642**. See [official API-server instructions](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server/). Do not start a duplicate if a gateway service already owns this port.

Test authenticated `/v1/chat/completions` with `model: hermes-agent` and a short message, then a harmless tool task. Keep the API key out of shared terminal transcripts. For startup persistence, use your version's native Hermes gateway service installer/help, and verify it survives a logout/reboot separately. Do not assume installing the glasses bridge also installs the Hermes gateway service.

## 5. Configure and start the bridge

From the app repository:

```bash
python3 -m venv bridge/.venv
bridge/.venv/bin/python -m pip install -r "$SETUP_REPO/templates/bridge-requirements.txt"
cp "$SETUP_REPO/templates/bridge.env.example" bridge/.env
chmod 600 bridge/.env
```

Edit `bridge/.env` locally. Set a new bridge token and the gateway API key. They are distinct secrets. Keep `HERMES_BRIDGE_BRAIN=hermes`; direct-provider modes bypass the full agent. Empty model/provider overrides inherit the gateway/CLI default, not the model selected in a particular Desktop chat. Set `HERMES_BIN` if the default executable does not exist.

The runner sources this file as shell code: keep it trusted, use simple quoted values and never paste untrusted shell expressions into it. For a manual foreground trial:

```bash
bash scripts/run-bridge.sh
```

Before installing the bridge LaunchAgent, make these portability edits in the app checkout:

| File | Required personalization |
|---|---|
| `scripts/run-bridge.sh` | Already derives home/username dynamically; verify the Python and Hermes executable paths. |
| `scripts/install-bridge-service.sh` | Already derives home/username and creates LaunchAgents; inspect the generated plist on the new Mac. |
| `scripts/reinstall-iphone.sh` | Set DEVICE to your phone ID, BUNDLE_ID to your own app ID, and ensure derived-data/profile locations match your Xcode. `HERMES_IPHONE_UDID` overrides DEVICE for manual runs. |
| `scripts/install-reinstall-service.sh` | Persist your device ID in the generated LaunchAgent EnvironmentVariables if relying on an override; a shell export does not propagate to a later scheduled run. |
| Xcode Signing & Capabilities | Choose your team and unique bundle ID for all configurations. Match that ID in the renewal script and Meta project when applicable. |

These scripts have **not** been converted into a universal installer. Review the generated plist before loading it. Keep backups of edited scripts and record your substitutions privately.

After the manual bridge test passes, stop the foreground instance and run `bash scripts/install-bridge-service.sh`. Confirm one listener owns port 8765. The service starts at login and restarts on failure; it cannot wake a powered-off Mac.

## 6. Tailscale: one address for home and away

Use the [official Tailscale installation instructions](https://tailscale.com/kb/1017/install). Connect both devices to the intended tailnet. On the Mac, `tailscale status` and `tailscale ip -4` identify its actual private address. Do not reuse the address of the machine this recipe was developed on.

The app endpoint is:

```text
ws://<YOUR_MAC_TAILSCALE_IP>:8765/voice?token=<YOUR_BRIDGE_TOKEN>
```

The token-bearing URL is sensitive. Enter it only in your app/private setup tools. Tailscale encrypts traffic across its private network; this does not make the token safe to publish. The default bridge bind also accepts local-network traffic, so keep authentication enabled. No router port forwarding, public tunnel or Tailscale Funnel is required. Keep the Hermes API listener local-only.

Confirm the tailnet's existing access policy allows the phone to reach the Mac's bridge port. Do not weaken a firewall or grant access to an entire organization merely to bypass a failed test. A direct LAN endpoint can be a diagnostic fallback, but changing Wi-Fi networks breaks that address.

## 7. Build and sign the iPhone app

Open `HermesGlasses.xcodeproj` in Xcode. Complete required components and account sign-in. Select your connected iPhone, your signing team and unique bundle ID. Preserve the pinned `Package.resolved` on the first build.

Meta configuration has two distinct paths:

- Developer mode: base config uses `META_APP_ID = 0`, with `CLIENT_TOKEN` **empty**. Enable Meta glasses developer mode via the current companion-app instructions. Do not set the token to the literal `0`.
- Registered Meta project: copy `Config/Secrets.example.xcconfig` to the ignored `Config/Secrets.xcconfig`, use your own Meta application/token and register the matching bundle/team IDs.

Refer to [Meta iOS integration](https://wearables.developer.meta.com/docs/develop/dat/build-integration-ios/) and the [official SDK repository](https://github.com/facebook/meta-wearables-dat-ios). Current SDK documentation may describe APIs newer than the pinned 0.8.0; upgrade only as a separate tested change.

Build and Run to the unlocked iPhone. If it fails, read the exact Xcode error. For terminal builds use the real device destination, `-allowProvisioningUpdates` and `-allowProvisioningDeviceRegistration`; a generic iOS destination did not register a previously unknown phone in the observed failure.

If launch is blocked after signing, on **the iPhone** inspect Settings → General → VPN & Device Management → Developer App → your account → Trust. The user must complete trust and other device security prompts. [Apple developer trust guidance](https://help.apple.com/xcode/mac/current/en.lproj/dev96a12fb84.html). Never disable signature checks or delete app data as the first repair.

## 8. Configure the app

1. Select **Bridge (server)** under assistant settings and enter the private endpoint.
2. Enable **on-device speech** in voice settings. The verified app supports it; it avoids server synthesis and audio-transfer delay.
3. Allow the required microphone, speech-recognition and Local Network permissions. Allow camera permissions only as needed.
4. Connect glasses through the app and companion registration flow; camera permission is separate from pairing. Select the intended microphone/audio route.
5. Begin with phone mode and a short request; then test the actual glasses camera and audio with the acceptance matrix.

The patched app can also persist `-hermes_endpoint <private-url>` and `-use_device_tts YES` when launched with `devicectl`. It clears those transient overrides so later Settings edits work. Do not print the URL in shared logs or command transcripts. Manual Settings entry is simpler for most users.

## 9. Enable renewal only after the first successful install

With the renewal scripts personalized, run `bash scripts/reinstall-iphone.sh --status`, then an initial `--force` when needed. Install the scheduled helper with `bash scripts/install-reinstall-service.sh`. It checks every two hours and renews near expiry; it cannot complete an install when the phone is locked/unreachable or Apple authentication is broken.

Verify an actual install and recorded expiry. A scheduler's successful exit can mean it skipped a locked phone, not that renewal succeeded. Inspect `.runtime/reinstall.log` and build/install logs privately. An app reinstall may interrupt an active turn.

Finish [VERIFICATION](VERIFICATION.md) before handing the system to an end user.
