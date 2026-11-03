//
// HermesAPIClient.swift
//
// WebSocket client for communicating with Hermes Agent's voice endpoint.
// Handles bidirectional audio streaming: sends captured audio from glasses,
// receives STT transcripts, agent text responses, and TTS audio.
//

import Foundation
import os

/// WebSocket-based client for Hermes Agent voice API
final class HermesAPIClient: NSObject {
    // A reconnect restores transport only. An uncertain request is never replayed.
    static func mayReconnect(isListening: Bool, requestPending: Bool) -> Bool {
        isListening && !requestPending
    }

    static func safeEndpoint(_ endpoint: String) -> String {
        guard let url = URL(string: endpoint), let host = url.host else { return "invalid endpoint" }
        return host + (url.port.map { ":\($0)" } ?? "")
    }

    static func isWelcome(_ message: URLSessionWebSocketTask.Message) -> Bool {
        guard case .string(let text) = message, let data = text.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any]
        else { return false }
        return object["type"] as? String == "welcome"
    }

    private struct Telemetry {
        var pending = false
        var sentAt: Date?
        var firstText: TimeInterval?
        var event = "Not connected"
    }
    private let telemetry = OSAllocatedUnfairLock(initialState: Telemetry())
    var hasPendingRequest: Bool { telemetry.withLock { $0.pending } }
    var diagnosticSummary: String {
        telemetry.withLock { t in
            let timing = t.firstText.map { String(format: " · first text %.1fs", $0) } ?? ""
            return "\(Self.safeEndpoint(endpoint)) · \(t.event) · \(t.pending ? "request pending" : "idle")\(timing)"
        }
    }
    var onDiagnostics: ((String) -> Void)?
    private func diagnose(_ event: String) {
        telemetry.withLock { $0.event = event }
        let summary = diagnosticSummary
        Task { @MainActor [weak self] in self?.onDiagnostics?(summary) }
    }

    // MARK: - Callbacks

    var onTranscript: ((String) -> Void)?
    /// (text, bridgeWillSendAudio, alreadyStreamed)
    /// alreadyStreamed: deltas were spoken/shown; don't speak the full text.
    var onResponse: ((String, Bool, Bool) -> Void)?
    /// Speakable sentence while the agent is still generating.
    var onResponseDelta: ((String) -> Void)?
    /// Short filler ("One sec.") the bridge sends when a turn will be slow.
    /// Not part of the reply; with bridge TTS its audio arrives as a clip.
    var onAck: ((String) -> Void)?
    /// Bridge started a TTS stream. Play clips as they arrive.
    var onAudioStreamStart: (() -> Void)?
    var onAudioResponse: ((Data) -> Void)?
    /// Bridge finished sending TTS clips.
    var onAudioStreamEnd: (() -> Void)?
    var onPlaybackComplete: (() -> Void)?
    var onError: ((String) -> Void)?
    /// Called when the WebSocket disconnects
    var onDisconnected: (() -> Void)?
    /// Bridge asks the app to take a photo with the glasses
    var onCapturePhotoRequested: (() -> Void)?
    /// Bridge confirmed the conversation was reset
    var onSessionReset: (() -> Void)?

    // MARK: - Private

    private let endpoint: String
    private var webSocket: URLSessionWebSocketTask?
    private var session: URLSession?
    /// Behind a lock because the receive loop clears it from a background
    /// executor while the view model reads it on the main actor to decide
    /// whether an utterance can be sent. A plain `Bool` was a data race; an
    /// actor hop would have made `disconnect()` land after callers had
    /// already read the stale value.
    private let connectedFlag = OSAllocatedUnfairLock(initialState: false)
    var isConnected: Bool { connectedFlag.withLock { $0 } }
    private var receiveTask: Task<Void, Never>?
    private var isFinalized: Bool = false
    /// TTS audio accumulated between audio_start and audio_end
    private var ttsBuffer = Data()
    /// Bridge is streaming per-sentence clips (audio_clip markers).
    private var awaitingAudioClips = false

    init(endpoint: String) {
        self.endpoint = endpoint
        super.init()
    }

    // MARK: - Public API

    /// Connect to the Hermes bridge and wait for its welcome message.
    /// Returns true once the bridge has confirmed the connection.
    @discardableResult
    func connect() async -> Bool {
        guard let url = URL(string: endpoint) else {
            await reportError("Invalid Hermes endpoint URL")
            return false
        }

        diagnose("Connecting")
        let config = URLSessionConfiguration.default
        // Agent tool turns can be silent longer than a normal HTTP request.
        // Match the bridge turn budget with margin rather than cutting off at 10s.
        config.timeoutIntervalForRequest = 240
        config.timeoutIntervalForResource = 24 * 60 * 60
        let urlSession = URLSession(configuration: config)
        session = urlSession

        let ws = urlSession.webSocketTask(with: url)
        webSocket = ws
        ws.resume()

        do {
            // The bridge sends {"type":"welcome"} immediately on connect
            let first = try await ws.receive()
            guard Self.isWelcome(first) else { throw URLError(.badServerResponse) }
            guard webSocket === ws, !Task.isCancelled else { return false }
            setConnected(true)
            diagnose("Connected")
            await handleMessage(first)

            receiveTask = Task { [weak self] in
                await self?.receiveLoop()
            }
            return true
        } catch {
            diagnose("Connect failed (\((error as NSError).domain) \((error as NSError).code))")
            await reportError(diagnosticSummary)
            disconnect()
            return false
        }
    }

    /// Disconnect from Hermes
    func disconnect() {
        receiveTask?.cancel()
        receiveTask = nil
        webSocket?.cancel(with: .normalClosure, reason: nil)
        webSocket = nil
        session?.invalidateAndCancel()
        session = nil
        setConnected(false)
        isFinalized = false
        Task { @MainActor in
            onDisconnected?()
        }
    }

    func sendAudioChunk(_ data: Data) {
        guard isConnected, let ws = webSocket, !isFinalized else { return }

        ws.send(.data(data)) { [weak self] error in
            if let error {
                Task { @MainActor in
                    self?.onError?("Send error: \(error.localizedDescription)")
                }
            }
        }
    }

    /// Send a diagnostic message that the bridge prints to its log
    func sendDebug(_ message: String) {
        guard isConnected, let ws = webSocket else { return }
        let payload: [String: String] = ["type": "debug", "msg": message]
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let text = String(data: data, encoding: .utf8) else { return }
        ws.send(.string(text)) { _ in }
    }

    /// Ask the bridge to forget the conversation (same-day memory reset)
    func sendNewSession() {
        guard isConnected, let ws = webSocket else { return }
        ws.send(.string(#"{"type":"new_session"}"#)) { _ in }
    }

    /// Send an on-device-transcribed query. bridgeTTS asks the bridge to
    /// synthesize the reply voice (edge-tts); false = app speaks locally.
    func sendQuery(_ text: String, bridgeTTS: Bool) {
        guard isConnected, let ws = webSocket else { return }
        let payload: [String: Any] = ["type": "query", "text": text,
                                      "tts": bridgeTTS]
        guard let data = try? JSONSerialization.data(withJSONObject: payload),
              let json = String(data: data, encoding: .utf8) else { return }
        telemetry.withLock { t in
            t.pending = true
            t.sentAt = Date()
            t.firstText = nil
        }
        diagnose("Waiting for reply")
        ws.send(.string(json)) { [weak self] error in
            if let error {
                Task { @MainActor in
                    self?.diagnose("Send failed (\((error as NSError).code)); outcome unknown")
                    self?.onError?("Request delivery is uncertain. Check the action before retrying.")
                }
            }
        }
    }

    /// Send a captured JPEG as base64 JSON (binary frames are mic audio only)
    func sendPhoto(_ data: Data) {
        guard isConnected, let ws = webSocket else { return }
        let payload: [String: String] = [
            "type": "photo",
            "data": data.base64EncodedString(),
        ]
        guard let json = try? JSONSerialization.data(withJSONObject: payload),
              let text = String(data: json, encoding: .utf8) else { return }
        ws.send(.string(text)) { [weak self] error in
            if let error {
                Task { @MainActor in
                    self?.onError?("Photo send error: \(error.localizedDescription)")
                }
            }
        }
    }

    func sendPhotoError(_ message: String) {
        guard isConnected, let ws = webSocket else { return }
        let payload: [String: String] = ["type": "photo_error", "message": message]
        guard let json = try? JSONSerialization.data(withJSONObject: payload),
              let text = String(data: json, encoding: .utf8) else { return }
        ws.send(.string(text)) { _ in }
    }

    func finalizeAudio() async {
        guard isConnected, let ws = webSocket, !isFinalized else { return }
        isFinalized = true

        let endMarker = #"{"type":"end_of_audio"}"#
        ws.send(.string(endMarker)) { [weak self] error in
            if let error {
                Task { @MainActor in
                    self?.onError?("Finalize error: \(error.localizedDescription)")
                }
            }
        }
    }

    // MARK: - Private

    private func setConnected(_ value: Bool) {
        connectedFlag.withLock { $0 = value }
    }

    private func receiveLoop() async {
        guard let ws = webSocket else { return }

        while !Task.isCancelled, ws.closeCode == .invalid {
            do {
                let message = try await ws.receive()
                await handleMessage(message)
            } catch {
                setConnected(false)
                if !Task.isCancelled {
                    diagnose("Disconnected (\((error as NSError).domain) \((error as NSError).code), close \(ws.closeCode.rawValue))")
                    await MainActor.run { [weak self] in
                        self?.onDisconnected?()
                    }
                }
                break
            }
        }
    }

    private func handleMessage(_ message: URLSessionWebSocketTask.Message) async {
        switch message {
        case .string(let text):
            await handleTextMessage(text)
        case .data(let data):
            // Binary from the bridge is a TTS chunk; play only when complete
            ttsBuffer.append(data)
        @unknown default:
            break
        }
    }

    private func handleTextMessage(_ text: String) async {
        guard let data = text.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let type = json["type"] as? String else {
            return
        }

        await MainActor.run { [weak self] in
            switch type {
            case "welcome":
                break
            case "transcript":
                if let transcript = json["text"] as? String {
                    self?.onTranscript?(transcript)
                }
            case "response":
                self?.telemetry.withLock { $0.pending = false }
                self?.diagnose("Reply received")
                if let response = json["text"] as? String {
                    // Absent "tts" field = old bridge that always streams
                    // audio afterwards
                    let bridgeAudio = (json["tts"] as? Bool) ?? true
                    let streamed = (json["streamed"] as? Bool) ?? false
                    self?.onResponse?(response, bridgeAudio, streamed)
                }
            case "response_delta":
                self?.telemetry.withLock { t in
                    if t.firstText == nil, let sent = t.sentAt { t.firstText = Date().timeIntervalSince(sent) }
                }
                self?.diagnose("Receiving reply")
                if let chunk = json["text"] as? String, !chunk.isEmpty {
                    self?.onResponseDelta?(chunk)
                }
            case "ack":
                if let ack = json["text"] as? String, !ack.isEmpty {
                    self?.onAck?(ack)
                }
            case "audio_start":
                self?.ttsBuffer.removeAll()
                self?.awaitingAudioClips = true
                self?.onAudioStreamStart?()
            case "audio_clip":
                if let self, !self.ttsBuffer.isEmpty {
                    let clip = self.ttsBuffer
                    self.ttsBuffer.removeAll()
                    self.onAudioResponse?(clip)
                }
            case "audio_end":
                if let self, !self.ttsBuffer.isEmpty {
                    let audio = self.ttsBuffer
                    self.ttsBuffer.removeAll()
                    self.onAudioResponse?(audio)
                }
                self?.awaitingAudioClips = false
                self?.onAudioStreamEnd?()
                self?.isFinalized = false
            case "error":
                if let msg = json["message"] as? String {
                    self?.onError?("Hermes: \(msg)")
                }
            case "capture_photo":
                self?.onCapturePhotoRequested?()
            case "session_reset":
                self?.onSessionReset?()
            default:
                break
            }
        }
    }

    private func reportError(_ message: String) async {
        await MainActor.run { [weak self] in
            self?.onError?(message)
        }
    }
}
