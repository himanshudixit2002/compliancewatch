// ComplianceWatch Control: the desktop shell around the control app's web UI.
//
// One window with a WKWebView. The shell starts the local helper (panel_server.py, which the app
// bundle carries) with the checkout's own Python, reads the one hand-off line it prints,
// {"port": ..., "token": ...}, asks the helper for a single-use launch code with that token, and
// shows http://127.0.0.1:<port>/#launch=<code>: the page swaps the code for the token, so no
// token is ever in a URL. Before the helper starts, the shell reads the checkout itself, so a
// macOS question about the folder it is in (Desktop, Documents) comes while the window says so.
//
// Closing the window quits when nothing runs, and asks in a sheet when something does (keep it
// running in the background, the Dock brings the window back, or quit). Quitting (Cmd-Q, the
// window's Quit button) always quits within five seconds: "Quitting…" shows, the helper's
// input closes (it stops by itself), SIGTERM two seconds later, SIGKILL a second after that.
// SIGTERM to the app does the same off the main thread, so a sheet cannot hold it. Nothing waits
// on a reply that has to come through the main queue.
//
// install-app.sh compiles it (no Xcode project):
//   xcrun swiftc -O -swift-version 5 -parse-as-library -o ComplianceWatch ControlApp.swift
//
// The token lives in this process's memory only: it is never written to disk, to a log or into a
// URL.

import AppKit
import WebKit

private let appTitle = "ComplianceWatch Control"
private let slowStartSeconds: TimeInterval = 8
private let handOffSeconds: TimeInterval = 120
private let heartbeatSeconds: TimeInterval = 30
private let runningCheckSeconds: TimeInterval = 1
private let frameName = "ComplianceWatchControlWindow"
private let privacySettings =
    "x-apple.systempreferences:com.apple.preference.security?Privacy_FilesAndFolders"

// MARK: - where things are

/// The checkout the app was built for, the helper it carries, and the Python that runs it.
struct Setup {
    let checkout: URL
    let panel: URL
    let python: URL
    let demo: Bool

    static func load() -> Result<Setup, Problem> {
        let env = ProcessInfo.processInfo.environment
        let bundle = Bundle.main
        let panelPath = env["CW_CONTROL_PANEL_DIR"]
            ?? bundle.resourceURL?.appendingPathComponent("control-panel").path ?? ""
        let checkoutPath = env["CW_CONTROL_PANEL_REPO"]
            ?? (bundle.object(forInfoDictionaryKey: "CWCheckout") as? String) ?? ""
        let demo = CommandLine.arguments.contains("--demo") || env["CW_CONTROL_DEMO"] == "1"
        let files = FileManager.default
        let panel = URL(fileURLWithPath: panelPath, isDirectory: true)
        let server = panel.appendingPathComponent("panel_server.py")
        guard !panelPath.isEmpty, files.fileExists(atPath: server.path) else {
            return .failure(Problem(
                title: "This app is incomplete",
                text: "Its copy of the control app's helper is missing.",
                fix: "Build the app again from your checkout: make control-panel-app.",
                details: "Looked for \(server.path)"))
        }
        let checkout = URL(fileURLWithPath: checkoutPath, isDirectory: true)
        guard !checkoutPath.isEmpty,
              files.fileExists(atPath: checkout.appendingPathComponent("Makefile").path)
        else {
            return .failure(Problem(
                title: "The checkout this app was built for is not there",
                text: "The app controls one ComplianceWatch checkout, and it cannot find it.",
                fix: "Build the app again from your checkout: make control-panel-app.",
                details: "Checkout: \(checkoutPath.isEmpty ? "(none recorded)" : checkoutPath)"))
        }
        let python = checkout.appendingPathComponent(".venv/bin/python")
        guard files.isExecutableFile(atPath: python.path) else {
            return .failure(Problem(
                title: "The checkout has no Python environment yet",
                text: "The control app runs with the checkout's own Python, and it is not set up.",
                fix: "In Terminal, run: cd \(shellQuote(checkout.path)) && uv sync --all-packages. "
                    + "Then press Try again.",
                details: "Looked for \(python.path)"))
        }
        return .success(Setup(checkout: checkout, panel: panel, python: python, demo: demo))
    }
}

/// Something that stops the window from showing the app, in plain words.
struct Problem: Error {
    let title: String
    let text: String
    let fix: String
    let details: String
}

func shellQuote(_ text: String) -> String {
    if text.range(of: "^[A-Za-z0-9_./-]+$", options: .regularExpression) != nil { return text }
    return "'" + text.replacingOccurrences(of: "'", with: "'\\''") + "'"
}

/// The titles of the runs still running, from the body of GET /api/runs.
func runningTitles(_ data: Data?) -> [String] {
    guard let data,
          let body = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
          let runs = body["runs"] as? [[String: Any]]
    else { return [] }
    return runs.filter { $0["state"] as? String == "running" }.compactMap { $0["title"] as? String }
}

func htmlEscape(_ text: String) -> String {
    var out = ""
    for char in text {
        switch char {
        case "&": out += "&amp;"
        case "<": out += "&lt;"
        case ">": out += "&gt;"
        case "\"": out += "&quot;"
        case "'": out += "&#39;"
        default: out.append(char)
        }
    }
    return out
}

// MARK: - the helper process

