# Hermes models, tools and cost policy

## Required baseline

Get one authorized model working in Hermes before adding the glasses. The glasses use `hermes-agent` through the local gateway when model/provider overrides are empty. The gateway's active configuration governs execution. A model name shown in a Desktop chat is not proof of the gateway's provider or model.

Use the provider IDs and model inventory exposed by your installed Hermes version. Test the actual provider request rather than asking a model which model it is. SDK/subscription routes and custom adapters may not be present in a colleague's stock installation. A missing adapter is a compatibility issue, not a reason to invent credentials or a provider ID.

## Recorded reference design, optional for a new user

| Purpose | Reference configuration | Portability note |
|---|---|---|
| Full main agent | Claude SDK Opus route | Requires compatible adapter and authorized account; independently verify current model ID. |
| Budget catalog | Custom OpenRouter-compatible provider with discovery disabled and an explicit small model list | Useful when a built-in picker expands to the full catalog despite a list. |
| Fast fallback | A tested free model, then a cheap paid model | Free endpoints can be unavailable, rate-limited or slower; test tool support as well as text. |
| Council / mixture of agents | Google advisor + OpenAI advisor, Claude aggregator | This is application-level multi-agent orchestration, not changes to a model's internal mixture-of-experts architecture. |
| Vision | A separately verified image-capable route | A text-only response is not vision acceptance. |

Reference model labels used during setup included Google Argon, OpenAI Astra and Claude Opus. These are not universal installation requirements. Do not hardcode them without confirming the current account's inventory. The exact personal Hermes config is deliberately excluded.

## Build a free/cheap shortlist

1. Obtain current model IDs and input/output prices from the provider's official catalog; record the verification date.
2. Set an explicit per-million-token input and output ceiling with the owner. Include tool capability, context needs and real latency, not price alone.
3. Test each candidate with a minimal text request and a harmless tool-call request. Record auth/balance failures separately from unsupported models and transient rate limits.
4. Disable or hide confirmed unusable choices reversibly. Retain credentials privately for repair; do not delete providers after one transient failure.
5. Verify both the UI catalog and actual request routing. A short visible list is not an account-level spending cap.

The reference shortlist at the time of setup was `nvidia/nemotron-3.5-lightning:free`, `cohere/north-mini-code:free`, `nvidia/nemotron-3-ultra-550b-a55b:free`, `z-ai/glm-5.3-flash`, and `deepseek/deepseek-v4-flash-0731`. It is a historical example, not a current recommendation or availability guarantee. Reprice and retest before use. Use the provider dashboard for spending controls.

## Council setup and validation

Configure advisor routes and a synthesis/aggregator route through the installed Hermes MoA facility if supported. Keep it optional until every advisor works individually. Then run one real fan-out task and confirm both advisor results and aggregation in execution evidence. A successful call to the aggregator alone does not test council fan-out.

Council routing can increase latency and cost; it is not the default recommendation for every spoken utterance. The reference configuration used loud failure reporting so a missing advisor was not silently represented as a successful full council response. Full council behavior was tested separately in Hermes; it was not independently revalidated through the physical glasses in this handoff.

## Changing models safely

Save the desired main/gateway configuration, remove stale glasses-specific overrides, and start a new glasses session. If the gateway retains old settings, reload it using its supported mechanism when no task is in progress. Restarting only the phone does not necessarily reload the gateway. Confirm the executed route from trusted runtime evidence; never rely on model self-identification.

Memory is scoped by the gateway/profile/session configuration. Using the full agent does not automatically merge every Desktop chat, specialist memory or another user's history into the glasses conversation.
