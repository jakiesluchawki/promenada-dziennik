import XCTest
import Foundation
import CryptoKit
import CommonCrypto
@testable import Mahbrus

// Every HTTP request is intercepted in-process. Missing routes fail closed;
// no credentials, school data, published reports, or network server are used.
private struct StubReply {
    var status = 200
    var chunks: [Data] = []
    var declaredLength: Int? = nil
    var redirect: URL? = nil
}
private final class StubState: @unchecked Sendable {
    private let lock = NSLock()
    private var replies: [String: StubReply] = [:]
    private var seen: [String] = []
    func reset(_ replies: [String: StubReply] = [:]) {
        lock.lock(); defer { lock.unlock() }; self.replies = replies; seen = []
    }
    func response(for url: URL) -> StubReply? {
        lock.lock(); defer { lock.unlock() }; seen.append(url.path); return replies[url.path]
    }
    var requests: [String] { lock.lock(); defer { lock.unlock() }; return seen }
}
private final class SyntheticURLProtocol: URLProtocol, @unchecked Sendable {
    static let state = StubState()
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        guard let url = request.url, let reply = Self.state.response(for: url) else {
            client?.urlProtocol(self, didFailWithError: URLError(.notConnectedToInternet)); return
        }
        if let destination = reply.redirect {
            let response = HTTPURLResponse(url: url, statusCode: 302, httpVersion: "HTTP/1.1",
                                           headerFields: ["Location": destination.absoluteString])!
            client?.urlProtocol(self, wasRedirectedTo: URLRequest(url: destination), redirectResponse: response)
            return
        }
        var headers = ["Content-Type": "application/octet-stream"]
        if let length = reply.declaredLength { headers["Content-Length"] = String(length) }
        let response = HTTPURLResponse(url: url, statusCode: reply.status, httpVersion: "HTTP/1.1", headerFields: headers)!
        client?.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
        for chunk in reply.chunks { client?.urlProtocol(self, didLoad: chunk) }
        client?.urlProtocolDidFinishLoading(self)
    }
    override func stopLoading() {}
}
private actor DelayedBytes {
    private var continuation: CheckedContinuation<Data, Never>?
    private(set) var arrived = false
    func wait() async -> Data {
        arrived = true
        return await withCheckedContinuation { continuation = $0 }
    }
    func release(_ bytes: Data) { continuation?.resume(returning: bytes); continuation = nil }
}
private enum SyntheticFailure: Error { case timeout }

