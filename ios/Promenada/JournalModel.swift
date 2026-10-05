import Foundation
import SwiftUI
import WebKit

@MainActor
final class JournalModel: NSObject, ObservableObject, WKScriptMessageHandler, WKNavigationDelegate, WKUIDelegate {
    @Published var open = false
    @Published var busy = true
    @Published var error = ""
    @Published var confirmForget = false
    @Published var attachment: ShareItem?
    private weak var web: WKWebView?
    private let store: ReportStore
    override init() { store = ReportStore(); super.init() }
    #if DEBUG
    init(testStore: ReportStore) { store = testStore; super.init() }
    func testInstallAccess(_ access: JournalAccess) { self.access = access; ready = true; open = true; busy = false }
    func testReceiveAttachment(_ body: [String: Any]) { openAttachment(body) }
    func testPendingAttachment() -> Task<Void, Never>? { attachmentTask }
    #endif
    private var lastCheck = Date.distantPast
    private var generation = 0
    private var ready = false
    private var forgetting = false
    private var sharingURL: URL?
    private let webRoot = Bundle.main.resourceURL!.appendingPathComponent("Web", isDirectory: true)
    private var access: JournalAccess?
    private var refreshConfig: RefreshConfiguration?
    private var refreshTask: Task<Void, Never>?
    private var unlockTask: Task<Void, Never>?
    private var attachmentTask: Task<Void, Never>?
    private var attachmentGeneration = 0
    private var reviewKey: String { access?.role == "student" ? "mahbrus-review-student-" + access!.principal : "promenada-review-v1" }

