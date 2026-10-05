import Foundation
import CryptoKit
import CommonCrypto
import Security
import CoreFoundation

enum JournalError: LocalizedError {
    case format, password, network, keychain
    var errorDescription: String? {
        switch self {
        case .format: return "Raport ma nieobsługiwany format. Spróbuj ponownie później."
        case .password: return "To hasło nie otwiera dziennika. Sprawdź je i spróbuj ponownie."
        case .network: return "Nie udało się pobrać raportu. Sprawdź połączenie z internetem."
        case .keychain: return "Nie udało się zapamiętać dostępu w pęku kluczy iPhone’a."
        }
    }
}

// Foundation bridges JSON booleans through NSNumber; they are never schema integers.
enum ReportJSON {
    static func integer(_ value: Any?) -> Int? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID(),
              number.doubleValue.isFinite, number.doubleValue.rounded() == number.doubleValue,
              number.doubleValue >= 0, number.doubleValue <= Double(Int32.max) else { return nil }
        return number.intValue
    }
}

struct ReportCipher {
    struct Envelope: Decodable {
        let v: Int, iterations: Int
        let salt: String, iv: String, ciphertext: String
    }
    static func acceptsSchema(_ value: Any?, requiresSchema2: Bool = false) -> Bool {
        guard let schema = ReportJSON.integer(value), [1, 2].contains(schema) else { return false }
        return !requiresSchema2 || schema == 2
    }
    static func decrypt(_ encrypted: Data, password: String, requiresSchema2: Bool = false) throws -> String {
        guard encrypted.count <= 25_000_000,
              let envelope = try? JSONDecoder().decode(Envelope.self, from: encrypted),
              envelope.v == 1, envelope.iterations == 600000,
              let salt = Data(base64Encoded: envelope.salt), salt.count == 16,
              let iv = Data(base64Encoded: envelope.iv), iv.count == 12,
              let sealed = Data(base64Encoded: envelope.ciphertext), sealed.count > 16
        else { throw JournalError.format }
        let bytes = Array(password.utf8)
        var derived = [UInt8](repeating: 0, count: 32)
        let result = bytes.withUnsafeBytes { pass in
            salt.withUnsafeBytes { saltBytes in
                CCKeyDerivationPBKDF(CCPBKDFAlgorithm(kCCPBKDF2),
                    pass.bindMemory(to: Int8.self).baseAddress, bytes.count,
                    saltBytes.bindMemory(to: UInt8.self).baseAddress, salt.count,
                    CCPseudoRandomAlgorithm(kCCPRFHmacAlgSHA256), 600000, &derived, 32)
            }
        }
        guard result == kCCSuccess else { throw JournalError.format }
        defer { _ = derived.withUnsafeMutableBytes { $0.initializeMemory(as: UInt8.self, repeating: 0) } }
        let box = try AES.GCM.SealedBox(nonce: AES.GCM.Nonce(data: iv),
            ciphertext: sealed.dropLast(16), tag: sealed.suffix(16))
        let plain: Data
        do { plain = try AES.GCM.open(box, using: SymmetricKey(data: derived),
                                    authenticating: Data("promenada-report-v1".utf8)) }
        catch { throw JournalError.password }
        guard let object = try? JSONSerialization.jsonObject(with: plain) as? [String: Any],
              acceptsSchema(object["schema"], requiresSchema2: requiresSchema2),
              object["accounts"] is [String: Any],
              let text = String(data: plain, encoding: .utf8) else { throw JournalError.format }
        return text
    }
}

