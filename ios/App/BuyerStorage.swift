import Foundation
import Security
import CryptoKit
import BuyerCore

struct StorageFailure: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

final class BuyerStorage {
    private let defaults: UserDefaults
    init(defaults: UserDefaults = .standard) { self.defaults = defaults }
    var endpoint: String {
        get { defaults.string(forKey: "endpoint") ?? "http://localhost:8101" }
        set { defaults.set(newValue, forKey: "endpoint") }
    }
    var owner: String {
        get { defaults.string(forKey: "owner") ?? "" }
        set { defaults.set(newValue, forKey: "owner") }
    }
    private var scope: String {
        SHA256.hash(data: Data((endpoint + "|" + owner).utf8)).map { String(format: "%02x", $0) }.joined()
    }
    private var keyQuery: [String: Any] {
        [kSecClass as String: kSecClassGenericPassword, kSecAttrService as String: "io.shopmate.buyer",
         kSecAttrAccount as String: scope]
    }
    func token() throws -> String? {
        var query = keyQuery
        query[kSecReturnData as String] = true
        var value: CFTypeRef?
        let status = SecItemCopyMatching(query as CFDictionary, &value)
        if status == errSecItemNotFound { return nil }
        guard status == errSecSuccess, let data = value as? Data else {
            throw StorageFailure(message: "无法读取登录凭证，请重新登录")
        }
        return String(decoding: data, as: UTF8.self)
    }
    func saveToken(_ token: String) throws {
        let value = Data(token.utf8)
        let update = SecItemUpdate(keyQuery as CFDictionary, [kSecValueData: value] as CFDictionary)
        if update == errSecSuccess { return }
        guard update == errSecItemNotFound else { throw StorageFailure(message: "无法保存登录凭证") }
        var query = keyQuery
        query[kSecValueData as String] = value
        query[kSecAttrAccessible as String] = kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly
        guard SecItemAdd(query as CFDictionary, nil) == errSecSuccess else { throw StorageFailure(message: "无法保存登录凭证") }
    }
    func logout() throws {
        let result = SecItemDelete(keyQuery as CFDictionary)
        guard result == errSecSuccess || result == errSecItemNotFound else { throw StorageFailure(message: "无法清除登录凭证") }
        owner = ""
    }
    var conversation: String? {
        get { defaults.string(forKey: scope + ".conversation") }
        set { defaults.set(newValue, forKey: scope + ".conversation") }
    }
    private func pendingURL() throws -> URL {
        let folder = try FileManager.default.url(for: .applicationSupportDirectory, in: .userDomainMask, appropriateFor: nil, create: true)
        return folder.appendingPathComponent(scope + "-pending.json")
    }
    func pending() throws -> [PendingWrite] {
        let url = try pendingURL()
        guard FileManager.default.fileExists(atPath: url.path) else { return [] }
        let values = try JSONDecoder().decode([String].self, from: Data(contentsOf: url))
        return try values.map { try WriteRecovery.shared.decode(payload: $0) }
    }
    func savePending(_ values: [PendingWrite]) throws {
        let data = try JSONEncoder().encode(values.map { WriteRecovery.shared.encode(pending: $0) })
        try data.write(to: pendingURL(), options: [.atomic, .completeFileProtectionUntilFirstUserAuthentication])
    }
}
