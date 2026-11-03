import Foundation

@main struct RecoveryChecks {
    @MainActor static func main() async {
        var failures = 0
        func check(_ value: Bool, _ name: String) {
            print("\(value ? "PASS" : "FAIL") \(name)")
            if !value { failures += 1 }
        }
        for listening in [false, true] {
            for pending in [false, true] {
                check(HermesAPIClient.mayReconnect(isListening: listening, requestPending: pending)
                      == (listening && !pending), "idle recovery policy \(listening)/\(pending)")
            }
        }
        check(HermesAPIClient.safeEndpoint("ws://user:password@example.test:8765/voice?token=secret")
              == "example.test:8765", "diagnostics omit credentials, path and query")
        check(!HermesAPIClient.isWelcome(.string("{}")), "reject missing welcome")
        check(!HermesAPIClient.isWelcome(.data(Data())), "reject binary welcome")
        let bad = HermesAPIClient(endpoint: "ws://127.0.0.1:19876/bad?token=private")
        check(!(await bad.connect()), "reject live error handshake")
        check(!bad.diagnosticSummary.contains("private"), "error diagnostics redact token")

        let cancelled = HermesAPIClient(endpoint: "ws://127.0.0.1:19876/slowwelcome")
        let pendingConnect = Task { await cancelled.connect() }
        try? await Task.sleep(nanoseconds: 100_000_000)
        cancelled.disconnect()
        check(!(await pendingConnect.value), "Stop cancels delayed transport startup")
        check(!cancelled.isConnected, "late welcome cannot restore stopped transport")

        let dropped = HermesAPIClient(endpoint: "ws://127.0.0.1:19876/drop")
        var disconnects = 0
        dropped.onDisconnected = { disconnects += 1 }
        check(await dropped.connect(), "drop test connected")
        dropped.sendQuery("synthetic test", bridgeTTS: false)
        try? await Task.sleep(nanoseconds: 1_000_000_000)
        check(!dropped.isConnected && dropped.hasPendingRequest, "interrupted outcome remains uncertain")
        check(disconnects == 1, "single disconnect notification")
        dropped.onDisconnected = nil
        dropped.disconnect()

        if ProcessInfo.processInfo.arguments.contains("--short") {
            print(failures == 0 ? "SHORT CHECKS PASS" : "\(failures) FAILED")
            exit(failures == 0 ? 0 : 1)
        }
        let client = HermesAPIClient(endpoint: "ws://127.0.0.1:19876/long")
        var received = false
        client.onResponse = { _, _, _ in received = true }
        check(await client.connect(), "long test connected")
        client.sendQuery("synthetic delayed test", bridgeTTS: false)
        check(client.hasPendingRequest, "request marked pending before delivery")
        for _ in 0..<80 {
            if received { break }
            try? await Task.sleep(nanoseconds: 1_000_000_000)
        }
        check(received && client.isConnected, "65-second delayed response survives")
        check(!client.hasPendingRequest, "completed request no longer pending")
        check(client.diagnosticSummary.contains("first text"), "response latency recorded")
        client.disconnect()
        check(!client.isConnected, "explicit stop closes transport")
        print(failures == 0 ? "ALL PASS" : "\(failures) FAILED")
        exit(failures == 0 ? 0 : 1)
    }
}