private struct Fixture {
    let access: JournalAccess
    let text: String
    let encrypted: Data
    let plaintext: Data
    let ciphertext: Data
    let ref: EncryptedAttachment
    let request: NativeAttachmentRequest
    let body: [String: Any]
    static func make(role: String = "parent", schema: Int = 2) throws -> Fixture {
        let access = JournalAccess(role: role, login: role == "student" ? "student-demo" : "", password: "synthetic-only-password")
        let plaintext = Data("SYNTHETIC runtime attachment: zażółć 🐸".utf8)
        let hash = EncryptedAttachment.digest(plaintext)
        let key = Data(repeating: 17, count: 32), iv = Data(repeating: 23, count: 12)
        let aad: [Any] = ["promenada-attachment-v1", role, access.principal, "demo", "demo:message:one", 0, hash, plaintext.count]
        var padded = plaintext; padded.append(Data(repeating: 173, count: 65_536 - plaintext.count))
        let box = try AES.GCM.seal(padded, using: SymmetricKey(data: key), nonce: AES.GCM.Nonce(data: iv),
                                   authenticating: JSONSerialization.data(withJSONObject: aad, options: [.withoutEscapingSlashes]))
        let ciphertext = box.ciphertext + box.tag
        let ref = EncryptedAttachment(v: 1, path: "attachments/" + EncryptedAttachment.digest(ciphertext) + ".bin",
                                      key: key.base64EncodedString(), iv: iv.base64EncodedString(), sha256: hash, size: plaintext.count)
        let reference = try JSONSerialization.jsonObject(with: JSONEncoder().encode(ref)) as! [String: Any]
        var attachment: [String: Any] = ["name": "synthetic-demo.txt", "mime": "text/plain", "size": plaintext.count]
        if schema == 2 { attachment["encrypted_attachment"] = reference }
        else { attachment["base64"] = plaintext.base64EncodedString() }
        let message: [String: Any] = ["id": "demo:message:one", "child": "demo", "kind": "message", "attachments": [attachment]]
        let report: [String: Any] = ["schema": schema, "audience": role, "principal": access.principal,
                                    "accounts": ["demo": ["child": "demo", "role": role, "messages": [message], "announcements": []]],
                                    "digest": ["actions": [], "observations": []]]
        let plainReport = try JSONSerialization.data(withJSONObject: report, options: [.sortedKeys])
        let encrypted = try encryptReport(plainReport, password: access.password)
        let body: [String: Any] = ["action": "attachment", "name": "synthetic-demo.txt", "ref": reference,
                                  "accountKey": "demo", "source": "messages", "messageId": "demo:message:one", "attachmentIndex": 0,
                                  "scope": ["audience": role, "principal": access.principal]]
        return Fixture(access: access, text: String(data: plainReport, encoding: .utf8)!, encrypted: encrypted,
                       plaintext: plaintext, ciphertext: ciphertext, ref: ref, request: try NativeAttachmentRequest.parse(body), body: body)
    }
    private static func encryptReport(_ data: Data, password: String) throws -> Data {
        let salt = Data(repeating: 31, count: 16), iv = Data(repeating: 41, count: 12)
        let pass = Array(password.utf8); var derived = [UInt8](repeating: 0, count: 32)
        let status = pass.withUnsafeBytes { passwordBytes in
            salt.withUnsafeBytes { saltBytes in
                CCKeyDerivationPBKDF(CCPBKDFAlgorithm(kCCPBKDF2), passwordBytes.bindMemory(to: Int8.self).baseAddress, pass.count,
                    saltBytes.bindMemory(to: UInt8.self).baseAddress, salt.count, CCPseudoRandomAlgorithm(kCCPRFHmacAlgSHA256),
                    600_000, &derived, 32)
            }
        }
        guard status == kCCSuccess else { throw JournalError.format }
        let box = try AES.GCM.seal(data, using: SymmetricKey(data: derived), nonce: AES.GCM.Nonce(data: iv),
                                   authenticating: Data("promenada-report-v1".utf8))
        return try JSONSerialization.data(withJSONObject: ["v": 1, "iterations": 600_000, "salt": salt.base64EncodedString(),
            "iv": iv.base64EncodedString(), "ciphertext": (box.ciphertext + box.tag).base64EncodedString()])
    }
}

