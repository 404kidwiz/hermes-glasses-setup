//
// Standalone tests for BargeInPolicy.
//   xcrun swiftc \
//     HermesGlasses/Services/BargeInPolicy.swift \
//     tests/barge-in/main.swift -o /tmp/barge-in-tests && /tmp/barge-in-tests
//
import Foundation

var failures = 0
func expect(_ got: Bool, _ want: Bool, _ label: String) {
    if got == want { print("PASS \(label)") }
    else { failures += 1; print("FAIL \(label)\n  got:  \(got)\n  want: \(want)") }
}

let reply = "Sounds like the name got cut off — this is... who? Say the name and I'll lock it in."

expect(BargeInPolicy.isEcho(partial: "Sounds like", ofResponse: reply), true,
       "opening words of the reply are echo")
expect(BargeInPolicy.shouldCutIn(partial: "Sounds like", ofResponse: reply), false,
       "echo must not barge in")
expect(BargeInPolicy.shouldCutIn(partial: "stop", ofResponse: reply), true,
       "stop is a one-word cut-in")
expect(BargeInPolicy.shouldCutIn(partial: "wait", ofResponse: reply), true,
       "wait is a one-word cut-in")
expect(BargeInPolicy.shouldCutIn(partial: "hey hermes", ofResponse: reply), true,
       "two words that are not in the reply")
expect(BargeInPolicy.shouldCutIn(partial: "ok", ofResponse: reply), false,
       "ok is too short — TTS leak")
expect(BargeInPolicy.shouldCutIn(partial: "I", ofResponse: reply), false,
       "single letter is not a cut-in")
expect(BargeInPolicy.shouldCutIn(partial: "", ofResponse: reply), false,
       "empty partial is echo/noise")
expect(BargeInPolicy.shouldCutIn(partial: "this is my wife", ofResponse: reply), true,
       "wearer talking about the photo is not echo")

print(failures == 0 ? "\nALL PASS" : "\n\(failures) FAILURES")
exit(failures == 0 ? 0 : 1)
