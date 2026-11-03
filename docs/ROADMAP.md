# Improvements ranked by value

These are proposals, not claims of implemented features.

1. **Connection and latency diagnostics.** Show selected route, VPN reachability, last error, model/tool status and time to first text/audio. Use redacted metrics rather than full conversation logging. This reduces guesswork when a long tool request looks like broken Wi-Fi.
2. **Fast / Full / Council modes.** Let the user choose low-latency everyday answers, full tool work, or explicit multi-agent analysis. Validate each route, make the active mode visible, and do not silently downgrade capability or exceed a budget.
3. **Safe reconnection and cancellation.** Reconnect the transport after a network change without automatically replaying side-effecting requests. Introduce tested request identity/idempotency and explicit cancel/status handling before retrying interrupted tasks.
4. **Operational readiness.** Add clear signing-expiry/account-health alerts and a supported always-on host option. A dedicated plugged-in Mac improves availability; an Internet/VPS migration requires its own credential, data and tool-access review.
5. **Physical device acceptance and packaging.** Test glasses audio/camera, interruptions, locked-phone behavior and long sessions. Then replace hardcoded service identity fields with a reviewed installer, and evaluate appropriate app distribution for the intended audience.

Recommended next step: finish the physical-hardware and longer-turn acceptance matrix before adding more modes or making a broader reliability claim. Measure matched prompts on Wi-Fi/cellular before changing network settings.