final class PromenadaRuntimeTests: XCTestCase {
    private static let parent = try! Fixture.make()
    private static let student = try! Fixture.make(role: "student")
    private static let legacy = try! Fixture.make(schema: 1)
    private var root: URL!
    override func setUpWithError() throws {
        root = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("SyntheticRuntimeTests/" + UUID().uuidString, isDirectory: true)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        SyntheticURLProtocol.state.reset()
    }
    override func tearDownWithError() throws {
        try? FileManager.default.removeItem(at: root)
        SyntheticURLProtocol.state.reset()
    }
    private func store() -> ReportStore {
        ReportStore(testDirectory: root) { url, maximum in
            try await BoundedReportDownload.testFetch(url, maximum: maximum, protocols: [SyntheticURLProtocol.self])
        }
    }
    private func configure(_ fixture: Fixture) {
        SyntheticURLProtocol.state.reset([
            fixture.access.v2Endpoint.path: StubReply(chunks: [fixture.encrypted]),
            ReportStore.siteRoot.appendingPathComponent(fixture.ref.path).path: StubReply(chunks: [fixture.ciphertext])
        ])
    }
    private func blobURL(_ fixture: Fixture) -> URL {
        root.appendingPathComponent("PromenadaAttachments/" + fixture.access.role + "-" + fixture.access.principal)
            .appendingPathComponent(fixture.ref.ciphertextDigest + ".bin")
    }
    private func assertProtected(_ url: URL, file: StaticString = #filePath, line: UInt = #line) throws {
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        let metadata = attributes[.protectionKey]
        // FileManager may bridge this attribute as NSString rather than the Swift wrapper.
        let protection = (metadata as? FileProtectionType)?.rawValue ?? (metadata as? String)
        let metadataType = metadata.map { String(reflecting: type(of: $0)) } ?? "<missing>"
        XCTAssertEqual(protection, FileProtectionType.complete.rawValue,
                       "Protection metadata for \(url.lastPathComponent): type=\(metadataType), raw=\(String(describing: metadata)). Simulator metadata is not physical locked-device validation.",
                       file: file, line: line)
        XCTAssertEqual(try url.resourceValues(forKeys: [.isExcludedFromBackupKey]).isExcludedFromBackup, true, file: file, line: line)
        // Simulator verifies requested attributes, not physical locked-device key eviction.
    }
    private func rejects(_ operation: () async throws -> Void, file: StaticString = #filePath, line: UInt = #line) async {
        do { try await operation(); XCTFail("Operation unexpectedly succeeded", file: file, line: line) } catch {}
    }
    private func waitForGate(_ gate: DelayedBytes) async throws {
        for _ in 0..<200 {
            if await gate.arrived { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        throw SyntheticFailure.timeout
    }

    func testBoundedTransportRejectsOversizeStatusCrossOriginAndRedirects() async throws {
        let url = ReportStore.siteRoot.appendingPathComponent("attachments/" + String(repeating: "a", count: 64) + ".bin")
        SyntheticURLProtocol.state.reset([url.path: StubReply(chunks: [Data([1, 2]), Data([3, 4])])])
        let bytes = try await BoundedReportDownload.testFetch(url, maximum: 4, protocols: [SyntheticURLProtocol.self])
        XCTAssertEqual(bytes, Data([1, 2, 3, 4]))
        SyntheticURLProtocol.state.reset([url.path: StubReply(chunks: [Data([1, 2]), Data([3, 4, 5])])])
        await rejects { _ = try await BoundedReportDownload.testFetch(url, maximum: 4, protocols: [SyntheticURLProtocol.self]) }
        SyntheticURLProtocol.state.reset([url.path: StubReply(chunks: [], declaredLength: 5)])
        await rejects { _ = try await BoundedReportDownload.testFetch(url, maximum: 4, protocols: [SyntheticURLProtocol.self]) }
        for status in [302, 403, 404, 500] {
            SyntheticURLProtocol.state.reset([url.path: StubReply(status: status)])
            await rejects { _ = try await BoundedReportDownload.testFetch(url, maximum: 4, protocols: [SyntheticURLProtocol.self]) }
        }
        for destination in [ReportStore.siteRoot.appendingPathComponent("other.bin"), URL(string: "https://example.invalid/forbidden")!] {
            SyntheticURLProtocol.state.reset([url.path: StubReply(redirect: destination)])
            await rejects { _ = try await BoundedReportDownload.testFetch(url, maximum: 4, protocols: [SyntheticURLProtocol.self]) }
            XCTAssertEqual(SyntheticURLProtocol.state.requests, [url.path])
        }
        SyntheticURLProtocol.state.reset()
        await rejects { _ = try await BoundedReportDownload.testFetch(URL(string: "https://example.invalid/forbidden")!, maximum: 4, protocols: [SyntheticURLProtocol.self]) }
        XCTAssertTrue(SyntheticURLProtocol.state.requests.isEmpty)
    }

    func testReport404IsOnlyNetworkDowngradeAndV2RequiresSchema2() async throws {
        let f = Self.legacy
        SyntheticURLProtocol.state.reset([f.access.v2Endpoint.path: StubReply(chunks: [f.encrypted])])
        await rejects { _ = try await self.store().load(access: f.access) }
        XCTAssertEqual(SyntheticURLProtocol.state.requests, [f.access.v2Endpoint.path])
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("last-report.v2.enc.json").path))
        SyntheticURLProtocol.state.reset([f.access.v2Endpoint.path: StubReply(status: 500), f.access.endpoint.path: StubReply(chunks: [f.encrypted])])
        await rejects { _ = try await self.store().load(access: f.access) }
        XCTAssertEqual(SyntheticURLProtocol.state.requests, [f.access.v2Endpoint.path])
        SyntheticURLProtocol.state.reset([f.access.v2Endpoint.path: StubReply(status: 404), f.access.endpoint.path: StubReply(chunks: [f.encrypted])])
        let result = try await store().load(access: f.access)
        XCTAssertFalse(result.offline); XCTAssertEqual(result.text, f.text)
        XCTAssertEqual(SyntheticURLProtocol.state.requests, [f.access.v2Endpoint.path, f.access.endpoint.path])
    }