/// The helper: started with a pipe on its standard input (closing it stops the helper), its
/// hand-off line read from standard output, its standard error kept for the error page and
/// appended to ~/Library/Logs/ComplianceWatch Control/helper.log (it never writes the token).
final class Helper: @unchecked Sendable {  // its mutable state is behind `lock`
    struct HandOff {
        let port: Int
        let token: String
    }

    let setup: Setup
    private let process = Process()
    private let input = Pipe()
    private let output = Pipe()
    private let errors = Pipe()
    private let lock = NSLock()
    private var buffer = Data()
    private var stderrLines: [String] = []
    private var stderrPartial = ""
    private var handedOff = false
    private var stopping = false
    private var inputOpen = true
    private let log = HelperLog()

    /// Called once on the main queue with the hand-off, or a problem.
    var onReady: ((Result<HandOff, Problem>) -> Void)?
    /// Called on the main queue when it has not handed off after `slowStartSeconds`.
    var onSlow: (() -> Void)?
    /// Called on the main queue when the helper exits after it was ready, unless it was asked to.
    var onExit: ((Problem) -> Void)?

    init(setup: Setup) {
        self.setup = setup
    }

    var command: String {
        var parts = [setup.python.path, "-B", setup.panel.appendingPathComponent("panel_server.py").path]
        if setup.demo { parts.append("--demo") }
        return parts.map(shellQuote).joined(separator: " ")
    }

    var pid: Int32 { process.processIdentifier }

    /// The helper process is there (started and not yet gone).
    var isAlive: Bool { process.processIdentifier > 0 && process.isRunning }

    func start() {
        process.executableURL = setup.python
        var arguments = ["-B", setup.panel.appendingPathComponent("panel_server.py").path]
        if setup.demo { arguments.append("--demo") }
        process.arguments = arguments
        process.currentDirectoryURL = setup.checkout
        var env = ProcessInfo.processInfo.environment
        env["CW_CONTROL_PANEL_REPO"] = setup.checkout.path
        env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + (env["PATH"] ?? "/usr/bin:/bin:/usr/sbin:/sbin")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        process.environment = env
        process.standardInput = input
        process.standardOutput = output
        process.standardError = errors
        log.begin(command)

        output.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty {
                handle.readabilityHandler = nil
                return
            }
            self?.received(data)
        }
        errors.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty {
                handle.readabilityHandler = nil
                return
            }
            self?.receivedError(data)
        }
        process.terminationHandler = { [weak self] process in
            let status = process.terminationStatus
            // a moment for its last lines on standard error to arrive before they are shown
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) { self?.exited(status) }
        }
        do {
            try process.run()
        } catch {
            finish(.failure(Problem(
                title: "The control app could not start its helper",
                text: "macOS refused to start the checkout's Python.",
                fix: "Check that the checkout's Python works, then press Try again.",
                details: "\(command)\n\n\(error.localizedDescription)")))
            return
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + slowStartSeconds) { [weak self] in
            guard let self, !self.isHandedOff else { return }
            self.onSlow?()
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + handOffSeconds) { [weak self] in
            guard let self, !self.isHandedOff else { return }
            self.finish(.failure(Problem(
                title: "The control app's helper did not answer",
                text: "It started but did not say it was ready within \(Int(handOffSeconds)) seconds.",
                fix: "Press Try again. If it keeps happening, look at the details.",
                details: self.details())))
            self.stop()
        }
    }

    private var isHandedOff: Bool {
        lock.lock()
        defer { lock.unlock() }
        return handedOff
    }

    private func received(_ data: Data) {
        lock.lock()
        if handedOff {
            lock.unlock()
            return  // the helper prints nothing after its hand-off; anything else is dropped
        }
        buffer.append(data)
        guard let newline = buffer.firstIndex(of: 0x0A) else {
            if buffer.count > 4096 { buffer.removeAll() }
            lock.unlock()
            return
        }
        let line = buffer[buffer.startIndex..<newline]
        buffer.removeAll()
        lock.unlock()
        let parsed = (try? JSONSerialization.jsonObject(with: Data(line))) as? [String: Any]
        let port = parsed?["port"] as? Int ?? 0
        let token = parsed?["token"] as? String ?? ""
        let tokenOK = token.range(of: "^[A-Za-z0-9_-]{16,128}$", options: .regularExpression) != nil
        DispatchQueue.main.async { [weak self] in
            guard let self else { return }
            if (1...65535).contains(port) && tokenOK {
                self.finish(.success(HandOff(port: port, token: token)))
            } else {
                self.finish(.failure(Problem(
                    title: "The control app's helper answered something unexpected",
                    text: "Its first line was not the address the window needs.",
                    fix: "Build the app again from your checkout: make control-panel-app.",
                    details: self.details())))
                self.stop()
            }
        }
    }

    private func receivedError(_ data: Data) {
        log.append(data)
        let text = String(decoding: data, as: UTF8.self)
        lock.lock()
        let pieces = (stderrPartial + text).components(separatedBy: "\n")
        stderrPartial = pieces.last ?? ""
        stderrLines.append(contentsOf: pieces.dropLast())
        if stderrLines.count > 200 { stderrLines.removeFirst(stderrLines.count - 200) }
        lock.unlock()
    }

    /// The command and the helper's last lines on standard error.
    func details() -> String {
        lock.lock()
        var lines = stderrLines
        if !stderrPartial.isEmpty { lines.append(stderrPartial) }
        lock.unlock()
        let tail = lines.suffix(80).joined(separator: "\n")
        return "\(command)\n\n" + (tail.isEmpty ? "(it printed nothing on standard error)" : tail)
            + "\n\nThe full log: \(HelperLog.path)"
    }

    private func finish(_ result: Result<HandOff, Problem>) {
        lock.lock()
        if handedOff {
            lock.unlock()
            return
        }
        handedOff = true
        lock.unlock()
        let callback = onReady
        onReady = nil
        callback?(result)
    }

    private func exited(_ status: Int32) {
        lock.lock()
        let asked = stopping
        lock.unlock()
        if !isHandedOff {
            finish(.failure(Problem(
                title: "The control app's helper stopped as it started",
                text: "It exited (status \(status)) before the window could connect.",
                fix: "Look at the details for the reason, fix it, then press Try again.",
                details: details())))
            return
        }
        if asked { return }
        onExit?(Problem(
            title: "The control app's helper stopped",
            text: "It exited (status \(status)) while the window was open.",
            fix: "Press Try again to start it again.",
            details: details()))
    }

    private func closeInput() {
        lock.lock()
        stopping = true
        let open = inputOpen
        inputOpen = false
        lock.unlock()
        if open { try? input.fileHandleForWriting.close() }
    }

    private func waitGone(_ seconds: TimeInterval) -> Bool {
        let deadline = Date().addingTimeInterval(seconds)
        while isAlive && Date() < deadline { usleep(20_000) }
        return !isAlive
    }

    /// Stops the helper and returns once it is gone, within about 3.5 seconds: its input
    /// closes (it stops by itself), SIGTERM two seconds later, SIGKILL a second after that.
    /// Blocks: call it off the main thread (the SIGTERM path, the quitting thread).
    func stopNow() {
        closeInput()
        let pid = process.processIdentifier
        guard pid > 0, !waitGone(2) else { return }
        kill(pid, SIGTERM)
        guard !waitGone(1) else { return }
        kill(pid, SIGKILL)
        _ = waitGone(0.5)
    }

    /// `stopNow` on a background thread; `done` runs on the main queue after.
    func stop(done: (@MainActor () -> Void)? = nil) {
        closeInput()
        DispatchQueue.global(qos: .userInitiated).async { [self] in
            stopNow()
            if let done { DispatchQueue.main.async { done() } }
        }
    }
}