struct JournalAccess: Codable, Sendable, Equatable {
    let role: String
    let login: String
    let password: String
    var principal: String {
        role == "student" ? SHA256.hash(data: Data(login.trimmingCharacters(in: .whitespacesAndNewlines).lowercased().utf8)).map { String(format: "%02x", $0) }.joined() : "parent"
    }
    var endpoint: URL {
        let path = role == "student" ? "students/\(principal).enc.json" : "report.enc.json"
        return URL(string: "https://jakiesluchawki.github.io/promenada-dziennik/" + path)!
    }
    var v2Endpoint: URL {
        let path = role == "student" ? "students/\(principal).v2.enc.json" : "report.v2.enc.json"
        return ReportStore.siteRoot.appendingPathComponent(path)
    }
    func validate(_ text: String) throws {
        guard let bytes = text.data(using: .utf8),
              let report = try JSONSerialization.jsonObject(with: bytes) as? [String: Any],
              let schema = ReportJSON.integer(report["schema"]), [1, 2].contains(schema),
              let accounts = report["accounts"] as? [String: [String: Any]], !accounts.isEmpty else { throw JournalError.format }
        if role == "student" {
            guard report["audience"] as? String == "student", report["principal"] as? String == principal,
                  accounts.count == 1, accounts.values.first?["role"] as? String == "student" else { throw JournalError.format }
            let key = accounts.keys.first!
            let digest = report["digest"] as? [String: [[String: Any]]] ?? [:]
            guard (digest["actions", default: []] + digest["observations", default: []]).allSatisfy({ $0["child"] as? String == key }) else { throw JournalError.format }
        } else {
            guard role == "parent",
                  report["audience"] == nil || report["audience"] as? String == "parent",
                  report["principal"] == nil || report["principal"] as? String == "parent",
                  accounts.values.allSatisfy({ $0["role"] == nil || $0["role"] as? String == "parent" })
            else { throw JournalError.format }
        }
        for (key, account) in accounts {
            if let child = account["child"], child as? String != key { throw JournalError.format }
            var seen = Set<String>()
            for source in ["messages", "announcements"] {
                let kind = source == "messages" ? "message" : "announcement"
                guard let records = account[source] else { continue }
                guard let messages = records as? [[String: Any]], messages.allSatisfy({
                    guard let id = $0["id"] as? String,
                          id.hasPrefix(key + ":" + kind + ":"), $0["child"] as? String == key,
                          $0["kind"] as? String == kind, seen.insert(id).inserted else { return false }
                    return true
                }) else { throw JournalError.format }
            }
        }
    }
    var encoded: String { String(data: try! JSONEncoder().encode(self), encoding: .utf8)! }
    static func restore(_ value: String) -> JournalAccess {
        if let bytes = value.data(using: .utf8), let access = try? JSONDecoder().decode(Self.self, from: bytes) { return access }
        // Build 1 stored the family password directly. Preserve the existing signed-in session.
        return Self(role: "parent", login: "", password: value)
    }
}

enum AccessKey {
    private static let query: [String: Any] = [
        kSecClass as String: kSecClassGenericPassword,
        kSecAttrService as String: "pl.mahboob.mahbrus.ios",
        kSecAttrAccount as String: "journal-access",
        kSecAttrSynchronizable as String: false
    ]
    static func read() -> String? {
        var request = query
        request[kSecReturnData as String] = true
        request[kSecMatchLimit as String] = kSecMatchLimitOne
        var result: CFTypeRef?
        guard SecItemCopyMatching(request as CFDictionary, &result) == errSecSuccess,
              let bytes = result as? Data else { return nil }
        return String(data: bytes, encoding: .utf8)
    }
    static func save(_ value: String) throws {
        let attributes: [String: Any] = [
            kSecValueData as String: Data(value.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleWhenUnlockedThisDeviceOnly
        ]
        let status = SecItemUpdate(query as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            guard SecItemAdd(query.merging(attributes) { _, b in b } as CFDictionary, nil) == errSecSuccess
            else { throw JournalError.keychain }
        } else if status != errSecSuccess { throw JournalError.keychain }
    }
    static func remove() { SecItemDelete(query as CFDictionary) }
}

// Both report and blob transfers are capped while receiving data, not after allocation.
// A request owns its session and rejects every redirect, even to the same host.
enum ReportDownloadError: Error { case notFound, invalidResponse, tooLarge }

final class BoundedReportDownload: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    private let request: URLRequest
    private let maximum: Int
    private let configuration: URLSessionConfiguration
    private let lock = NSLock()
    private var buffer = Data()
    private var continuation: CheckedContinuation<Data, Error>?
    private var session: URLSession?
    private var task: URLSessionDataTask?
    private var finished = false

