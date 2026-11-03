//
// HermesSpeechSynthesizer.swift
//
// On-device text-to-speech for Hermes's replies via AVSpeechSynthesizer.
// Replaces bridge-side TTS: speech starts the instant the response text
// arrives, no cloud synthesis or PCM streaming. Plays through the current
// audio route (glasses in HFP mode). Interruption is stopSpeaking().
//

import AVFoundation
import Foundation
import os

final class HermesSpeechSynthesizer: NSObject, @unchecked Sendable {
    // MARK: - Callbacks (delivered on the main queue)

    /// Fired when an utterance finishes OR is cancelled
    var onFinished: (() -> Void)?

    // MARK: - Private

    private let logger = Logger(subsystem: "com.flowsxr.hermesglasses", category: "tts")
    private let synthesizer = AVSpeechSynthesizer()
    private let voice: AVSpeechSynthesisVoice?
    /// Utterances of the current reply still queued or speaking. Tracked by
    /// identity, not a count: delegate callbacks hop to main asynchronously,
    /// so a finish for an utterance that speak()/stop() already replaced can
    /// land after the next one is queued - a counter would take it off the
    /// NEW reply and fire onFinished mid-sentence.
    private var pending: [AVSpeechUtterance] = []

    override init() {
        // Best installed English voice: premium > enhanced > default.
        // Users can download nicer voices in Settings → Accessibility →
        // Spoken Content → Voices.
        let english = AVSpeechSynthesisVoice.speechVoices()
            .filter { $0.language.hasPrefix("en") }
        let preferred = english.filter { $0.language == "en-US" }
        voice = (preferred.isEmpty ? english : preferred)
            .max { $0.quality.rawValue < $1.quality.rawValue }

        super.init()
        synthesizer.delegate = self
        // Stay on the session HermesAudioManager already configured
        // (playAndRecord + mixWithOthers) so the mic tap keeps running
        // during TTS and barge-in can hear the wearer.
        synthesizer.usesApplicationAudioSession = true
        if let voice {
            logger.info("TTS voice: \(voice.name, privacy: .public) (quality \(voice.quality.rawValue))")
        }
    }

    // MARK: - Public API

    var isSpeaking: Bool { synthesizer.isSpeaking }

    func speak(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else {
            DispatchQueue.main.async { [weak self] in self?.onFinished?() }
            return
        }
        // Replaced utterances are forgotten first, so their didCancel is
        // ignored rather than read as this reply finishing.
        pending.removeAll()
        if synthesizer.isSpeaking {
            synthesizer.stopSpeaking(at: .immediate)
        }
        enqueue(trimmed)
    }

    /// Queue another sentence without cutting the one already in flight.
    func enqueue(_ text: String) {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        let utterance = AVSpeechUtterance(string: trimmed)
        utterance.voice = voice
        pending.append(utterance)
        logger.info("Speaking \(trimmed.count) chars on-device (queue \(self.pending.count))")
        synthesizer.speak(utterance)
    }

    /// Barge-in: stop immediately and report finished once.
    func stop() {
        pending.removeAll()
        guard synthesizer.isSpeaking else { return }
        synthesizer.stopSpeaking(at: .immediate)
        DispatchQueue.main.async { [weak self] in self?.onFinished?() }
    }

    /// A delegate callback for `utterance`: fire onFinished only when it was
    /// the last live utterance. Stale callbacks (already replaced) are no-ops.
    private func settle(_ utterance: AVSpeechUtterance) {
        guard let index = pending.firstIndex(where: { $0 === utterance }) else { return }
        pending.remove(at: index)
        if pending.isEmpty {
            onFinished?()
        }
    }
}

// MARK: - AVSpeechSynthesizerDelegate

extension HermesSpeechSynthesizer: AVSpeechSynthesizerDelegate {
    func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didFinish utterance: AVSpeechUtterance
    ) {
        DispatchQueue.main.async { [weak self] in
            self?.settle(utterance)
        }
    }

    func speechSynthesizer(
        _ synthesizer: AVSpeechSynthesizer,
        didCancel utterance: AVSpeechUtterance
    ) {
        // speak()/stop() already dropped it from `pending`, so this is a
        // no-op for every cancel the class issues itself.
        DispatchQueue.main.async { [weak self] in
            self?.settle(utterance)
        }
    }
}