    func makeWebView() -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .nonPersistent()
        config.userContentController.add(self, name: "journal")
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--reset-test-access") {
            AccessKey.remove()
            UserDefaults.standard.removeObject(forKey: reviewKey)
        }
        #endif
        let shareDirectory = FileManager.default.temporaryDirectory.appendingPathComponent("PromenadaShare", isDirectory: true)
        try? FileManager.default.removeItem(at: shareDirectory)
        let view = WKWebView(frame: .zero, configuration: config)
        view.navigationDelegate = self
        view.uiDelegate = self
        view.isOpaque = false
        view.backgroundColor = UIColor(red: 1, green: 0.882, blue: 0.922, alpha: 1)
        view.scrollView.backgroundColor = view.backgroundColor
        view.scrollView.contentInsetAdjustmentBehavior = .never
        view.allowsLinkPreview = false
        web = view
        view.loadFileURL(webRoot.appendingPathComponent("index.html"), allowingReadAccessTo: webRoot)
        return view
    }
    private func trusted(_ url: URL?) -> Bool {
        guard let url else { return false }
        return url.isFileURL && url.standardizedFileURL.path.hasPrefix(webRoot.standardizedFileURL.path + "/")
    }
    func userContentController(_ controller: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.frameInfo.isMainFrame, trusted(message.frameInfo.request.url),
              let body = message.body as? [String: Any], let action = body["action"] as? String else { return }
        switch action {
        case "ready":
            guard !ready else { return }; ready = true
            if let saved = AccessKey.read() { unlock(JournalAccess.restore(saved), automatic: true) } else { busy = false }
        case "refresh": requestRefresh()
        case "published": if let access { unlock(access, refreshing: true) }
        case "forget": confirmForget = true
        case "review":
            if let value = body["value"] as? String, value.utf8.count < 1_000_000,
               let bytes = value.data(using: .utf8),
               (try? JSONSerialization.jsonObject(with: bytes)) is [String: Any] {
                UserDefaults.standard.set(value, forKey: reviewKey)
            }
        case "attachment": openAttachment(body)
        default: break
        }
    }
    private func openAttachment(_ body: [String: Any]) {
        guard open, !busy, let access else { return }
        cancelAttachmentLoad()
        if body["ref"] != nil || body["scope"] != nil {
            do {
                let request = try NativeAttachmentRequest.parse(body)
                let requestGeneration = generation, requestAttachmentGeneration = attachmentGeneration
                sendStatus("Otwieram załącznik…")
                attachmentTask = Task {
                    do {
                        let result = try await store.attachment(request, access: access)
                        try Task.checkCancellation()
                        guard generation == requestGeneration, attachmentGeneration == requestAttachmentGeneration,
                              self.access == access, open else { return }
                        try share(result.bytes, name: result.name)
                        sendStatus("")
                    } catch {
                        guard !Task.isCancelled, generation == requestGeneration,
                              attachmentGeneration == requestAttachmentGeneration else { return }
                        sendStatus("Nie udało się otworzyć załącznika. Bez internetu dostępne są tylko wcześniej otwarte załączniki.")
                    }
                }
            } catch { sendStatus("Załącznik ma nieprawidłowy format. Wczytaj raport ponownie.") }
        } else {
            // Keep schema1 / existing native-bridge sharing compatible.
            guard let filename = body["name"] as? String,
                  let base64 = body["base64"] as? String,
                  base64.utf8.count <= ((EncryptedAttachment.maximumPlaintext + 2) / 3) * 4,
                  let bytes = Data(base64Encoded: base64), bytes.count <= EncryptedAttachment.maximumPlaintext else { return }
            do { try share(bytes, name: filename) }
            catch { sendStatus("Nie udało się otworzyć załącznika. Spróbuj ponownie.") }
        }
    }
    func unlock(_ credentials: JournalAccess, refreshing: Bool = false, automatic: Bool = false) {
        guard ready, !forgetting, !credentials.password.isEmpty, !busy || !open else { return }
        unlockTask?.cancel()
        cancelAttachmentLoad()
        generation += 1
        busy = true; error = ""
        let requestGeneration = generation
        unlockTask = Task {
            do {
                // Show the last validated encrypted snapshot immediately on a remembered login.
                if automatic, !open, let cached = try? await store.cached(access: credentials) {
                    guard generation == requestGeneration else { return }
                    access = credentials
                    try await present(cached, status: "Sprawdzam dostępność nowszego raportu…", automatic: false)
                    guard generation == requestGeneration, !Task.isCancelled else { return }
                    open = true
                }
                let result = try await store.load(access: credentials)
                guard generation == requestGeneration else { return }
                try AccessKey.save(credentials.encoded)
                access = credentials
                if let bytes = result.text.data(using: .utf8), let report = try? JSONSerialization.jsonObject(with: bytes) as? [String: Any], let config = report["refresh"], let json = try? JSONSerialization.data(withJSONObject: config) {
                    refreshConfig = try? JSONDecoder().decode(RefreshConfiguration.self, from: json)
                } else { refreshConfig = nil }
                let message = result.offline ? "Bez połączenia z serwerem. Pokazuję ostatni zapisany raport." : ""
                try await present(result.text, status: message, automatic: automatic)
                guard generation == requestGeneration, !Task.isCancelled else { return }
                open = true; lastCheck = Date()
            } catch {
                guard generation == requestGeneration else { return }
                if open { sendStatus("Nie udało się odświeżyć raportu. Oglądasz ostatnio otwartą wersję.") }
                else { self.error = error.localizedDescription }
            }
            if generation == requestGeneration { busy = false; sendBusy(false) }
        }
    }
    private func present(_ text: String, status: String, automatic: Bool) async throws {
        cancelAttachmentLoad()
        let review = UserDefaults.standard.string(forKey: reviewKey) ?? "{\"read\":{},\"done\":{},\"priority\":{}}"
        _ = try await web?.callAsyncJavaScript(
            "window.promenadaReceive(JSON.parse(report), status, JSON.parse(review), automatic);",
            arguments: ["report": text, "status": status, "review": review, "automatic": automatic],
            in: nil, contentWorld: .page)
    }
    func foreground() {
        // Downloads only the already published file. Never dispatches a Librus collection.
        var interval: TimeInterval = 30
        #if DEBUG
        if ProcessInfo.processInfo.environment["PROMENADA_TEST_NEXT_REPORT"] != nil { interval = 0 }
        #endif
        guard ready, open, !busy, attachment == nil, let access,
              Date().timeIntervalSince(lastCheck) >= interval else { return }
        unlock(access, refreshing: true, automatic: true)
    }
    private func requestRefresh() {
        guard !busy, let access else { return }
        guard let refreshConfig else {
            sendStatus("Uruchamianie odczytu nie jest jeszcze skonfigurowane. Przycisk „Wczytaj raport” pobierze ostatnią publikację."); return
        }
        busy = true; sendBusy(true)
        let requestGeneration = generation
        refreshTask = Task {
            do {
                var state = try await refreshConfig.request(start: true)
                guard requestGeneration == generation else { return }
                sendStatus(state.message)
                let deadline = Date().addingTimeInterval(12 * 60)
                while state.pending && Date() < deadline {
                    try await Task.sleep(for: .seconds(8))
                    try Task.checkCancellation()
                    state = try await refreshConfig.request(start: false, run: state.run)
                    guard requestGeneration == generation else { return }
                    sendStatus(state.message)
                }
                guard requestGeneration == generation else { return }
                busy = false
                if state.state == "complete" || state.state == "cooldown" { unlock(access, refreshing: true) }
                else { sendStatus(state.pending ? "Odczyt nadal trwa. Wczytaj raport za chwilę." : state.message); sendBusy(false) }
            } catch {
                guard requestGeneration == generation else { return }
                busy = false; sendStatus("Nie udało się sprawdzić odczytu. Jeśli już wystartował, dokończy się na serwerze. Wczytaj raport za chwilę."); sendBusy(false)
            }
        }
    }
    func forget() {
        guard !forgetting else { return }
        forgetting = true
        generation += 1
        refreshTask?.cancel(); refreshTask = nil
        unlockTask?.cancel(); unlockTask = nil
        cancelAttachmentLoad()
        AccessKey.remove()
        UserDefaults.standard.removeObject(forKey: reviewKey)
        access = nil; refreshConfig = nil
        open = false; busy = true; error = ""
        let forgetGeneration = generation
        Task {
            await store.clear()
            forgetting = false
            if generation == forgetGeneration { busy = false }
        }
        removeShare()
        web?.evaluateJavaScript("window.promenadaClear()")
    }
    private func sendStatus(_ text: String) {
        web?.callAsyncJavaScript("document.getElementById('sync-status').textContent = text; ", arguments: ["text": text], in: nil, in: .page, completionHandler: nil)
    }
    private func sendBusy(_ value: Bool) {
        web?.callAsyncJavaScript("document.getElementById('refresh').disabled = value; document.getElementById('refresh').textContent = value ? 'Sprawdzam…' : 'Odśwież z Librusa';", arguments: ["value": value], in: nil, in: .page, completionHandler: nil)
    }
    private func cancelAttachmentLoad() {
        attachmentGeneration += 1
        attachmentTask?.cancel(); attachmentTask = nil
    }
    private func share(_ bytes: Data, name: String) throws {
        removeShare()
        let dir = FileManager.default.temporaryDirectory.appendingPathComponent("PromenadaShare", isDirectory: true)
        try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true,
                                                attributes: [.protectionKey: FileProtectionType.complete])
        try FileManager.default.setAttributes([.protectionKey: FileProtectionType.complete], ofItemAtPath: dir.path)
        var flags = URLResourceValues(); flags.isExcludedFromBackup = true
        var protectedDirectory = dir; try protectedDirectory.setResourceValues(flags)
        var cleaned = URL(fileURLWithPath: name).lastPathComponent.components(separatedBy: .controlCharacters).joined()
        while cleaned.utf8.count > 180 { cleaned.removeLast() }
        if cleaned.isEmpty || [".", "..", "/"].contains(cleaned) { cleaned = "zalacznik" }
        var url = dir.appendingPathComponent(cleaned)
        try bytes.write(to: url, options: [.atomic, .completeFileProtection])
        do { try url.setResourceValues(flags) }
        catch { try? FileManager.default.removeItem(at: url); throw error }
        sharingURL = url; attachment = ShareItem(url: url)
    }
    func removeShare() {
        if let sharingURL { try? FileManager.default.removeItem(at: sharingURL) }
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("PromenadaShare", isDirectory: true)
        try? FileManager.default.removeItem(at: directory)
        sharingURL = nil; attachment = nil
    }
    func webView(_ webView: WKWebView, decidePolicyFor navigationAction: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        guard let url = navigationAction.request.url else { decisionHandler(.cancel); return }
        if trusted(url) && navigationAction.targetFrame?.isMainFrame != false {
            decisionHandler(.allow)
        } else {
            decisionHandler(.cancel)
            if navigationAction.navigationType == .linkActivated && ["https", "http"].contains(url.scheme ?? "") {
                UIApplication.shared.open(url)
            }
        }
    }
    func webView(_ webView: WKWebView, createWebViewWith configuration: WKWebViewConfiguration,
                 for navigationAction: WKNavigationAction, windowFeatures: WKWindowFeatures) -> WKWebView? {
        if navigationAction.navigationType == .linkActivated, let url = navigationAction.request.url,
           ["https","http"].contains(url.scheme ?? "") { UIApplication.shared.open(url) }
        return nil
    }
    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        generation += 1
        unlockTask?.cancel(); refreshTask?.cancel()
        cancelAttachmentLoad(); removeShare()
        ready = false; open = false; busy = true
        webView.loadFileURL(webRoot.appendingPathComponent("index.html"), allowingReadAccessTo: webRoot)
    }
}