    private init(url: URL, maximum: Int, configuration: URLSessionConfiguration) {
        self.maximum = maximum
        self.configuration = configuration
        configuration.httpShouldSetCookies = false
        configuration.urlCache = nil
        configuration.timeoutIntervalForResource = 40
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 20)
        request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        request.setValue("identity", forHTTPHeaderField: "Accept-Encoding")
        self.request = request
    }
    static func fetch(_ url: URL, maximum: Int) async throws -> Data {
        try await fetch(url, maximum: maximum, configuration: .ephemeral)
    }
    #if DEBUG
    // XCTest supplies an in-process URLProtocol; production has no injectable transport.
    static func testFetch(_ url: URL, maximum: Int, protocols: [AnyClass]) async throws -> Data {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = protocols
        return try await fetch(url, maximum: maximum, configuration: configuration)
    }
    #endif
    private static func fetch(_ url: URL, maximum: Int, configuration: URLSessionConfiguration) async throws -> Data {
        guard url.scheme == ReportStore.siteRoot.scheme, url.host == ReportStore.siteRoot.host,
              url.port == nil, url.user == nil, url.password == nil,
              url.path.hasPrefix(ReportStore.siteRoot.path), maximum > 0
        else { throw JournalError.format }
        let download = BoundedReportDownload(url: url, maximum: maximum, configuration: configuration)
        return try await withTaskCancellationHandler {
            try Task.checkCancellation()
            return try await withCheckedThrowingContinuation { download.start($0) }
        } onCancel: { download.finish(.failure(CancellationError())) }
    }
    private func start(_ continuation: CheckedContinuation<Data, Error>) {
        lock.lock()
        guard !finished else { lock.unlock(); continuation.resume(throwing: CancellationError()); return }
        self.continuation = continuation
        let session = URLSession(configuration: configuration, delegate: self, delegateQueue: nil)
        let task = session.dataTask(with: request)
        self.session = session; self.task = task
        lock.unlock()
        task.resume()
    }
    private func finish(_ result: Result<Data, Error>) {
        lock.lock()
        guard !finished else { lock.unlock(); return }
        finished = true
        let completion = self.continuation, currentSession = self.session
        self.continuation = nil; self.session = nil; task = nil; buffer = Data()
        lock.unlock()
        currentSession?.invalidateAndCancel()
        completion?.resume(with: result)
    }
    func urlSession(_ session: URLSession, task: URLSessionTask,
                    willPerformHTTPRedirection response: HTTPURLResponse, newRequest request: URLRequest,
                    completionHandler: @escaping (URLRequest?) -> Void) {
        completionHandler(nil)
        finish(.failure(ReportDownloadError.invalidResponse))
    }
    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive response: URLResponse,
                    completionHandler: @escaping (URLSession.ResponseDisposition) -> Void) {
        guard let response = response as? HTTPURLResponse,
              response.url?.absoluteString == request.url?.absoluteString else {
            completionHandler(.cancel); finish(.failure(ReportDownloadError.invalidResponse)); return
        }
        guard response.statusCode == 200 else {
            completionHandler(.cancel)
            finish(.failure(response.statusCode == 404 ? ReportDownloadError.notFound : ReportDownloadError.invalidResponse))
            return
        }
        guard response.expectedContentLength <= Int64(maximum) else {
            completionHandler(.cancel); finish(.failure(ReportDownloadError.tooLarge)); return
        }
        completionHandler(.allow)
    }
    func urlSession(_ session: URLSession, dataTask: URLSessionDataTask, didReceive data: Data) {
        lock.lock()
        guard !finished else { lock.unlock(); return }
        guard data.count <= maximum - buffer.count else {
            lock.unlock(); finish(.failure(ReportDownloadError.tooLarge)); return
        }
        buffer.append(data)
        lock.unlock()
    }
    func urlSession(_ session: URLSession, task: URLSessionTask, didCompleteWithError error: Error?) {
        if let error { finish(.failure(error)); return }
        lock.lock(); let bytes = buffer; lock.unlock()
        finish(.success(bytes))
    }
}