    func testEncryptedCacheRoundtripProtectionAndOfflineOpen() async throws {
        let f = Self.parent; configure(f)
        let reader = store()
        let report = try await reader.load(access: f.access)
        XCTAssertFalse(report.offline)
        let attachment = try await reader.attachment(f.request, access: f.access)
        XCTAssertEqual(attachment.bytes, f.plaintext)
        let snapshot = root.appendingPathComponent("last-report.v2.enc.json"), blob = blobURL(f)
        XCTAssertEqual(try Data(contentsOf: snapshot), f.encrypted)
        XCTAssertEqual(try Data(contentsOf: blob), f.ciphertext)
        XCTAssertNil(try Data(contentsOf: blob).range(of: f.plaintext))
        try assertProtected(snapshot); try assertProtected(blob); try assertProtected(blob.deletingLastPathComponent())
        SyntheticURLProtocol.state.reset()
        let offlineReader = store()
        let offlineReport = try await offlineReader.load(access: f.access)
        XCTAssertTrue(offlineReport.offline)
        let cachedAttachment = try await offlineReader.attachment(f.request, access: f.access)
        XCTAssertEqual(cachedAttachment.bytes, f.plaintext)
        XCTAssertEqual(SyntheticURLProtocol.state.requests, [f.access.v2Endpoint.path])
        await offlineReader.clear()
        XCTAssertFalse(FileManager.default.fileExists(atPath: snapshot.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: blob.path))
    }

    func testLegacyCacheMigrationAndUncachedOfflineAttachment() async throws {
        let old = Self.legacy, current = Self.parent
        let legacyURL = root.appendingPathComponent("last-report.enc.json")
        try old.encrypted.write(to: legacyURL, options: [.atomic, .completeFileProtection])
        let reader = store()
        let cached = try await reader.cached(access: old.access)
        XCTAssertEqual(cached, old.text)
        configure(current); _ = try await reader.load(access: current.access)
        XCTAssertEqual(try Data(contentsOf: legacyURL), old.encrypted)
        SyntheticURLProtocol.state.reset()
        await rejects { _ = try await reader.attachment(current.request, access: current.access) }
        XCTAssertFalse(FileManager.default.fileExists(atPath: blobURL(current).path))
    }

    func testCorruptEncryptedCacheIsRevalidatedAndReplaced() async throws {
        let f = Self.parent; configure(f)
        let reader = store(); _ = try await reader.load(access: f.access)
        _ = try await reader.attachment(f.request, access: f.access)
        var bad = f.ciphertext
        // CryptoKit Data slices need not start at index zero.
        bad[bad.startIndex] ^= 1
        try bad.write(to: blobURL(f), options: [.atomic, .completeFileProtection])
        configure(f)
        let recovered = try await reader.attachment(f.request, access: f.access)
        XCTAssertEqual(recovered.bytes, f.plaintext)
        XCTAssertEqual(try Data(contentsOf: blobURL(f)), f.ciphertext)
        XCTAssertEqual(SyntheticURLProtocol.state.requests, [ReportStore.siteRoot.appendingPathComponent(f.ref.path).path])
    }

    func testClearDuringLateAttachmentCannotRecreateCache() async throws {
        let f = Self.parent, gate = DelayedBytes(), envelope = Self.parent.encrypted
        let reader = ReportStore(testDirectory: root) { url, _ in
            if url.path.hasSuffix(".json") { return envelope }
            return await gate.wait()
        }
        _ = try await reader.load(access: f.access)
        let pending = Task { try await reader.attachment(f.request, access: f.access) }
        defer { pending.cancel(); Task { await gate.release(f.ciphertext) } }
        try await waitForGate(gate)
        await reader.clear(); await gate.release(f.ciphertext)
        await rejects { _ = try await pending.value }
        XCTAssertFalse(FileManager.default.fileExists(atPath: blobURL(f).path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: root.appendingPathComponent("last-report.v2.enc.json").path))
        await rejects { _ = try await reader.attachment(f.request, access: f.access) }
    }

    func testCancellationDuringLateAttachmentCannotWriteCache() async throws {
        let f = Self.parent, gate = DelayedBytes(), envelope = Self.parent.encrypted
        let reader = ReportStore(testDirectory: root) { url, _ in
            if url.path.hasSuffix(".json") { return envelope }
            return await gate.wait()
        }
        _ = try await reader.load(access: f.access)
        let pending = Task { try await reader.attachment(f.request, access: f.access) }
        defer { pending.cancel(); Task { await gate.release(f.ciphertext) } }
        try await waitForGate(gate); pending.cancel(); await gate.release(f.ciphertext)
        await rejects { _ = try await pending.value }
        XCTAssertFalse(FileManager.default.fileExists(atPath: blobURL(f).path))
    }

