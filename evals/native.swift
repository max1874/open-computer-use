// Acceptance-only ownership and activation events; never executes agent actions.
import AppKit
import ApplicationServices
import Carbon

func emit(_ value: [String: Any]) {
    var row = value; row["time"] = Date().timeIntervalSince1970
    let data = try! JSONSerialization.data(withJSONObject: row, options: [.sortedKeys])
    FileHandle.standardOutput.write(data + Data("\n".utf8))
}
func script(_ text: String) throws -> NSAppleEventDescriptor {
    var error: NSDictionary?
    let result = NSAppleScript(source: "with timeout of 3 seconds\n" + text + "\nend timeout")!.executeAndReturnError(&error)
    if let error { throw NSError(domain: "Acceptance", code: 1, userInfo: error as? [String: Any]) }
    return result
}
let config = try JSONSerialization.jsonObject(with: Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))) as! [String: String]
let bundle = config["bundle"]!
let center = NSWorkspace.shared.notificationCenter
let token = center.addObserver(forName: NSWorkspace.didActivateApplicationNotification, object: nil, queue: nil) { note in
    guard let app = note.userInfo?[NSWorkspace.applicationUserInfoKey] as? NSRunningApplication else { return }
    emit(["event": "activated", "pid": Int(app.processIdentifier), "bundle": app.bundleIdentifier ?? ""])
}
emit(["event": "ready", "frontmost_pid": Int(NSWorkspace.shared.frontmostApplication?.processIdentifier ?? 0)])
enum ProcessState: Equatable { case gone, running(String), unknown }
func processState(_ pid: pid_t) -> ProcessState {
    var info = proc_bsdinfo()
    let size = Int32(MemoryLayout<proc_bsdinfo>.size)
    if proc_pidinfo(pid, PROC_PIDTBSDINFO, 0, &info, size) == size {
        if info.pbi_status == SZOMB { return .gone }
        return .running("\(pid):\(info.pbi_start_tvsec):\(info.pbi_start_tvusec)")
    }
    return kill(pid, 0) == -1 && errno == ESRCH ? .gone : .unknown
}
var owned: (app: NSRunningApplication, instance: ProcessState)?
var finderWindow: Int32?
var finished = false
var closing = false
var opening = false
var closeRequested = false
func closeOwned() {
    if opening { closeRequested = true; return }
    guard !closing else { return }; closing = true
    var cleaned = true
    if let window = finderWindow {
        do {
            let target = try script("tell application \"Finder\" to get POSIX path of (target of Finder window id \(window) as alias)")
            emit(["event": "finder_result", "target": target.stringValue ?? ""])
        } catch { emit(["event": "error", "detail": String(describing: error)]) }
        do {
            // Result-reading failure must not skip closing the owned window.
            let result = try script("tell application \"Finder\"\nif exists Finder window id \(window) then close Finder window id \(window)\nreturn exists Finder window id \(window)\nend tell")
            cleaned = !result.booleanValue
        } catch { cleaned = false; emit(["event": "error", "detail": String(describing: error)]) }
    }
    if let target = owned {
        let pid = target.app.processIdentifier
        // Read the kernel, not NSRunningApplication's cached termination flag.
        // Match the launch instance again before either signal; never kill a reused PID.
        func ended() -> Bool {
            let state = processState(pid)
            return state != .unknown && state != target.instance
        }
        // An exiting process can briefly be unreadable while kill(pid, 0)
        // still succeeds. Wait for proof of exit; unknown is not a new target.
        if processState(pid) == target.instance { kill(pid, SIGTERM) }
        let deadline = Date(timeIntervalSinceNow: 2)
        while !ended(), Date() < deadline { RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.02)) }
        if processState(pid) == target.instance { kill(pid, SIGKILL) }
        let finalDeadline = Date(timeIntervalSinceNow: 2)
        while !ended(), Date() < finalDeadline { RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.02)) }
        cleaned = ended()
        emit(["event": "released", "pid": Int(pid), "kernel_gone": processState(pid) == .gone])
    }
    // Keep observing through teardown and its queued workspace notifications.
    let drained = Date(timeIntervalSinceNow: 0.15)
    while Date() < drained { RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.02)) }
    center.removeObserver(token)
    emit(["event": "stopped", "cleaned": cleaned]); finished = true
}
let existing = NSRunningApplication.runningApplications(withBundleIdentifier: bundle)
if bundle == "com.apple.finder" {
    let target = NSAppleEventDescriptor(bundleIdentifier: bundle)
    let permission = AEDeterminePermissionToAutomateTarget(target.aeDesc, typeWildCard, typeWildCard, false)
    if permission != noErr { emit(["event": "unavailable", "detail": "Finder automation permission is unavailable"]); closeOwned() }
    else if let app = existing.first {
        var raw: CFTypeRef?
        let status = AXUIElementCopyAttributeValue(AXUIElementCreateApplication(app.processIdentifier), kAXWindowsAttribute as CFString, &raw)
        let windows = raw as? [AXUIElement] ?? []
        // The model sees all windows of one app. Do not expose a user's other
        // Finder windows as possible targets while evaluating our own folder.
        let hasWindows = windows.contains { window in
            var role: CFTypeRef?
            AXUIElementCopyAttributeValue(window, kAXRoleAttribute as CFString, &role)
            return role as? String != kAXScrollAreaRole
        }
        if status != .success || hasWindows { emit(["event": "unavailable", "detail": "Finder has existing windows or unreadable ownership"]); closeOwned() }
        else {
            do {
                let path = config["folder"]!.replacingOccurrences(of: "\\", with: "\\\\").replacingOccurrences(of: "\"", with: "\\\"")
                finderWindow = try script("tell application \"Finder\"\nset w to make new Finder window to (POSIX file \"\(path)\")\nset current view of w to list view\nreturn id of w\nend tell").int32Value
                let target = try script("tell application \"Finder\" to get POSIX path of (target of Finder window id \(finderWindow!) as alias)")
                emit(["event": "leased", "pid": Int(app.processIdentifier), "target": target.stringValue ?? ""])
            } catch { emit(["event": "error", "detail": String(describing: error)]); closeOwned() }
        }
    } else { emit(["event": "unavailable", "detail": "Finder is not running"]); closeOwned() }
} else if !existing.isEmpty {
    emit(["event": "unavailable", "detail": "Target application is already running; user instances are preserved"]); closeOwned()
} else if let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: bundle) {
    let configuration = NSWorkspace.OpenConfiguration()
    configuration.activates = false
    configuration.createsNewApplicationInstance = true
    configuration.arguments = ["-ApplePersistenceIgnoreState", "YES", "-NSShowAppCentricOpenPanelInsteadOfUntitledFile", "NO"]
    let existingPIDs = Set(NSWorkspace.shared.runningApplications.map { $0.processIdentifier })
    opening = true
    let opened: (NSRunningApplication?, Error?) -> Void = { app, error in
        DispatchQueue.main.async {
            opening = false
            guard let app, !existingPIDs.contains(app.processIdentifier) else {
                emit(["event": "error", "detail": error.map(String.init(describing:)) ?? "No owned instance was created"]); closeOwned(); return
            }
            let instance = processState(app.processIdentifier)
            guard case .running = instance else {
                emit(["event": "error", "detail": "Created process identity is unavailable"]); closeOwned(); return
            }
            owned = (app, instance)
            if closeRequested { closeOwned() }
            else { emit(["event": "leased", "pid": Int(app.processIdentifier)]) }
        }
    }
    if let document = config["url"], let documentURL = URL(string: document) {
        NSWorkspace.shared.open([documentURL], withApplicationAt: url, configuration: configuration, completionHandler: opened)
    } else { NSWorkspace.shared.openApplication(at: url, configuration: configuration, completionHandler: opened) }
} else { emit(["event": "unavailable", "detail": "Target application is not installed"]); closeOwned() }
DispatchQueue.global().async {
    _ = FileHandle.standardInput.readDataToEndOfFile()
    DispatchQueue.main.async { closeOwned() }
}
let deadline = Date(timeIntervalSinceNow: 240)
var expired = false
while !finished {
    if !expired, Date() >= deadline {
        expired = true; emit(["event": "error", "detail": "Acceptance lease expired"]); closeOwned()
    }
    RunLoop.current.run(until: Date(timeIntervalSinceNow: 0.02))
}
