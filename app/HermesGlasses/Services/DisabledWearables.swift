//
//  DisabledWearables.swift
//  Hermes Glasses
//
//  Stand-in for the Meta DAT SDK used when `Wearables.configure()` fails
//  (e.g. the local 0/0 Developer Mode credentials are rejected, or the
//  Meta app isn't in Developer Mode). Without this, `Wearables.shared`
//  asserts and the app hard-crashes on launch. The stub lets the app keep
//  running in phone-only mode: glasses features are unavailable, but the
//  bridge voice loop still works.
//

import MWDATCore
import Foundation

struct NoopListenerToken: AnyListenerToken {
    func cancel() async {}
}

final class DisabledWearables: WearablesInterface {
    var registrationState: RegistrationState { .unavailable }
    var devices: [DeviceIdentifier] { [] }

    func addRegistrationStateListener(
        _ listener: @escaping @Sendable (RegistrationState) -> Void
    ) -> any AnyListenerToken { NoopListenerToken() }

    func registrationStateStream() -> AsyncStream<RegistrationState> {
        AsyncStream { $0.finish() }
    }

    func startRegistration() async throws(RegistrationError) {
        throw .configurationInvalid
    }

    func handleUrl(_ url: URL) async throws(WearablesHandleURLError) -> Bool {
        throw .registrationError
    }

    func startUnregistration() async throws(UnregistrationError) {
        throw .configurationInvalid
    }

    func openFirmwareUpdate() async throws(NavigationError) {
        throw .notRegistered
    }

    func openDATGlassesAppUpdate() async throws(NavigationError) {
        throw .notRegistered
    }

    func addDevicesListener(
        _ listener: @escaping @Sendable ([DeviceIdentifier]) -> Void
    ) -> any AnyListenerToken { NoopListenerToken() }

    func devicesStream() -> AsyncStream<[DeviceIdentifier]> {
        AsyncStream { $0.finish() }
    }

    func deviceForIdentifier(_ identifier: DeviceIdentifier) -> Device? { nil }

    func checkPermissionStatus(_ permission: Permission) async throws(PermissionError) -> PermissionStatus {
        throw .noDevice
    }

    func requestPermission(_ permission: Permission) async throws(PermissionError) -> PermissionStatus {
        throw .noDevice
    }

    func createSession(deviceSelector: any DeviceSelector) throws(DeviceSessionError) -> DeviceSession {
        throw .noEligibleDevice
    }

    func deviceStateStream(for identifier: DeviceIdentifier) -> AsyncStream<DeviceState> {
        AsyncStream { $0.finish() }
    }
}