struct EncryptedAttachment: Codable, Equatable, Sendable {
    let v: Int
    let path: String
    let key: String
    let iv: String
    let sha256: String
    let size: Int
    static let maximumPlaintext = 8_000_000
    static let maximumCiphertext = 8_000_016
    static let fields: Set<String> = ["v", "path", "key", "iv", "sha256", "size"]

    static func isDigest(_ value: String) -> Bool {
        value.utf8.count == 64 && value.utf8.allSatisfy { (48...57).contains($0) || (97...102).contains($0) }
    }
    var paddedSize: Int { min(Self.maximumPlaintext, max(65_536, ((size + 65_535) / 65_536) * 65_536)) }
    var ciphertextDigest: String { String(path.dropFirst("attachments/".count).dropLast(".bin".count)) }
    func validate() throws {
        guard v == 1, (0...Self.maximumPlaintext).contains(size),
              path.hasPrefix("attachments/"), path.hasSuffix(".bin"),
              Self.isDigest(ciphertextDigest), Self.isDigest(sha256),
              let keyBytes = Data(base64Encoded: key), keyBytes.count == 32, keyBytes.base64EncodedString() == key,
              let ivBytes = Data(base64Encoded: iv), ivBytes.count == 12, ivBytes.base64EncodedString() == iv
        else { throw JournalError.format }
    }
    func decrypt(_ ciphertext: Data, aad: Data) throws -> Data {
        try validate()
        guard ciphertext.count == paddedSize + 16,
              Self.digest(ciphertext) == ciphertextDigest else { throw JournalError.format }
        let box = try AES.GCM.SealedBox(nonce: AES.GCM.Nonce(data: Data(base64Encoded: iv)!),
                                       ciphertext: ciphertext.dropLast(16), tag: ciphertext.suffix(16))
        let padded = try AES.GCM.open(box, using: SymmetricKey(data: Data(base64Encoded: key)!), authenticating: aad)
        guard padded.count == paddedSize else { throw JournalError.format }
        let bytes = Data(padded.prefix(size))
        guard bytes.count == size, Self.digest(bytes) == sha256 else { throw JournalError.format }
        return bytes
    }
    static func digest(_ bytes: Data) -> String { SHA256.hash(data: bytes).map { String(format: "%02x", $0) }.joined() }
}

struct NativeAttachmentRequest: Decodable, Sendable {
    struct Scope: Decodable, Sendable { let audience: String; let principal: String }
    let name: String
    let accountKey: String
    let source: String
    let messageId: String
    let attachmentIndex: Int
    let ref: EncryptedAttachment
    let scope: Scope

    static func parse(_ body: [String: Any]) throws -> Self {
        guard let reference = body["ref"] as? [String: Any],
              Set(reference.keys) == EncryptedAttachment.fields else { throw JournalError.format }
        let bytes = try JSONSerialization.data(withJSONObject: body)
        guard bytes.count <= 16_384 else { throw JournalError.format }
        return try JSONDecoder().decode(Self.self, from: bytes)
    }
}

// The bridge only supplies a selector. The key and AAD always come from the
// currently authenticated native snapshot, never directly from the web message.
struct AuthorizedAttachment: Sendable {
    let name: String
    let ref: EncryptedAttachment
    let aad: Data

