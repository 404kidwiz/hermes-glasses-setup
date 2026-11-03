# Daily operations, recovery and data boundaries

## Everyday use

Keep Tailscale connected on phone and Mac. Keep the Mac awake, powered and online. Use Bridge mode and on-device speech. Start a new session after switching models; the bridge keeps a conversation/session record and may otherwise resume earlier context. Unplug USB after installation; it is not needed for network operation.

Use the app's existing Settings to choose speech mode or endpoints. On-device speech changes the voice and bypasses the failed Edge speech route. Free models, tool-heavy tasks and council fan-out are not guaranteed fast.

## Optional camera preview during conversation

Start Listening with the glasses selected, then tap **Show camera** on the conversation screen. The panel displays **Connecting**, **Live**, or **Reconnecting**. Tap **Hide camera** to release the preview while continuing voice conversation. It starts hidden; there is no automatic camera preview at app launch.

The preview displays locally; it does not continuously send video to Hermes. Asking a visual question still shares an image through the existing visual-query path. Opening Lens, starting recording, switching microphones, ending the session or backgrounding the app hides the preview. Show it again explicitly when needed. The panel is available for active glasses sessions, not phone-camera mode or recording.

## Troubleshooting

| Symptom | Inspect | Recovery |
|---|---|---|
| App will not open | Signing expiry, Developer Mode, trust | Renew/reinstall, then complete iPhone developer trust. Preserve data. |
| Xcode “No Accounts” | Xcode Apple Accounts | User signs in; rerun provisioning. |
| No devices to generate profile | Build destination and device registration | Target actual connected phone and allow provisioning registration. |
| Renewal says phone locked | Device lock state | Unlock and keep screen awake for installation. |
| Local connection fails | Saved endpoint, token, Local Network permission, port 8765 | Correct address/token; verify listener and phone permission. |
| Away connection fails | Tailscale on both devices, Mac awake, policy, address | Restore intended VPN connection; do not expose port publicly as a shortcut. |
| Connects but no response | Gateway :8642, API key, model auth, quota | Test gateway independently; repair the failing layer. |
| Wrong model | Bridge env override, gateway profile, resumed session | Clear unwanted overrides; reload gateway; new session. |
| Silence or premature disconnect | Phone logs, first-text timing, background state | Record actual error. Patched request timeout is 240s; it does not solve every disconnect. |
| Edge TTS 403 | Server audio selected | Prefer device speech; server macOS fallback can work but adds time. |
| Tools unavailable | API gateway tool configuration and provider tool support | Test harmless tools directly in Hermes; direct-provider app mode bypasses agent tools. |
| Tool started then connection lost | Check whether the action actually happened | Do not blindly retry; duplicate writes/messages may have side effects. |
| Camera unavailable | Pairing, developer enrollment, camera permission | Complete Meta companion registration/permission; test phone and glasses capture separately. |

## Service and diagnostic commands

From the app repository:

```bash
launchctl list com.visionclaw.hermes-glasses-bridge
lsof -nP -iTCP:8765 -sTCP:LISTEN
bash scripts/reinstall-iphone.sh --status
xcrun devicectl list devices
tailscale status
```

When no user task is running, restart the bridge with:

```bash
launchctl kickstart -k "gui/$(id -u)/com.visionclaw.hermes-glasses-bridge"
```

A bridge restart interrupts active requests. Inspect `.runtime/bridge.log`, `.runtime/bridge.error.log`, `.runtime/reinstall.log`, and build/install logs locally. Do not paste them wholesale: they can contain request text, location context, URLs and identifiers. A successful LaunchAgent exit may be a skip rather than a successful install.

## Privacy and credentials

The phone can send contextual data such as time, location, movement, weather and battery status with a query. Requested photos go through the bridge to the configured model. Check app settings and consent before enabling contextual features. Do not describe this as a completely offline system.

The bridge may save history under `~/.hermes_glasses_history/` and session metadata in `~/.hermes_glasses_bridge_session.json`; Hermes maintains its own state under its home. Phone preferences may contain the token-bearing endpoint. Provider SDKs have separate credential stores. Protect backups; exclude these paths from public repos.

Store API keys only in the intended local stores. Rotate exposed bridge/API keys and update both ends. Tailscale supplies the private encrypted network; the bridge token still grants meaningful agent/tool access. No SSH enablement, public ports, or broadened tailnet access are required by this recipe.

## Backup and rollback

Before editing, save private copies of config, ignored bridge `.env`, signing settings and app preferences using approved device backup methods. Keep code changes in a branch; keep secrets outside Git. If a patch causes a regression, restore the previous known-good source/config and rebuild with a still-valid signing profile. Do not uninstall the iPhone app as a routine rollback because that can erase local data.

After rollback, verify launch, auth, short reply and correct route. Gateway/model upgrades, SDK upgrades and iOS upgrades should be separate changes with the same acceptance matrix. Record actual profile expiration; personal-team renewal is not a promise of uninterrupted unattended availability.

## Multiple users

Use a separate Hermes home/profile, bridge token and session namespace for each user. The reference bridge has shared session/history files and is not a hardened multi-tenant service. Do not point several colleagues' phones at one personal agent and assume their conversations or tool permissions are isolated.
