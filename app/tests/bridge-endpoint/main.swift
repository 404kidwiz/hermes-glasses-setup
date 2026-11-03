//
// Standalone tests for BridgeEndpointConfig. No XCTest target, so build via
// swiftc and run WITH launch arguments - adoptLaunchArguments reads the real
// argument domain, which is the mechanism under test:
//   xcrun swiftc HermesGlasses/Services/BridgeEndpointConfig.swift \
//     tests/bridge-endpoint/main.swift -o /tmp/bridge-endpoint-tests && \
//   /tmp/bridge-endpoint-tests -hermes_endpoint 'ws://mac.local:8765/voice?token=t1' \
//     -endpoint_presets '{Home="ws://mac.local:8765/voice?token=t1";}'
//
import Foundation

var failures = 0
func expect(_ cond: Bool, _ label: String) {
    if cond { print("PASS \(label)") } else { print("FAIL \(label)"); failures += 1 }
}

// isBridgeURL
expect(BridgeEndpointConfig.isBridgeURL("ws://mac.local:8765/voice?token=abc"), "ws URL")
expect(BridgeEndpointConfig.isBridgeURL("wss://host.ts.net/voice"), "wss URL")
expect(!BridgeEndpointConfig.isBridgeURL("token=abc"), "bare token rejected")
expect(!BridgeEndpointConfig.isBridgeURL("http://mac.local:8765"), "http rejected")
expect(!BridgeEndpointConfig.isBridgeURL(""), "empty rejected")
expect(!BridgeEndpointConfig.isBridgeURL("ws://"), "no host rejected")
expect(BridgeEndpointConfig.isBridgeURL("ws://mac.local:8765/voice\n"), "trailing newline tolerated")

// mergedPresets
let merged = BridgeEndpointConfig.mergedPresets(
    persisted: ["Home": "ws://192.168.1.68:8765/voice", "Mac 14": "token=abc",
                "Away": "ws://a.ts.net:8765/voice?token=x"],
    pushed: ["Home": "ws://mac.local:8765/voice?token=x"])
expect(merged["Home"] == "ws://mac.local:8765/voice?token=x", "pushed preset wins")
expect(merged["Mac 14"] == nil, "invalid preset dropped")
expect(merged["Away"] == "ws://a.ts.net:8765/voice?token=x", "untouched preset kept")
expect(BridgeEndpointConfig.mergedPresets(persisted: [:], pushed: nil).isEmpty, "empty stays empty")

// adoptLaunchArguments against a throwaway suite, using this process's
// real launch arguments (see header).
let suite = "hermes.bridge-endpoint-tests.\(ProcessInfo.processInfo.processIdentifier)"
let defaults = UserDefaults(suiteName: suite)!
defaults.set(["Home": "ws://192.168.1.68:8765/voice", "Mac 14": "token=abc",
              "Away": "ws://a.ts.net:8765/voice?token=x"],
             forKey: BridgeEndpointConfig.presetsKey)
let argsBefore = defaults.volatileDomain(forName: UserDefaults.argumentDomain)
BridgeEndpointConfig.adoptLaunchArguments(defaults: defaults, domainName: suite)
let saved = defaults.persistentDomain(forName: suite) ?? [:]
if argsBefore[BridgeEndpointConfig.endpointKey] != nil {
    expect(saved[BridgeEndpointConfig.endpointKey] as? String
           == "ws://mac.local:8765/voice?token=t1", "launch endpoint persisted")
    let presets = saved[BridgeEndpointConfig.presetsKey] as? [String: String] ?? [:]
    expect(presets["Home"] == "ws://mac.local:8765/voice?token=t1", "launch preset persisted")
    expect(presets["Mac 14"] == nil, "invalid saved preset removed")
    expect(presets["Away"] == "ws://a.ts.net:8765/voice?token=x", "other saved preset kept")
    // QA F1: after adoption the arguments must stop shadowing the saved
    // values, or a preset saved this launch overwrites the others.
    let argsAfter = defaults.volatileDomain(forName: UserDefaults.argumentDomain)
    expect(argsAfter[BridgeEndpointConfig.presetsKey] == nil
           && argsAfter[BridgeEndpointConfig.endpointKey] == nil, "launch args cleared")
    var live = defaults.dictionary(forKey: BridgeEndpointConfig.presetsKey) as? [String: String] ?? [:]
    expect(live.count == 2, "reads see saved presets, not just pushed")
    live["Office"] = "ws://office.local:8765/voice"
    defaults.set(live, forKey: BridgeEndpointConfig.presetsKey)
    let afterSave = defaults.dictionary(forKey: BridgeEndpointConfig.presetsKey) as? [String: String] ?? [:]
    expect(afterSave.keys.sorted() == ["Away", "Home", "Office"], "save this launch keeps Away")
    defaults.set("ws://typed.local:8765/voice", forKey: BridgeEndpointConfig.endpointKey)
    expect(defaults.string(forKey: BridgeEndpointConfig.endpointKey)
           == "ws://typed.local:8765/voice", "typed endpoint not shadowed")
} else {
    print("FAIL run with the launch arguments in the header"); failures += 1
}
// Voice launch preference persists, but must not shadow later Settings changes.
for requested in [true, false] {
    defaults.setVolatileDomain(["use_device_tts": requested], forName: UserDefaults.argumentDomain)
    BridgeEndpointConfig.adoptLaunchArguments(defaults: defaults, domainName: suite)
    expect(defaults.persistentDomain(forName: suite)?["use_device_tts"] as? Bool == requested,
           "voice preference persisted: \(requested)")
    expect(defaults.volatileDomain(forName: UserDefaults.argumentDomain)["use_device_tts"] == nil,
           "voice override cleared")
    defaults.set(!requested, forKey: "use_device_tts")
    expect(defaults.bool(forKey: "use_device_tts") == !requested, "Settings remains editable")
}
defaults.removePersistentDomain(forName: suite)

print(failures == 0 ? "ALL PASS" : "\(failures) FAILED")
exit(failures == 0 ? 0 : 1)