/// The helper's standard error, appended to ~/Library/Logs/ComplianceWatch Control/helper.log
/// (started afresh past 2 MB): the first place to look when the window says it stopped.
final class HelperLog: @unchecked Sendable {
    static let path = FileManager.default.homeDirectoryForCurrentUser
        .appendingPathComponent("Library/Logs/ComplianceWatch Control/helper.log").path
    private let lock = NSLock()
    private var handle: FileHandle?

    func begin(_ command: String) {
        let files = FileManager.default
        let url = URL(fileURLWithPath: Self.path)
        try? files.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
        if let size = (try? files.attributesOfItem(atPath: url.path))?[.size] as? Int, size > 2_000_000 {
            try? files.removeItem(at: url)
        }
        // O_APPEND: each write lands at the end, even with a second copy of the app writing too
        let fd = open(url.path, O_WRONLY | O_APPEND | O_CREAT | O_CLOEXEC, 0o644)
        lock.lock()
        handle = fd >= 0 ? FileHandle(fileDescriptor: fd, closeOnDealloc: true) : nil
        lock.unlock()
        let stamp = ISO8601DateFormatter().string(from: Date())
        append(Data("--- \(stamp) app pid \(getpid()) starts: \(command)\n".utf8))
    }

    func append(_ data: Data) {
        lock.lock()
        defer { lock.unlock() }
        try? handle?.write(contentsOf: data)
    }
}

/// What the background threads need from the main thread's state: the helper, behind a lock.
final class Shared: @unchecked Sendable {
    private let lock = NSLock()
    private var current: Helper?

    var helper: Helper? {
        get {
            lock.lock()
            defer { lock.unlock() }
            return current
        }
        set {
            lock.lock()
            current = newValue
            lock.unlock()
        }
    }
}

/// Calls `then` once: with the first answer, or with the fallback when `seconds` pass first.
@MainActor
final class Once<Value> {
    private var done = false
    private let then: @MainActor (Value) -> Void

    init(_ then: @escaping @MainActor (Value) -> Void) { self.then = then }

    func callAsFunction(_ value: Value) {
        guard !done else { return }
        done = true
        then(value)
    }
}

