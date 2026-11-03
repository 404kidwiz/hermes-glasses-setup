//
// BargeInPolicy.swift
//
// Pure rules for cutting Hermes off mid-reply without treating his own
// voice as the wearer talking. Kept out of the view model so it can be
// tested with swiftc like the other standalone suites.
//

import Foundation

enum BargeInPolicy {
    static func normalize(_ text: String) -> String {
        text.lowercased()
            .filter { $0.isLetter || $0.isNumber || $0 == " " }
            .trimmingCharacters(in: .whitespaces)
    }

    /// Glasses hearing Hermes, not the wearer. A genuine quote of the
    /// reply loses — acceptable.
    static func isEcho(partial: String, ofResponse response: String) -> Bool {
        let heard = normalize(partial)
        guard !heard.isEmpty else { return true }
        return normalize(response).contains(heard)
    }

    /// Cut in on the first real word ("stop", "wait", "hey") or two tokens.
    /// Single letters and "ok" stay quiet so TTS leak does not self-interrupt.
    static func shouldCutIn(partial: String, ofResponse response: String) -> Bool {
        guard !isEcho(partial: partial, ofResponse: response) else { return false }
        let words = normalize(partial)
            .split(whereSeparator: { $0.isWhitespace })
            .filter { !$0.isEmpty }
        guard let first = words.first else { return false }
        if words.count >= 2 { return true }
        return first.count >= 3
    }
}
