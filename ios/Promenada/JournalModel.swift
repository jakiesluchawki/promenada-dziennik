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
    private let store = ReportStore()
    private var lastCheck = Date.distantPast
    private var generation = 0
    private var ready = false
    private var sharingURL: URL?
    private let webRoot = Bundle.main.resourceURL!.appendingPathComponent("Web", isDirectory: true)
    private let reviewKey = "promenada-review-v1"

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
            if let password = AccessKey.read() { unlock(password) } else { busy = false }
        case "refresh": if let password = AccessKey.read() { unlock(password, refreshing: true) }
        case "forget": confirmForget = true
        case "review":
            if let value = body["value"] as? String, value.utf8.count < 1_000_000,
               let bytes = value.data(using: .utf8),
               (try? JSONSerialization.jsonObject(with: bytes)) is [String: Any] {
                UserDefaults.standard.set(value, forKey: reviewKey)
            }
        case "attachment":
            guard let filename = body["name"] as? String,
                  let base64 = body["base64"] as? String,
                  base64.count < 25_000_000, let bytes = Data(base64Encoded: base64) else { return }
            do {
                removeShare()
                let dir = FileManager.default.temporaryDirectory.appendingPathComponent("PromenadaShare", isDirectory: true)
                try FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
                let cleaned = URL(fileURLWithPath: filename).lastPathComponent
                    .components(separatedBy: .controlCharacters).joined()
                let url = dir.appendingPathComponent(cleaned.isEmpty ? "zalacznik" : cleaned)
                try bytes.write(to: url, options: [.atomic, .completeFileProtection])
                sharingURL = url; attachment = ShareItem(url: url)
            } catch { sendStatus("Nie udało się otworzyć załącznika. Spróbuj ponownie.") }
        default: break
        }
    }
    func unlock(_ password: String, refreshing: Bool = false) {
        guard ready, !password.isEmpty, !busy || !open else { return }
        busy = true; error = ""
        let requestGeneration = generation
        Task {
            do {
                let result = try await store.load(password: password)
                guard generation == requestGeneration else { return }
                try AccessKey.save(password)
                let review = UserDefaults.standard.string(forKey: reviewKey) ?? "{\"read\":{},\"done\":{},\"priority\":{}}"
                let message = result.offline ? "Bez połączenia z serwerem. Pokazuję ostatni zapisany raport." : ""
                _ = try await web?.callAsyncJavaScript(
                    "window.promenadaReceive(JSON.parse(report), status, JSON.parse(review));",
                    arguments: ["report": result.text, "status": message, "review": review],
                    in: nil, contentWorld: .page)
                open = true; lastCheck = Date()
            } catch {
                guard generation == requestGeneration else { return }
                if open { sendStatus("Nie udało się odświeżyć raportu. Oglądasz ostatnio otwartą wersję.") }
                else { self.error = error.localizedDescription }
            }
            if generation == requestGeneration { busy = false; sendBusy(false) }
        }
    }
    func foreground() {
        if open && !busy && Date().timeIntervalSince(lastCheck) > 60, let password = AccessKey.read() {
            unlock(password, refreshing: true)
        }
    }
    func forget() {
        generation += 1
        AccessKey.remove()
        UserDefaults.standard.removeObject(forKey: reviewKey)
        open = false; busy = true; error = ""
        Task { await store.clear(); busy = false }
        removeShare()
        web?.evaluateJavaScript("window.promenadaClear()")
    }
    private func sendStatus(_ text: String) {
        web?.callAsyncJavaScript("document.getElementById('sync-status').textContent = text; document.getElementById('refresh').disabled = false; document.getElementById('refresh').textContent = 'Sprawdź raport';", arguments: ["text": text], in: nil, in: .page, completionHandler: nil)
    }
    private func sendBusy(_ value: Bool) {
        web?.callAsyncJavaScript("document.getElementById('refresh').disabled = value; document.getElementById('refresh').textContent = value ? 'Sprawdzam…' : 'Sprawdź raport';", arguments: ["value": value], in: nil, in: .page, completionHandler: nil)
    }
    func removeShare() {
        if let sharingURL { try? FileManager.default.removeItem(at: sharingURL) }
        sharingURL = nil
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
        ready = false; open = false; busy = true
        webView.loadFileURL(webRoot.appendingPathComponent("index.html"), allowingReadAccessTo: webRoot)
    }
}