    static func resolve(_ request: NativeAttachmentRequest, reportText: String, access: JournalAccess) throws -> Self {
        try access.validate(reportText)
        guard let report = try JSONSerialization.jsonObject(with: Data(reportText.utf8)) as? [String: Any],
              ReportJSON.integer(report["schema"]) == 2,
              let accounts = report["accounts"] as? [String: [String: Any]],
              let account = accounts[request.accountKey],
              account["child"] as? String == request.accountKey,
              ["messages", "announcements"].contains(request.source),
              let messages = account[request.source] as? [[String: Any]],
              request.messageId.hasPrefix(request.accountKey + (request.source == "messages" ? ":message:" : ":announcement:")),
              request.attachmentIndex >= 0 else { throw JournalError.format }
        let audience = report["audience"] as? String ?? "parent"
        let principal = report["principal"] as? String ?? "parent"
        guard request.scope.audience == audience, request.scope.principal == principal,
              audience == access.role, principal == access.principal else { throw JournalError.format }
        let matches = messages.filter { $0["id"] as? String == request.messageId }
        guard matches.count == 1, let message = matches.first,
              message["child"] as? String == request.accountKey,
              message["kind"] as? String == (request.source == "messages" ? "message" : "announcement"),
              let attachments = message["attachments"] as? [[String: Any]],
              request.attachmentIndex < attachments.count else { throw JournalError.format }
        let attachment = attachments[request.attachmentIndex]
        guard attachment["base64"] == nil, attachment["error"] == nil,
              let reference = attachment["encrypted_attachment"] as? [String: Any],
              Set(reference.keys) == EncryptedAttachment.fields else { throw JournalError.format }
        let ref = try JSONDecoder().decode(EncryptedAttachment.self, from: JSONSerialization.data(withJSONObject: reference))
        try ref.validate()
        let name = (attachment["name"] as? String).flatMap { $0.isEmpty ? nil : $0 } ?? "zalacznik"
        guard request.ref == ref, request.name == name else { throw JournalError.format }
        let aad: [Any] = ["promenada-attachment-v1", audience, principal, request.accountKey,
                          request.messageId, request.attachmentIndex, ref.sha256, ref.size]
        return Self(name: name, ref: ref, aad: try JSONSerialization.data(withJSONObject: aad, options: [.withoutEscapingSlashes]))
    }
}

