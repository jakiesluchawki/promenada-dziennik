import Foundation
import CryptoKit

// Synthetic-only command-line contract tests. run-attachment-contract-tests.sh
// compiles the production helpers directly, without an app or a network request.
private struct ContractFailure: Error { let message: String }
private func require(_ condition: @autoclosure () throws -> Bool, _ message: String) throws {
    if try !condition() { throw ContractFailure(message: message) }
}
private func reject(_ message: String, _ work: () throws -> Void) throws {
    var rejected = false
    do { try work() } catch { rejected = true }
    try require(rejected, message)
}
private func reportText(_ report: [String: Any]) throws -> String {
    String(data: try JSONSerialization.data(withJSONObject: report), encoding: .utf8)!
}

@main
struct AttachmentV2ContractTests {
    static func main() throws {
        guard CommandLine.arguments.count == 2 else { throw ContractFailure(message: "Supply the synthetic fixture JSON path") }
        let data = try Data(contentsOf: URL(fileURLWithPath: CommandLine.arguments[1]))
        let vectors = try JSONSerialization.jsonObject(with: data) as! [[String: Any]]
        var checked = 0
        for vector in vectors {
            let report = vector["report"] as! [String: Any]
            let audience = report["audience"] as! String
            let access = JournalAccess(role: audience, login: vector["login"] as? String ?? "", password: "synthetic-only")
            let accounts = report["accounts"] as! [String: [String: Any]]
            let accountKey = vector["account_key"] as! String
            let source = vector["kind"] as! String
            let message = (accounts[accountKey]![source] as! [[String: Any]])[0]
            let attachment = (message["attachments"] as! [[String: Any]])[vector["attachment_index"] as! Int]
            let reference = attachment["encrypted_attachment"] as! [String: Any]
            var body: [String: Any] = ["action": "attachment", "name": attachment["name"]!,
                "accountKey": accountKey, "source": source, "messageId": vector["message_id"]!,
                "attachmentIndex": vector["attachment_index"]!, "ref": reference,
                "scope": ["audience": audience, "principal": report["principal"]!]]
            let text = try reportText(report)
            let request = try NativeAttachmentRequest.parse(body)
            let authorized = try AuthorizedAttachment.resolve(request, reportText: text, access: access)
            try require(authorized.aad == Data(base64Encoded: vector["expected_aad_base64"] as! String)!, "Cross-language AAD bytes differ")
            let ciphertext = Data(base64Encoded: vector["ciphertext_base64"] as! String)!
            let plaintext = Data(base64Encoded: vector["expected_plaintext_base64"] as! String)!
            try require(try authorized.ref.decrypt(ciphertext, aad: authorized.aad) == plaintext, "Cross-language decryption differs")
            try require(ciphertext.count == authorized.ref.paddedSize + 16, "Padding length differs")
            try reject("Truncated ciphertext was accepted") { _ = try authorized.ref.decrypt(ciphertext.dropLast(), aad: authorized.aad) }
            var modified = ciphertext; modified[0] ^= 1
            try reject("Corrupt ciphertext was accepted") { _ = try authorized.ref.decrypt(modified, aad: authorized.aad) }
            try reject("Cross-context AAD was accepted") { _ = try authorized.ref.decrypt(ciphertext, aad: Data("other context".utf8)) }
            for (field, value) in [("accountKey", "other"), ("source", "timetable"), ("messageId", "other"), ("name", "other.bin")] {
                var changed = body; changed[field] = value
                try reject("Bridge field substitution was accepted: " + field) {
                    _ = try AuthorizedAttachment.resolve(NativeAttachmentRequest.parse(changed), reportText: text, access: access)
                }
            }
            for badIndex in [true, -1, 1.5, 100] as [Any] {
                var changed = body; changed["attachmentIndex"] = badIndex
                try reject("Invalid attachment index was accepted") {
                    _ = try AuthorizedAttachment.resolve(NativeAttachmentRequest.parse(changed), reportText: text, access: access)
                }
            }
            for badPath in ["../report.enc.json", "attachments/" + String(repeating: "a", count: 64) + ".bin?key=x",
                            "https://example.invalid/file", "attachments/" + String(repeating: "A", count: 64) + ".bin",
                            "attachments/" + String(repeating: "a", count: 64) + "\n.bin"] {
                var changed = reference; changed["path"] = badPath
                try reject("Unsafe attachment path was accepted") {
                    let ref = try JSONDecoder().decode(EncryptedAttachment.self, from: JSONSerialization.data(withJSONObject: changed))
                    try ref.validate()
                }
            }
            for badSize in [true, -1, 1.5, 8_000_001] as [Any] {
                var changed = reference; changed["size"] = badSize
                try reject("Invalid attachment size was accepted") {
                    let ref = try JSONDecoder().decode(EncryptedAttachment.self, from: JSONSerialization.data(withJSONObject: changed))
                    try ref.validate()
                }
            }
            for field in ["key", "iv", "sha256", "path"] {
                var changed = reference
                changed[field] = field == "path" ? "attachments/" + String(repeating: "0", count: 64) + ".bin" : "invalid"
                var changedBody = body; changedBody["ref"] = changed
                try reject("Untrusted bridge reference was accepted") {
                    _ = try AuthorizedAttachment.resolve(NativeAttachmentRequest.parse(changedBody), reportText: text, access: access)
                }
            }
            var extraReference = reference; extraReference["unexpected"] = "rejected"
            var extraBody = body; extraBody["ref"] = extraReference
            try reject("Unknown bridge reference field was accepted") { _ = try NativeAttachmentRequest.parse(extraBody) }
            var extraAttachment = attachment; extraAttachment["encrypted_attachment"] = extraReference
            var extraMessage = message; extraMessage["attachments"] = [extraAttachment]
            var extraAccount = accounts[accountKey]!; extraAccount[source] = [extraMessage]
            var extraAccounts = accounts; extraAccounts[accountKey] = extraAccount
            var extraReport = report; extraReport["accounts"] = extraAccounts
            try reject("Unknown authenticated reference field was accepted") {
                _ = try AuthorizedAttachment.resolve(request, reportText: reportText(extraReport), access: access)
            }
            body["scope"] = ["audience": "parent", "principal": "another"]
            try reject("Untrusted principal was accepted") {
                _ = try AuthorizedAttachment.resolve(NativeAttachmentRequest.parse(body), reportText: text, access: access)
            }
            var duplicateReport = report, duplicateAccounts = accounts, duplicateAccount = accounts[accountKey]!
            duplicateAccount[source] = [message, message]
            duplicateAccounts[accountKey] = duplicateAccount; duplicateReport["accounts"] = duplicateAccounts
            try reject("Ambiguous duplicate source was accepted") { try access.validate(reportText(duplicateReport)) }
            var wrongKindMessage = message; wrongKindMessage["kind"] = "other"
            duplicateAccount[source] = [wrongKindMessage]
            duplicateAccounts[accountKey] = duplicateAccount; duplicateReport["accounts"] = duplicateAccounts
            try reject("Wrong collection kind was accepted") { try access.validate(reportText(duplicateReport)) }
            var badReport = report; badReport["schema"] = true
            try reject("Boolean schema was accepted") { try access.validate(reportText(badReport)) }
            checked += 1
        }
        try require(!ReportCipher.acceptsSchema(1, requiresSchema2: true), "Live v2 endpoint accepted schema1")
        try require(ReportCipher.acceptsSchema(2, requiresSchema2: true), "Live v2 endpoint rejected schema2")
        try require(ReportCipher.acceptsSchema(1), "Legacy transport/cache migration rejected schema1")
        try require(!ReportCipher.acceptsSchema(true), "Boolean schema was accepted")
        let parent = JournalAccess(role: "parent", login: "", password: "synthetic-only")
        for schema in [1, 2] { try parent.validate(reportText(["schema": schema, "accounts": ["demo": ["child": "demo", "role": "parent"]]])) }
        for (size, padded) in [(0, 65_536), (1, 65_536), (65_536, 65_536), (65_537, 131_072), (8_000_000, 8_000_000)] {
            let ref = EncryptedAttachment(v: 1, path: "attachments/" + String(repeating: "0", count: 64) + ".bin",
                key: Data(repeating: 0, count: 32).base64EncodedString(), iv: Data(repeating: 0, count: 12).base64EncodedString(),
                sha256: String(repeating: "0", count: 64), size: size)
            try ref.validate(); try require(ref.paddedSize == padded, "Padding boundary failed")
        }
        print("PASS: \(checked) synthetic Swift AAD/decryption vectors, bridge tampering, limits, padding and schema checks")
        print("This helper check does not validate an iOS app build, protected files, lifecycle or UI behavior.")
    }
}