// MARK: - the application

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate, WKNavigationDelegate, WKUIDelegate,
    NSWindowDelegate, WKScriptMessageHandler
{
    private var window: NSWindow!
    private var webView: WKWebView!
    private let shared = Shared()
    private var handOff: Helper.HandOff?
    private var heartbeat: DispatchSourceTimer?
    private var reloads = 0
    private var quitting = false
    private var signalSources: [DispatchSourceSignal] = []
    private lazy var session: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.timeoutIntervalForRequest = 2
        config.connectionProxyDictionary = [:]
        return URLSession(configuration: config)
    }()

    private var helper: Helper? {
        get { shared.helper }
        set { shared.helper = newValue }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.mainMenu = makeMenu()
        makeWindow()
        // SIGTERM (a logout, kill), SIGINT and SIGHUP quit without asking, the helper stopped
        // first. Handled off the main thread, which a sheet or a stuck call may be holding.
        let shared = self.shared
        for number in [SIGTERM, SIGINT, SIGHUP] {
            signal(number, SIG_IGN)
            let source = DispatchSource.makeSignalSource(
                signal: number, queue: .global(qos: .userInitiated))
            source.setEventHandler {
                shared.helper?.stopNow()
                _exit(0)  // not exit(): its handlers may want the main thread
            }
            source.resume()
            signalSources.append(source)
        }
        launch()
    }

    // MARK: quitting

    /// Quits: "Quitting…" in the window, the helper stopped (its input closed, SIGTERM two
    /// seconds later, SIGKILL a second after that), then the app, within five seconds whatever
    /// happens: if the main thread cannot finish it, the quitting thread exits the process.
    func quitNow() {
        guard !quitting else { return }
        quitting = true
        stopHeartbeat()
        if let sheet = window.attachedSheet { window.endSheet(sheet) }
        showPage(quittingPage())
        let shared = self.shared
        Thread.detachNewThread {
            shared.helper?.stopNow()
            DispatchQueue.main.async { NSApp.terminate(nil) }
            Thread.sleep(forTimeInterval: 1.0)
            _exit(0)  // the main thread did not get there in time
        }
    }

    /// Cmd-Q, the Dock's Quit, the window's Quit button: always quits, a running task stopped
    /// with it. Never `.terminateLater`: nothing here waits on a reply from the main queue.
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let helper, helper.isAlive else { return .terminateNow }
        if isSystemQuit() {  // logging out, restarting, shutting down: stop the helper and go
            helper.stopNow()
            return .terminateNow
        }
        quitNow()
        return .terminateCancel  // quitNow terminates again once the helper is gone
    }

    private func isSystemQuit() -> Bool {
        guard let event = NSAppleEventManager.shared().currentAppleEvent,
              event.eventClass == kCoreEventClass, event.eventID == kAEQuitApplication,
              let reason = event.attributeDescriptor(forKeyword: kAEQuitReason)?.typeCodeValue
        else { return false }
        return [kAELogOut, kAEReallyLogOut, kAEShowRestartDialog, kAEShowShutdownDialog,
                kAERestart, kAEShutDown].contains(reason)
    }

    func applicationWillTerminate(_ notification: Notification) {
        if let helper, helper.isAlive {
            helper.stopNow()
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }

    /// A click on the Dock icon brings the window back (after "Keep Running in Background").
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
        if !flag || !window.isVisible {
            window.makeKeyAndOrderFront(nil)
        }
        return true
    }

    /// Closing the window: with nothing running the app quits at once; with a task running a
    /// sheet asks whether to keep it running in the background (the Dock brings the window
    /// back) or to quit and stop it. The running check waits one second at most: a helper that
    /// does not answer counts as running nothing.
    func windowShouldClose(_ sender: NSWindow) -> Bool {
        if quitting || window.attachedSheet != nil { return false }
        guard handOff != nil, let helper, helper.isAlive else {
            quitNow()
            return false
        }
        checkRunning { [weak self] running in
            guard let self, !self.quitting else { return }
            if running.isEmpty {
                self.quitNow()
            } else {
                self.askOnClose(running)
            }
        }
        return false
    }

    /// The titles of the runs going now, from GET /api/runs, within `runningCheckSeconds`.
    private func checkRunning(then: @escaping @MainActor ([String]) -> Void) {
        let once = Once<[String]>(then)
        guard var request = apiRequest("GET", "/api/runs?limit=20") else {
            once([])
            return
        }
        request.timeoutInterval = runningCheckSeconds
        session.dataTask(with: request) { data, response, _ in
            let ok = (response as? HTTPURLResponse)?.statusCode == 200
            let running = ok ? runningTitles(data) : []
            DispatchQueue.main.async { once(running) }
        }.resume()
        DispatchQueue.main.asyncAfter(deadline: .now() + runningCheckSeconds) { once([]) }
    }

    private func askOnClose(_ running: [String]) {
        guard window.attachedSheet == nil else { return }
        if window.isMiniaturized { window.deminiaturize(nil) }
        NSApp.activate(ignoringOtherApps: true)
        window.makeKeyAndOrderFront(nil)
        let alert = NSAlert()
        alert.alertStyle = .warning
        alert.messageText = running.count == 1
            ? "\(running[0]) is still running"
            : "\(running.count) tasks are still running"
        alert.informativeText =
            "Keep Running in Background closes this window and lets it finish: click "
            + "ComplianceWatch Control in the Dock to bring the window back. Quit stops it now, "
            + "partway through."
        alert.addButton(withTitle: "Keep Running in Background")
        alert.addButton(withTitle: "Quit and Stop It")
        alert.addButton(withTitle: "Cancel")
        alert.beginSheetModal(for: window) { [weak self] response in
            guard let self else { return }
            switch response {
            case .alertFirstButtonReturn:
                self.window.orderOut(nil)
            case .alertSecondButtonReturn:
                self.quitNow()
            default:
                break
            }
        }
    }

    /// The window's own Quit button (and nothing else) posts here: `cwControl.postMessage("quit")`.
    func userContentController(
        _ userContentController: WKUserContentController, didReceive message: WKScriptMessage
    ) {
        guard message.name == "cwControl", let handOff,
              message.frameInfo.securityOrigin.host == "127.0.0.1",
              message.frameInfo.securityOrigin.port == handOff.port,
              message.body as? String == "quit"
        else { return }
        quitNow()
    }

    func applicationSupportsSecureRestorableState(_ app: NSApplication) -> Bool { true }

    // MARK: window

    private func makeWindow() {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        config.preferences.isElementFullscreenEnabled = false
        config.suppressesIncrementalRendering = false
        config.userContentController.add(self, name: "cwControl")
        webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsBackForwardNavigationGestures = false
        webView.allowsMagnification = true
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 13.3, *) {
            webView.isInspectable = UserDefaults.standard.bool(forKey: "WebInspector")
        }

        window = NSWindow(
            contentRect: NSRect(x: 0, y: 0, width: 1240, height: 820),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false)
        window.title = appTitle
        window.minSize = NSSize(width: 880, height: 580)
        window.backgroundColor = .windowBackgroundColor
        window.contentView = webView
        window.delegate = self
        window.isReleasedWhenClosed = false
        window.tabbingMode = .disallowed
        if !window.setFrameUsingName(frameName) { window.center() }
        window.setFrameAutosaveName(frameName)
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    // MARK: the helper

    private func launch() {
        stopHeartbeat()
        handOff = nil
        showPage(loadingPage())
        switch Setup.load() {
        case .failure(let problem):
            showPage(problemPage(problem))
        case .success(let setup):
            checkAccess(setup) { [weak self] problem in
                guard let self, !self.quitting else { return }
                if let problem {
                    self.showPage(self.problemPage(problem, privacy: true))
                } else {
                    self.startHelper(setup)
                }
            }
        }
    }

    /// Reads the checkout's Makefile off the main thread before the helper starts. When macOS
    /// asks whether the app may use the folder the checkout is in (Desktop, Documents,
    /// Downloads), the question comes now, and the window says what it is waiting for, instead
    /// of the helper stalling unseen while it waits for the answer.
    private func checkAccess(_ setup: Setup, then: @escaping @MainActor (Problem?) -> Void) {
        let makefile = setup.checkout.appendingPathComponent("Makefile").path
        let folder = protectedFolder(setup.checkout)
        let once = Once<Problem?>(then)
        DispatchQueue.global(qos: .userInitiated).async {
            var failure: Int32 = 0
            let fd = open(makefile, O_RDONLY)
            if fd < 0 {
                failure = errno
            } else {
                var byte: UInt8 = 0
                if read(fd, &byte, 1) < 0 { failure = errno }
                close(fd)
            }
            let problem: Problem? = (failure == EPERM || failure == EACCES)
                ? Problem(
                    title: "ComplianceWatch Control may not use your \(folder ?? "checkout's") folder",
                    text: "macOS keeps that folder private, and the app was not allowed to read "
                        + "the checkout in it.",
                    fix: "Open Privacy settings, find ComplianceWatch Control under Files & Folders "
                        + "and turn on \(folder.map { "\($0) Folder" } ?? "its folder"); then press "
                        + "Try again.",
                    details: "\(makefile): \(String(cString: strerror(failure)))")
                : nil
            DispatchQueue.main.async { once(problem) }
        }
        DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { [weak self] in
            guard let self, !self.quitting, self.handOff == nil, self.helper == nil else { return }
            self.showPage(self.permissionPage(folder))
        }
    }

    private func protectedFolder(_ checkout: URL) -> String? {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let path = checkout.standardizedFileURL.path
        for (folder, name) in [("Desktop", "Desktop"), ("Documents", "Documents"),
                               ("Downloads", "Downloads"), ("Library/Mobile Documents", "iCloud Drive")]
        where path.hasPrefix("\(home)/\(folder)/") {
            return name
        }
        return nil
    }

    private func startHelper(_ setup: Setup) {
        showPage(loadingPage())
        let helper = Helper(setup: setup)
        self.helper = helper
        helper.onReady = { [weak self] result in
            self?.helperReady(result)
        }
        helper.onSlow = { [weak self] in
            guard let self, self.handOff == nil, !self.quitting else { return }
            self.showPage(self.loadingPage(slow: true))
        }
        helper.onExit = { [weak self] problem in
            guard let self, !self.quitting else { return }
            self.stopHeartbeat()
            self.handOff = nil
            self.showPage(self.problemPage(problem))
        }
        helper.start()
    }

    private func helperReady(_ result: Result<Helper.HandOff, Problem>) {
        switch result {
        case .failure(let problem):
            showPage(problemPage(problem))
        case .success(let handOff):
            self.handOff = handOff
            openPage(view: nil)
            startHeartbeat()
        }
    }

    /// The helper stops when the app closes its input; while the app runs it stays up. The
    /// heartbeat is for the helper's own clock, on a background timer that a hidden window or
    /// a sheet cannot pause.
    private func startHeartbeat() {
        stopHeartbeat()
        guard let request = apiRequest("POST", "/api/heartbeat") else { return }
        let session = self.session
        let timer = DispatchSource.makeTimerSource(queue: .global(qos: .utility))
        timer.schedule(
            deadline: .now() + heartbeatSeconds, repeating: heartbeatSeconds, leeway: .seconds(5))
        timer.setEventHandler { session.dataTask(with: request).resume() }
        timer.resume()
        heartbeat = timer
    }

    private func stopHeartbeat() {
        heartbeat?.cancel()
        heartbeat = nil
    }

    /// Loads the window's page with a fresh single-use launch code (``POST /api/launch-code``
    /// with the token): the page swaps the code for the token, so the token is in no URL.
    private func openPage(view: String?) {
        guard let request = apiRequest("POST", "/api/launch-code") else { return }
        session.dataTask(with: request) { [weak self] data, response, error in
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            let body = data.flatMap { try? JSONSerialization.jsonObject(with: $0) as? [String: Any] }
            let code = body?["code"] as? String ?? ""
            let detail = error?.localizedDescription ?? "status \(status)"
            DispatchQueue.main.async {
                guard let self, !self.quitting else { return }
                guard status == 200, let url = self.appURL(code: code, view: view) else {
                    self.showPage(self.problemPage(Problem(
                        title: "The window could not be opened",
                        text: "The helper did not give the window its one-time link.",
                        fix: "Press Try again.",
                        details: detail)))
                    return
                }
                self.webView.load(URLRequest(url: url))
            }
        }.resume()
    }

    /// The window's address: the helper's page with the launch code in the fragment (never sent
    /// to the server), and the view to open. `r` makes a reload a real navigation.
    private func appURL(code: String, view: String?) -> URL? {
        guard let handOff,
              code.range(of: "^l-[A-Za-z0-9_-]{8,128}$", options: .regularExpression) != nil
        else { return nil }
        var fragment = "launch=\(code)"
        if let view, view.range(of: "^[a-z0-9/_-]{1,64}$", options: .regularExpression) != nil {
            fragment += "&view=\(view)"
        }
        let query = reloads > 0 ? "?r=\(reloads)" : ""
        return URL(string: "http://127.0.0.1:\(handOff.port)/\(query)#\(fragment)")
    }

    private func isHelperPage(_ url: URL) -> Bool {
        guard let handOff else { return false }
        return url.scheme == "http" && url.host == "127.0.0.1" && url.port == handOff.port
    }

    private func apiRequest(_ method: String, _ path: String) -> URLRequest? {
        guard let handOff, let url = URL(string: "http://127.0.0.1:\(handOff.port)\(path)") else {
            return nil
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.setValue(handOff.token, forHTTPHeaderField: "X-Panel-Token")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        return request
    }

    // MARK: navigation

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping @MainActor (WKNavigationActionPolicy) -> Void
    ) {
        guard let url = navigationAction.request.url else {
            decisionHandler(.cancel)
            return
        }
        if url.scheme == "cw-control" {
            decisionHandler(.cancel)
            switch url.absoluteString {
            case "cw-control:retry": retry()
            case "cw-control:quit": quitNow()
            case "cw-control:privacy":
                if let settings = URL(string: privacySettings) { NSWorkspace.shared.open(settings) }
            default: break
            }
            return
        }
        if url.scheme == "about" || isHelperPage(url) {
            decisionHandler(.allow)
            return
        }
        decisionHandler(.cancel)
        if ["http", "https", "mailto"].contains(url.scheme ?? "") {
            NSWorkspace.shared.open(url)  // every other address opens in the default browser
        }
    }

    func webView(
        _ webView: WKWebView,
        createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction,
        windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        if let url = navigationAction.request.url, ["http", "https", "mailto"].contains(url.scheme ?? "") {
            NSWorkspace.shared.open(url)
        }
        return nil
    }

    func webView(
        _ webView: WKWebView,
        runJavaScriptAlertPanelWithMessage message: String,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping @MainActor () -> Void
    ) {
        guard window.attachedSheet == nil else {
            completionHandler()
            return
        }
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "OK")
        alert.beginSheetModal(for: window) { _ in completionHandler() }
    }

    func webView(
        _ webView: WKWebView,
        runJavaScriptConfirmPanelWithMessage message: String,
        initiatedByFrame frame: WKFrameInfo,
        completionHandler: @escaping @MainActor (Bool) -> Void
    ) {
        guard window.attachedSheet == nil else {
            completionHandler(false)
            return
        }
        let alert = NSAlert()
        alert.messageText = message
        alert.addButton(withTitle: "OK")
        alert.addButton(withTitle: "Cancel")
        alert.beginSheetModal(for: window) { completionHandler($0 == .alertFirstButtonReturn) }
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        if !quitting { reload(nil) }  // the page's process crashed: load it again, same helper
    }

    // MARK: menu actions

    @objc func reload(_ sender: Any?) {
        guard !quitting else { return }
        guard handOff != nil else {
            retry()
            return
        }
        var view: String?
        if let current = webView.url, isHelperPage(current), let fragment = current.fragment,
           fragment.hasPrefix("/")
        {
            view = String(fragment.dropFirst())
        }
        reloads += 1
        openPage(view: view)
    }

    @objc func retry() {
        guard !quitting else { return }
        let old = helper
        helper = nil
        handOff = nil
        stopHeartbeat()
        showPage(loadingPage())
        if let old, old.isAlive {
            old.stop { [weak self] in self?.launch() }
        } else {
            launch()
        }
    }

    @objc func showGuide(_ sender: Any?) {
        guard handOff != nil else { return }
        webView.evaluateJavaScript("window.location.hash = '#/guide'", completionHandler: nil)
    }

    @objc func zoomIn(_ sender: Any?) { webView.pageZoom = min(webView.pageZoom + 0.1, 2.0) }
    @objc func zoomOut(_ sender: Any?) { webView.pageZoom = max(webView.pageZoom - 0.1, 0.6) }
    @objc func actualSize(_ sender: Any?) { webView.pageZoom = 1.0 }

    @objc func about(_ sender: Any?) {
        var lines: [String] = []
        if let setup = helper?.setup {
            let build = readBuild(setup.panel)
            if let built = build["built"] {
                lines.append("Built \(built) from \(build["commit"] ?? "an unknown commit").")
            }
            lines.append("Controls \(setup.checkout.path)")
            if setup.demo { lines.append("Demo mode: canned data, nothing real runs.") }
        }
        let credits = NSAttributedString(
            string: lines.joined(separator: "\n"),
            attributes: [
                .font: NSFont.systemFont(ofSize: NSFont.smallSystemFontSize),
                .foregroundColor: NSColor.secondaryLabelColor,
            ])
        NSApp.orderFrontStandardAboutPanel(options: [
            .applicationName: appTitle,
            .applicationVersion: "2",
            .credits: credits,
        ])
        NSApp.activate(ignoringOtherApps: true)
    }

    private func readBuild(_ panel: URL) -> [String: String] {
        guard let text = try? String(contentsOf: panel.appendingPathComponent("BUILD"), encoding: .utf8)
        else { return [:] }
        var out: [String: String] = [:]
        for line in text.split(separator: "\n") {
            let parts = line.split(separator: "=", maxSplits: 1)
            if parts.count == 2 { out[String(parts[0])] = String(parts[1]) }
        }
        return out
    }

    private func makeMenu() -> NSMenu {
        let main = NSMenu()

        func submenu(_ title: String, _ items: [NSMenuItem]) {
            let holder = NSMenuItem(title: title, action: nil, keyEquivalent: "")
            let menu = NSMenu(title: title)
            items.forEach(menu.addItem)
            holder.submenu = menu
            main.addItem(holder)
        }
        func item(
            _ title: String, _ action: Selector?, _ key: String = "",
            _ modifiers: NSEvent.ModifierFlags = .command, target: AnyObject? = nil
        ) -> NSMenuItem {
            let item = NSMenuItem(title: title, action: action, keyEquivalent: key)
            item.keyEquivalentModifierMask = modifiers
            item.target = target
            return item
        }

        submenu(appTitle, [
            item("About \(appTitle)", #selector(about(_:)), target: self),
            .separator(),
            item("Hide \(appTitle)", #selector(NSApplication.hide(_:)), "h"),
            item("Hide Others", #selector(NSApplication.hideOtherApplications(_:)), "h", [.command, .option]),
            item("Show All", #selector(NSApplication.unhideAllApplications(_:))),
            .separator(),
            item("Quit \(appTitle)", #selector(NSApplication.terminate(_:)), "q"),
        ])
        submenu("Edit", [
            item("Undo", Selector(("undo:")), "z"),
            item("Redo", Selector(("redo:")), "z", [.command, .shift]),
            .separator(),
            item("Cut", #selector(NSText.cut(_:)), "x"),
            item("Copy", #selector(NSText.copy(_:)), "c"),
            item("Paste", #selector(NSText.paste(_:)), "v"),
            item("Select All", #selector(NSText.selectAll(_:)), "a"),
        ])
        submenu("View", [
            item("Reload", #selector(reload(_:)), "r", target: self),
            .separator(),
            item("Actual Size", #selector(actualSize(_:)), "0", target: self),
            item("Zoom In", #selector(zoomIn(_:)), "+", target: self),
            item("Zoom Out", #selector(zoomOut(_:)), "-", target: self),
            .separator(),
            item("Enter Full Screen", #selector(NSWindow.toggleFullScreen(_:)), "f", [.command, .control]),
        ])
        let windowItems = [
            item("Minimize", #selector(NSWindow.performMiniaturize(_:)), "m"),
            item("Zoom", #selector(NSWindow.performZoom(_:))),
            .separator(),
            item("Close", #selector(NSWindow.performClose(_:)), "w"),
        ]
        submenu("Window", windowItems)
        submenu("Help", [item("\(appTitle) Guide", #selector(showGuide(_:)), "?", target: self)])
        if let windowMenu = main.item(withTitle: "Window")?.submenu { NSApp.windowsMenu = windowMenu }
        return main
    }

    // MARK: pages the shell shows itself

    private func showPage(_ html: String) {
        webView.loadHTMLString(html, baseURL: nil)
    }

    private static let pageStyle = """
        :root { color-scheme: light dark; --bg: #f6f6f7; --card: #ffffff; --text: #171717;
          --muted: #5b5b66; --line: #e4e4e7; --accent: #1d4ed8; --accent-fg: #ffffff; }
        @media (prefers-color-scheme: dark) { :root { --bg: #111113; --card: #1c1c1f;
          --text: #f4f4f5; --muted: #a1a1aa; --line: #2e2e33; --accent: #8ab4ff; --accent-fg: #0b1220; } }
        * { box-sizing: border-box; }
        html, body { margin: 0; height: 100%; background: var(--bg); color: var(--text);
          font: 14px/1.5 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Helvetica Neue", sans-serif; }
        main { min-height: 100%; display: grid; place-items: center; padding: 32px; }
        .card { max-width: 620px; width: 100%; background: var(--card); border: 1px solid var(--line);
          border-radius: 14px; padding: 28px 32px; box-shadow: 0 8px 30px rgba(0,0,0,.08); }
        .mark { width: 40px; height: 40px; margin-bottom: 16px; }
        .mark svg { display: block; border-radius: 9px; }
        h1 { font-size: 20px; margin: 0 0 8px; letter-spacing: -0.01em; }
        p { margin: 0 0 12px; color: var(--muted); }
        p.fix { color: var(--text); }
        .button { display: inline-block; margin-top: 8px; padding: 8px 16px; border-radius: 8px;
          background: var(--accent); color: var(--accent-fg); text-decoration: none; font-weight: 600; }
        .button.secondary { background: transparent; color: var(--accent);
          box-shadow: inset 0 0 0 1px var(--line); }
        .button.quiet { background: transparent; color: var(--muted); }
        .button:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
        details { margin-top: 18px; border-top: 1px solid var(--line); padding-top: 12px; }
        summary { cursor: pointer; color: var(--muted); }
        pre { white-space: pre-wrap; word-break: break-word; font: 12px/1.45 ui-monospace, Menlo, monospace;
          background: var(--bg); border: 1px solid var(--line); border-radius: 8px; padding: 12px;
          max-height: 320px; overflow: auto; user-select: text; }
        .spinner { width: 22px; height: 22px; border-radius: 50%; border: 3px solid var(--line);
          border-top-color: var(--accent); animation: spin .9s linear infinite; margin-bottom: 16px; }
        @keyframes spin { to { transform: rotate(360deg); } }
        @media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }
        """

    /// The ComplianceWatch Control mark (ui/icon.svg): a white shield with a tick on the brand's
    /// blue-to-teal square.
    private static let markSVG = """
        <svg width="40" height="40" viewBox="0 0 64 64" aria-hidden="true"><defs>\
        <linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#2563eb"/>\
        <stop offset="1" stop-color="#0f766e"/></linearGradient></defs>\
        <rect width="64" height="64" rx="14.5" fill="url(#g)"/>\
        <path d="M32 10.5 48.5 16.2V31c0 10.6-6.9 18.5-16.5 22.3C22.4 49.5 15.5 41.6 15.5 31V16.2z" \
        fill="#fff"/><path d="m24.2 31.6 5.9 5.9 10-11.8" fill="none" stroke="#1d4ed8" \
        stroke-width="4.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        """

    private func card(_ body: String, role: String = "status") -> String {
        """
        <!doctype html><html lang="en"><head><meta charset="utf-8"><title>\(appTitle)</title>
        <style>\(Self.pageStyle)</style></head><body><main><div class="card" role="\(role)">
        \(body)
        </div></main></body></html>
        """
    }

    private func loadingPage(slow: Bool = false) -> String {
        if slow {
            return card("""
                <div class="spinner"></div><h1>Still starting…</h1>
                <p>The first start after an update can take a little longer.</p>
                <p class="fix">If macOS shows a question about your files or folders, answer it: \
                ComplianceWatch Control waits for it.</p>
                """)
        }
        return card("""
            <div class="spinner"></div><h1>Starting \(appTitle)…</h1>
            <p>It reads what is running in your checkout. This takes a second or two.</p>
            """)
    }

    private func permissionPage(_ folder: String?) -> String {
        let place = folder.map { "your \($0) folder" } ?? "the folder your checkout is in"
        return card("""
            <div class="mark">\(Self.markSVG)</div>
            <h1>Waiting for macOS</h1>
            <p>Your checkout is in \(htmlEscape(place)), which macOS keeps private. It is asking \
            whether ComplianceWatch Control may use files there.</p>
            <p class="fix">Click <strong>Allow</strong> in the macOS dialog. If you do not see \
            it, look behind this window.</p>
            <a class="button" href="cw-control:privacy">Open Privacy settings</a>
            """)
    }

    private func quittingPage() -> String {
        card("""
            <div class="spinner"></div><h1>Quitting…</h1>
            <p>Stopping the helper and anything it runs. This takes a few seconds at most.</p>
            """)
    }

    private func problemPage(_ problem: Problem, privacy: Bool = false) -> String {
        let settings = privacy
            ? #"<a class="button secondary" href="cw-control:privacy">Open Privacy settings</a> "#
            : ""
        return card("""
            <div class="mark">\(Self.markSVG)</div>
            <h1>\(htmlEscape(problem.title))</h1>
            <p>\(htmlEscape(problem.text))</p>
            <p class="fix">\(htmlEscape(problem.fix))</p>
            \(settings)<a class="button" href="cw-control:retry">Try again</a> \
            <a class="button quiet" href="cw-control:quit">Quit</a>
            <details><summary>Show details</summary><pre>\(htmlEscape(problem.details))</pre></details>
            """, role: "alert")
    }
}

@main
enum ControlApp {
    @MainActor private static var delegate: AppDelegate?

    @MainActor static func main() {
        let app = NSApplication.shared
        app.setActivationPolicy(.regular)
        let delegate = AppDelegate()
        Self.delegate = delegate
        app.delegate = delegate
        app.run()
    }
}
