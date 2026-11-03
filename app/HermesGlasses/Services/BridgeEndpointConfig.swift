import Foundation

/// Bridge endpoint + named presets, as stored in UserDefaults.
///
/// The paired Mac can push them at launch:
///   xcrun devicectl device process launch --device <id> <bundle-id> -- \
///     -hermes_endpoint 'ws://host.local:8765/voice?token=…' \
///     -endpoint_presets '{Home="ws://…"; Away="ws://…";}'
/// Launch arguments land in the argument domain, which shadows the app's
/// own values but is never saved - so `adoptLaunchArguments` copies them
/// over. That is what lets a fresh install or a token change be configured
/// without typing a 48-character token on the phone. Writing the prefs
/// plist into the container does NOT work: cfprefsd restores its cached
/// copy over it.
enum BridgeEndpointConfig {
    static let endpointKey = "hermes_endpoint"
    static let presetsKey = "endpoint_presets"

    /// ws:// or wss:// with a host. Anything else can only fail to connect
    /// (a bare "token=…" preset used to be saveable).
    static func isBridgeURL(_ string: String) -> Bool {
        guard let url = URL(string: string.trimmingCharacters(in: .whitespacesAndNewlines)),
              let scheme = url.scheme?.lowercased(),
              scheme == "ws" || scheme == "wss",
              let host = url.host, !host.isEmpty
        else { return false }
        return true
    }

    /// Saved presets with pushed ones layered on top (same name wins),
    /// minus anything that isn't a bridge URL.
    static func mergedPresets(
        persisted: [String: String],
        pushed: [String: String]?
    ) -> [String: String] {
        persisted
            .merging(pushed ?? [:]) { _, new in new }
            .filter { isBridgeURL($0.value) }
            .mapValues { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
    }

    /// Persist launch-argument config and drop invalid saved presets.
    /// `domainName` is the app's persistent domain (its bundle id).
    static func adoptLaunchArguments(
        defaults: UserDefaults = .standard,
        domainName: String? = Bundle.main.bundleIdentifier
    ) {
        var args = defaults.volatileDomain(forName: UserDefaults.argumentDomain)
        if let endpoint = args[endpointKey] as? String, isBridgeURL(endpoint) {
            defaults.set(endpoint.trimmingCharacters(in: .whitespacesAndNewlines),
                         forKey: endpointKey)
        }
        // Deployment can select the existing low-latency speech mode without
        // leaving a launch override that shadows the user's Settings toggle.
        let voiceKey = "use_device_tts"
        if args[voiceKey] != nil {
            defaults.set(defaults.bool(forKey: voiceKey), forKey: voiceKey)
        }
        defer {
            // Once adopted, stop the arguments shadowing the saved values for
            // the rest of this launch - otherwise a preset saved now is
            // merged into the PUSHED dict and the other saved presets are
            // lost, and an endpoint typed in Settings reads back as the
            // pushed one.
            if args[endpointKey] != nil || args[presetsKey] != nil || args[voiceKey] != nil {
                args[endpointKey] = nil
                args[presetsKey] = nil
                args[voiceKey] = nil
                defaults.setVolatileDomain(args, forName: UserDefaults.argumentDomain)
            }
        }
        let saved = domainName.flatMap { defaults.persistentDomain(forName: $0) } ?? [:]
        let persisted = saved[presetsKey] as? [String: String] ?? [:]
        let merged = mergedPresets(
            persisted: persisted,
            pushed: args[presetsKey] as? [String: String]
        )
        if merged != persisted {
            defaults.set(merged, forKey: presetsKey)
        }
    }
}
