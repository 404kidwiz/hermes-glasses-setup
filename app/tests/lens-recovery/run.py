"""Exercise the actual camera-session startup function with a deterministic SDK double."""
from pathlib import Path
import subprocess, tempfile
root = Path(__file__).resolve().parents[2]
source = (root / 'HermesGlasses/ViewModels/HermesSessionViewModel.swift').read_text()
a = source.index('    func ensureCameraSession() async throws {')
b = source.index('    /// Tear down the Lens-owned', a)
code = '''import Foundation
enum Phase { case starting, started, stopped }
enum DeviceSessionError: Error { case unexpectedError(description: String) }
enum HermesCameraError: Error { case timeout }
final class Session {
 var state = Phase.starting
 var stops = 0
 func start() throws {}
 func stop() { stops += 1; state = .stopped }
}
final class Wearables {
 let session = Session()
 func createSession(deviceSelector: Int) throws -> Session { session }
}
final class Camera {
 var configured = false
 func configure(session: Session) { configured = true }
}
@MainActor final class Owner {
 var deviceSession: Session?
 var lensSession: Session?
 let wearables = Wearables()
 let deviceSelector = 0
 let cameraManager = Camera()
 func ensureCameraPermission(interactive: Bool) async -> Bool { true }
''' + source[a:b] + '''}
@main struct Check {
 @MainActor static func main() async throws {
  let cancelled = Owner()
  let task = Task { try await cancelled.ensureCameraSession() }
  try await Task.sleep(nanoseconds: 20_000_000)
  task.cancel()
  do { try await task.value; fatalError("Expected cancellation") }
  catch is CancellationError {}
  precondition(cancelled.wearables.session.stops == 1)
  precondition(cancelled.lensSession == nil)
  precondition(!cancelled.cameraManager.configured)
  let stopped = Owner()
  stopped.wearables.session.state = .stopped
  do { try await stopped.ensureCameraSession(); fatalError("Expected failure") }
  catch is DeviceSessionError {}
  precondition(stopped.wearables.session.stops == 1)
  let success = Owner()
  success.wearables.session.state = .started
  try await success.ensureCameraSession()
  precondition(success.lensSession === success.wearables.session)
  precondition(success.wearables.session.stops == 0)
  precondition(success.cameraManager.configured)
  print("PASS: cancellation and failed startup release session; successful startup retains it")
 }
}
'''
with tempfile.TemporaryDirectory() as directory:
    path = Path(directory)
    (path / 'check.swift').write_text(code)
    subprocess.run(['swiftc', '-parse-as-library', str(path / 'check.swift'), '-o', str(path / 'check')], check=True)
    subprocess.run([str(path / 'check')], check=True)