actor ReportStore {
    private let cacheDirectory: URL
    private let fetch: @Sendable (URL, Int) async throws -> Data
    #if DEBUG
    private let testBeforeCacheMetadata: (@Sendable (URL) throws -> Void)?
    #endif
    init() {
        cacheDirectory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        fetch = { try await BoundedReportDownload.fetch($0, maximum: $1) }
        #if DEBUG
        testBeforeCacheMetadata = nil
        #endif
    }
    #if DEBUG
    // Isolated synthetic caches and transport are available only to Debug tests.
    init(testDirectory: URL, testBeforeCacheMetadata: (@Sendable (URL) throws -> Void)? = nil,
         testFetch: @escaping @Sendable (URL, Int) async throws -> Data) {
        cacheDirectory = testDirectory
        fetch = testFetch
        self.testBeforeCacheMetadata = testBeforeCacheMetadata
    }
    #endif
    private var revision = 0
    private var activeRevision = 0
    private var activeText: String?
    private var activeAccess: JournalAccess?
    #if DEBUG
    private var fixtureLoads = 0
    #endif
    static let siteRoot = URL(string: "https://jakiesluchawki.github.io/promenada-dziennik/")!
    static let endpoint = siteRoot.appendingPathComponent("report.enc.json")
    private var directory: URL { cacheDirectory }
    private func cachedURL(_ access: JournalAccess, legacy: Bool = false) -> URL {
        let prefix = access.role == "parent" ? "last-report" : "student-" + access.principal
        return directory.appendingPathComponent(prefix + (legacy ? ".enc.json" : ".v2.enc.json"))
    }
    private func cachedBytes(_ access: JournalAccess) throws -> Data? {
        // An old schema1 snapshot remains readable after the upgrade. Never overwrite it.
        let modern = cachedURL(access)
        let url = FileManager.default.fileExists(atPath: modern.path) ? modern : cachedURL(access, legacy: true)
        guard FileManager.default.fileExists(atPath: url.path) else { return nil }
        return try boundedLocalRead(url, maximum: 25_000_000)
    }
    private func boundedLocalRead(_ url: URL, maximum: Int) throws -> Data {
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        guard let size = attributes[.size] as? NSNumber, size.int64Value <= Int64(maximum),
              attributes[.type] as? FileAttributeType == .typeRegular else { throw JournalError.format }
        let handle = try FileHandle(forReadingFrom: url)
        defer { try? handle.close() }
        let bytes = try handle.read(upToCount: maximum + 1) ?? Data()
        guard bytes.count <= maximum else { throw JournalError.format }
        return bytes
    }
    private func activate(_ text: String, access: JournalAccess) {
        activeRevision += 1; activeText = text; activeAccess = access
    }
    func cached(access: JournalAccess) throws -> String? {
        try Task.checkCancellation()
        guard let bytes = try cachedBytes(access) else { return nil }
        let text = try ReportCipher.decrypt(bytes, password: access.password)
        try access.validate(text)
        try Task.checkCancellation()
        activate(text, access: access)
        return text
    }
    private func downloadReport(_ access: JournalAccess) async throws -> (bytes: Data, requiresSchema2: Bool) {
        func fresh(_ endpoint: URL) -> URL {
            var parts = URLComponents(url: endpoint, resolvingAgainstBaseURL: false)!
            parts.queryItems = [URLQueryItem(name: "t", value: String(Date().timeIntervalSince1970))]
            return parts.url!
        }
        do {
            let bytes = try await fetch(fresh(access.v2Endpoint), 25_000_000)
            return (bytes, true)
        }
        catch ReportDownloadError.notFound {
            // Only absence enables v1 transport; never downgrade on authentication or network errors.
            try Task.checkCancellation()
            let bytes = try await fetch(fresh(access.endpoint), 25_000_000)
            return (bytes, false)
        }
    }
    func load(access: JournalAccess) async throws -> (text: String, offline: Bool) {
        let startedAtRevision = revision
        var encrypted: Data
        var requiresSchema2 = false
        var offline = false
        do {
            #if DEBUG
            if let fixture = ProcessInfo.processInfo.environment["PROMENADA_TEST_REPORT"] {
                fixtureLoads += 1
                if ProcessInfo.processInfo.environment["PROMENADA_TEST_OFFLINE"] == "1" { throw JournalError.network }
                let selected = fixtureLoads > 1 ? ProcessInfo.processInfo.environment["PROMENADA_TEST_NEXT_REPORT"] ?? fixture : fixture
                guard let bytes = Data(base64Encoded: selected) else { throw JournalError.format }
                encrypted = bytes
                requiresSchema2 = ProcessInfo.processInfo.environment["PROMENADA_TEST_REQUIRE_SCHEMA2"] == "1"
            } else {
                let result = try await downloadReport(access)
                encrypted = result.bytes; requiresSchema2 = result.requiresSchema2
            }
            #else
            let result = try await downloadReport(access)
            encrypted = result.bytes; requiresSchema2 = result.requiresSchema2
            #endif
        } catch {
            try Task.checkCancellation()
            guard startedAtRevision == revision else { throw CancellationError() }
            guard let cached = try cachedBytes(access) else { throw JournalError.network }
            encrypted = cached; requiresSchema2 = false; offline = true
        }
        try Task.checkCancellation()
        guard startedAtRevision == revision else { throw CancellationError() }
        let text = try ReportCipher.decrypt(encrypted, password: access.password, requiresSchema2: requiresSchema2)
        try access.validate(text)
        try Task.checkCancellation()
        if !offline { try protectedWrite(encrypted, to: cachedURL(access)) }
        activate(text, access: access)
        return (text, offline)
    }
    private func protectedWrite(_ bytes: Data, to destination: URL) throws {
        let parent = destination.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: parent, withIntermediateDirectories: true,
                                                attributes: [.protectionKey: FileProtectionType.complete])
        try FileManager.default.setAttributes([.protectionKey: FileProtectionType.complete], ofItemAtPath: parent.path)
        var flags = URLResourceValues(); flags.isExcludedFromBackup = true
        var protectedDirectory = parent
        try protectedDirectory.setResourceValues(flags)
        // Prepare every required attribute on a sibling before replacing the good cache.
        let staging = parent.appendingPathComponent(".promenada-pending-" + UUID().uuidString)
        defer { try? FileManager.default.removeItem(at: staging) }
        try bytes.write(to: staging, options: [.atomic, .completeFileProtection])
        #if DEBUG
        try testBeforeCacheMetadata?(staging)
        #endif
        try FileManager.default.setAttributes([.protectionKey: FileProtectionType.complete], ofItemAtPath: staging.path)
        var stagedURL = staging; try stagedURL.setResourceValues(flags)
        if FileManager.default.fileExists(atPath: destination.path) {
            _ = try FileManager.default.replaceItemAt(destination, withItemAt: staging,
                                                       backupItemName: nil, options: [.usingNewMetadataOnly])
        } else {
            try FileManager.default.moveItem(at: staging, to: destination)
        }
    }
    func attachment(_ request: NativeAttachmentRequest, access: JournalAccess) async throws -> (name: String, bytes: Data) {
        try Task.checkCancellation()
        guard activeAccess == access, let text = activeText else { throw JournalError.format }
        let startedAtRevision = revision, startedAtActiveRevision = activeRevision
        let authorized = try AuthorizedAttachment.resolve(request, reportText: text, access: access)
        let ref = authorized.ref
        let cache = directory.appendingPathComponent("PromenadaAttachments", isDirectory: true)
            .appendingPathComponent(access.role + "-" + access.principal, isDirectory: true)
            .appendingPathComponent(ref.ciphertextDigest + ".bin")
        if let encrypted = try? boundedLocalRead(cache, maximum: EncryptedAttachment.maximumCiphertext),
           let bytes = try? ref.decrypt(encrypted, aad: authorized.aad) {
            try Task.checkCancellation()
            return (authorized.name, bytes)
        }
        // Immutable ciphertext-hash URLs need no query and never leave the fixed publication root.
        let encrypted = try await fetch(Self.siteRoot.appendingPathComponent(ref.path),
                                        min(EncryptedAttachment.maximumCiphertext, ref.paddedSize + 16))
        try Task.checkCancellation()
        guard revision == startedAtRevision, activeRevision == startedAtActiveRevision, activeAccess == access
        else { throw CancellationError() }
        let bytes = try ref.decrypt(encrypted, aad: authorized.aad)
        try Task.checkCancellation()
        try protectedWrite(encrypted, to: cache)
        return (authorized.name, bytes)
    }
    func clear() {
        revision += 1; activeRevision += 1; activeText = nil; activeAccess = nil
        for url in (try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)) ?? [] {
            if ["last-report.enc.json", "last-report.v2.enc.json", "PromenadaAttachments"].contains(url.lastPathComponent) ||
                url.lastPathComponent.hasPrefix(".promenada-pending-") ||
                (url.lastPathComponent.hasPrefix("student-") && url.pathExtension == "json") {
                try? FileManager.default.removeItem(at: url)
            }
        }
    }
}