    func testStudentIsolationAndChangedAccountRejectLateParentAttachment() async throws {
        let p = Self.parent, s = Self.student, gate = DelayedBytes()
        let parentEnvelope = p.encrypted, studentEnvelope = s.encrypted
        let reader = ReportStore(testDirectory: root) { url, _ in
            if url.path.contains("/students/") { return studentEnvelope }
            if url.path.hasSuffix(".json") { return parentEnvelope }
            return await gate.wait()
        }
        _ = try await reader.load(access: p.access)
        await rejects { _ = try await reader.attachment(s.request, access: s.access) }
        let pending = Task { try await reader.attachment(p.request, access: p.access) }
        defer { pending.cancel(); Task { await gate.release(p.ciphertext) } }
        try await waitForGate(gate)
        let student = try await reader.load(access: s.access)
        XCTAssertEqual(student.text, s.text)
        await gate.release(p.ciphertext)
        await rejects { _ = try await pending.value }
        XCTAssertFalse(FileManager.default.fileExists(atPath: blobURL(p).path))
        await rejects { _ = try await reader.attachment(p.request, access: p.access) }
        await rejects { _ = try await reader.cached(access: JournalAccess(role: "student", login: s.access.login, password: "wrong")) }
    }

    @MainActor
    func testNativeModelLegacyAndV2SharingCleanupAndLogout() async throws {
        let f = Self.parent; configure(f)
        let reader = store(); _ = try await reader.load(access: f.access)
        let model = JournalModel(testStore: reader); model.testInstallAccess(f.access)
        defer { model.removeShare() }
        model.testReceiveAttachment(["name": "../legacy-demo.txt", "base64": f.plaintext.base64EncodedString()])
        let legacyURL = try XCTUnwrap(model.attachment?.url)
        XCTAssertEqual(legacyURL.lastPathComponent, "legacy-demo.txt")
        XCTAssertEqual(try Data(contentsOf: legacyURL), f.plaintext); try assertProtected(legacyURL)
        model.testReceiveAttachment(f.body)
        await model.testPendingAttachment()?.value
        let modernURL = try XCTUnwrap(model.attachment?.url)
        XCTAssertEqual(modernURL.lastPathComponent, "synthetic-demo.txt")
        XCTAssertEqual(try Data(contentsOf: modernURL), f.plaintext); try assertProtected(modernURL)
        XCTAssertFalse(FileManager.default.fileExists(atPath: legacyURL.path))
        model.removeShare(); XCTAssertNil(model.attachment)
        XCTAssertFalse(FileManager.default.fileExists(atPath: modernURL.path))
        model.testReceiveAttachment(f.body); await model.testPendingAttachment()?.value
        XCTAssertNotNil(model.attachment)
        model.forget()
        for _ in 0..<200 { if !model.busy { break }; try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertFalse(model.busy); XCTAssertFalse(model.open); XCTAssertNil(model.attachment)
        XCTAssertFalse(FileManager.default.fileExists(atPath: modernURL.path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: blobURL(f).path))
    }

    @MainActor
    func testNativeModelLogoutSuppressesLateShareAndCache() async throws {
        let f = Self.parent, gate = DelayedBytes(), envelope = Self.parent.encrypted
        let reader = ReportStore(testDirectory: root) { url, _ in
            if url.path.hasSuffix(".json") { return envelope }
            return await gate.wait()
        }
        _ = try await reader.load(access: f.access)
        let model = JournalModel(testStore: reader); model.testInstallAccess(f.access)
        defer { model.removeShare(); Task { await gate.release(f.ciphertext) } }
        model.testReceiveAttachment(f.body)
        let completion = model.testPendingAttachment()
        try await waitForGate(gate)
        model.forget(); await gate.release(f.ciphertext); await completion?.value
        for _ in 0..<200 { if !model.busy { break }; try await Task.sleep(for: .milliseconds(10)) }
        XCTAssertFalse(model.open); XCTAssertFalse(model.busy); XCTAssertNil(model.attachment)
        XCTAssertFalse(FileManager.default.fileExists(atPath: blobURL(f).path))
        XCTAssertFalse(FileManager.default.fileExists(atPath: FileManager.default.temporaryDirectory.appendingPathComponent("PromenadaShare").path))
    }
}
