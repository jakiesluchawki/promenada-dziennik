import Foundation
import CryptoKit
import CommonCrypto
import Security

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

struct ReportCipher {
    struct Envelope: Decodable {
        let v: Int, iterations: Int
        let salt: String, iv: String, ciphertext: String
    }
    static func decrypt(_ encrypted: Data, password: String) throws -> String {
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
              object["schema"] as? Int == 1, object["accounts"] is [String: Any],
              let text = String(data: plain, encoding: .utf8) else { throw JournalError.format }
        return text
    }
}

struct JournalAccess: Codable, Sendable {
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
    func validate(_ text: String) throws {
        guard let bytes = text.data(using: .utf8),
              let report = try JSONSerialization.jsonObject(with: bytes) as? [String: Any],
              let accounts = report["accounts"] as? [String: [String: Any]] else { throw JournalError.format }
        if role == "student" {
            guard report["audience"] as? String == "student", report["principal"] as? String == principal,
                  accounts.count == 1, accounts.values.first?["role"] as? String == "student" else { throw JournalError.format }
            let key = accounts.keys.first!
            let digest = report["digest"] as? [String: [[String: Any]]] ?? [:]
            guard (digest["actions", default: []] + digest["observations", default: []]).allSatisfy({ $0["child"] as? String == key }) else { throw JournalError.format }
        } else if role != "parent" || report["audience"] as? String == "student" { throw JournalError.format }
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

actor ReportStore {
    private var revision = 0
    static let endpoint = URL(string: "https://jakiesluchawki.github.io/promenada-dziennik/report.enc.json")!
    private func cachedURL(_ access: JournalAccess) -> URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(access.role == "parent" ? "last-report.enc.json" : "student-" + access.principal + ".enc.json")
    }
    func load(access: JournalAccess) async throws -> (text: String, offline: Bool) {
        let startedAtRevision = revision
        let cachedURL = cachedURL(access)
        let endpoint = access.endpoint
        var encrypted: Data
        var offline = false
        do {
            #if DEBUG
            if let fixture = ProcessInfo.processInfo.environment["PROMENADA_TEST_REPORT"] {
                if ProcessInfo.processInfo.environment["PROMENADA_TEST_OFFLINE"] == "1" { throw JournalError.network }
                guard let bytes = Data(base64Encoded: fixture) else { throw JournalError.format }
                encrypted = bytes
            } else {
            var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false)!
            components.queryItems = [URLQueryItem(name: "t", value: String(Date().timeIntervalSince1970))]
            var request = URLRequest(url: components.url!, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 20)
            request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
            let configuration = URLSessionConfiguration.ephemeral
            configuration.httpShouldSetCookies = false
            let session = URLSession(configuration: configuration)
            defer { session.invalidateAndCancel() }
            let (bytes, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                  http.url?.host == endpoint.host, bytes.count <= 25_000_000 else { throw JournalError.network }
            encrypted = bytes
            }
            #else
            var components = URLComponents(url: endpoint, resolvingAgainstBaseURL: false)!
            components.queryItems = [URLQueryItem(name: "t", value: String(Date().timeIntervalSince1970))]
            var request = URLRequest(url: components.url!, cachePolicy: .reloadIgnoringLocalCacheData, timeoutInterval: 20)
            request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
            let configuration = URLSessionConfiguration.ephemeral
            configuration.httpShouldSetCookies = false
            let session = URLSession(configuration: configuration)
            defer { session.invalidateAndCancel() }
            let (bytes, response) = try await session.data(for: request)
            guard let http = response as? HTTPURLResponse, http.statusCode == 200,
                  http.url?.host == endpoint.host, bytes.count <= 25_000_000 else { throw JournalError.network }
            encrypted = bytes
            #endif
        } catch {
            guard let cached = try? Data(contentsOf: cachedURL) else { throw JournalError.network }
            encrypted = cached
            offline = true
        }
        guard startedAtRevision == revision else { throw CancellationError() }
        let text = try ReportCipher.decrypt(encrypted, password: access.password)
        try access.validate(text)
        if !offline {
            let directory = cachedURL.deletingLastPathComponent()
            try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
            try encrypted.write(to: cachedURL, options: [.atomic, .completeFileProtection])
            var url = cachedURL
            var flags = URLResourceValues()
            flags.isExcludedFromBackup = true
            try url.setResourceValues(flags)
        }
        return (text, offline)
    }
    func clear() {
        revision += 1
        let directory = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
        for url in (try? FileManager.default.contentsOfDirectory(at: directory, includingPropertiesForKeys: nil)) ?? [] {
            if url.lastPathComponent == "last-report.enc.json" || (url.lastPathComponent.hasPrefix("student-") && url.pathExtension == "json") { try? FileManager.default.removeItem(at: url) }
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