struct RefreshConfiguration: Codable, Sendable {
    let endpoint: String
    let token: String
    struct State: Decodable, Sendable {
        let state: String
        let message: String
        let run: String?
        var pending: Bool { state == "queued" || state == "running" }
    }
    func request(start: Bool, run: String? = nil) async throws -> State {
        // An encrypted report cannot redirect the refresh capability to another host.
        guard endpoint == "https://mahbrus-refresh.netlify.app/api/refresh",
              token.range(of: "^[A-Za-z0-9_-]{43}$", options: .regularExpression) != nil,
              var components = URLComponents(string: endpoint) else { throw JournalError.format }
        if let run { components.queryItems = [URLQueryItem(name: "run", value: run)] }
        var req = URLRequest(url: components.url!, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 25)
        req.httpMethod = start ? "POST" : "GET"
        req.setValue("Bearer " + token, forHTTPHeaderField: "Authorization")
        let session = URLSession(configuration: .ephemeral)
        defer { session.invalidateAndCancel() }
        let (data, response) = try await session.data(for: req)
        guard let response = response as? HTTPURLResponse, [200, 202].contains(response.statusCode),
              response.url?.host == "mahbrus-refresh.netlify.app", data.count < 10000 else { throw JournalError.network }
        return try JSONDecoder().decode(State.self, from: data)
    }
}
