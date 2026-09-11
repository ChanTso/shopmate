import Foundation

struct BuyerFailure: LocalizedError {
    let status: Int
    let category: String
    let message: String
    var errorDescription: String? { message }
}

typealias Object = [String: Any]
func text(_ object: Object, _ key: String) -> String { object[key] as? String ?? "" }
func rows(_ object: Object, _ key: String) -> [Object] { object[key] as? [Object] ?? [] }
func object(_ value: Object, _ key: String) -> Object { value[key] as? Object ?? [:] }
func jsonData(_ value: Any) throws -> Data { try JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) }
func jsonText(_ value: Any) throws -> String { String(decoding: try jsonData(value), as: UTF8.self) }
func jsonObject(_ data: Data) throws -> Object {
    guard let value = try JSONSerialization.jsonObject(with: data) as? Object else {
        throw BuyerFailure(status: 502, category: "", message: "响应格式不正确，请刷新核对")
    }
    return value
}
func money(_ minor: Any?, currency: String = "CNY") -> String {
    guard let number = minor as? NSNumber else { return "—" }
    return (currency == "CNY" ? "¥" : currency + " ") + String(format: "%.2f", number.doubleValue / 100)
}
func majorMoney(_ value: Any?) -> String {
    guard let number = value as? NSNumber else { return "—" }
    return String(format: "¥%.2f", number.doubleValue)
}

@MainActor
final class BuyerAPI {
    var root = "http://localhost:8101"
    var commerceRoot = "http://localhost:9082"
    var token: String?
    private let session: URLSession

    init(session: URLSession? = nil) {
        self.session = session ?? Self.makeSession()
    }

    private static func makeSession() -> URLSession {
        let configuration = URLSessionConfiguration.default
        configuration.timeoutIntervalForRequest = 60
        configuration.timeoutIntervalForResource = 600
        return URLSession(configuration: configuration)
    }

    static func serviceRoot(_ value: String) throws -> String {
        let raw = value.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let url = URL(string: raw), let host = url.host,
              url.user == nil, url.password == nil, url.query == nil, url.fragment == nil,
              url.path.isEmpty, url.scheme == "https" || (url.scheme == "http" && localHost(host)) else {
            throw BuyerFailure(status: 400, category: "", message: "请输入 HTTPS 服务地址；本机可用 localhost")
        }
        return raw
    }
    private static func localHost(_ host: String) -> Bool {
        if ["localhost", "127.0.0.1", "::1"].contains(host) { return true }
        #if DEBUG
        return host.hasSuffix(".local")
        #else
        return false
        #endif
    }
    func setRoot(_ value: String) throws { root = try Self.serviceRoot(value) }
    func setCommerceRoot(_ value: String) throws { commerceRoot = try Self.serviceRoot(value) }


    func request(_ path: String, body: Object? = nil, method: String? = nil) throws -> URLRequest {
        guard let url = URL(string: root + "/api/buyer" + path) else {
            throw BuyerFailure(status: 400, category: "", message: "服务地址无效")
        }
        var request = URLRequest(url: url)
        if let token { request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization") }
        if let body {
            request.httpMethod = "POST"
            request.httpBody = try jsonData(body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        if let method { request.httpMethod = method }
        return request
    }

    func failure(_ response: HTTPURLResponse, data: Data = Data()) -> BuyerFailure {
        let value = (try? jsonObject(data)) ?? [:]
        let message = response.statusCode == 401 ? "登录已过期，请重新登录" : text(value, "detail")
        return BuyerFailure(status: response.statusCode, category: text(value, "category"),
                            message: message.isEmpty ? "请求未完成，请刷新核对（\(response.statusCode)）" : message)
    }

    func call(_ path: String, body: Object? = nil, method: String? = nil) async throws -> Object {
        let origin = root, identity = token
        let (data, response) = try await session.data(for: request(path, body: body, method: method))
        try Task.checkCancellation()
        guard root == origin, token == identity else { throw CancellationError() }
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        guard (200..<300).contains(http.statusCode) else { throw failure(http, data: data) }
        return try jsonObject(data)
    }

    func seckill(_ path: String, body: Object? = nil, key: String? = nil) async throws -> Object {
        guard let url = URL(string: commerceRoot + "/api" + path) else { throw URLError(.badURL) }
        var request = URLRequest(url: url)
        if let token { request.setValue("Bearer " + token, forHTTPHeaderField: "Authorization") }
        if let key { request.setValue(key, forHTTPHeaderField: "Idempotency-Key") }
        if let body {
            request.httpMethod = "POST"; request.httpBody = try jsonData(body)
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        }
        let origin = commerceRoot, identity = token
        let (data, response) = try await session.data(for: request)
        try Task.checkCancellation()
        guard commerceRoot == origin, token == identity else { throw CancellationError() }
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        let value = try jsonObject(data)
        let rejected = key != nil && http.statusCode == 409 && text(value, "state") == "REJECTED" && !text(value, "reservationId").isEmpty
        guard (200..<300).contains(http.statusCode) || rejected else { throw failure(http, data: data) }
        return value
    }

    func stream(_ path: String, body: Object, line: (String) throws -> Void) async throws {
        let (bytes, response) = try await session.bytes(for: request(path, body: body))
        guard let http = response as? HTTPURLResponse else { throw URLError(.badServerResponse) }
        guard (200..<300).contains(http.statusCode) else { throw failure(http) }
        // Foundation AsyncLineSequence drops empty lines, which are SSE frame boundaries.
        var lines = StreamLines()
        for try await byte in bytes {
            try Task.checkCancellation()
            if let value = try lines.accept(byte) { try line(value) }
        }
        if let value = try lines.finish() { try line(value) }
    }
}

struct StreamLines {
    private var buffer = Data()
    mutating func accept(_ byte: UInt8) throws -> String? {
        if byte != 10 { buffer.append(byte); return nil }
        if buffer.last == 13 { buffer.removeLast() }
        let result = try decode()
        buffer.removeAll(keepingCapacity: true)
        return result
    }
    mutating func finish() throws -> String? {
        guard !buffer.isEmpty else { return nil }
        let result = try decode(); buffer.removeAll(); return result
    }
    private func decode() throws -> String {
        guard let value = String(data: buffer, encoding: .utf8) else { throw URLError(.cannotDecodeContentData) }
        return value
    }
}
