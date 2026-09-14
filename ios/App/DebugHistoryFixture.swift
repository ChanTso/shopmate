#if DEBUG
import Foundation

enum HistoryUITestFixture {
    @MainActor
    static func makeModel() -> BuyerModel {
        let suite = "io.shopmate.history-interaction-test"
        let defaults = UserDefaults(suiteName: suite)!
        defaults.removePersistentDomain(forName: suite)
        let storage = BuyerStorage(defaults: defaults)
        storage.endpoint = "https://history-ui.invalid"
        storage.owner = "ui-fixture"
        storage.conversation = "history-ui"
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [HistoryUITestProtocol.self]
        let model = BuyerModel(api: BuyerAPI(session: URLSession(configuration: configuration)), storage: storage)
        model.signedIn = true
        model.tab = 1
        model.selectConversation("history-ui")
        return model
    }
}

/// Fixed HTTP responses for touch tests; all requests from this session stay in-process.
private final class HistoryUITestProtocol: URLProtocol {
    private static let queue = DispatchQueue(label: "io.shopmate.history-ui-http")
    private static var failedEarlier = false
    private static var status = "completed"
    private static var items: [Object] = (1...70).map { id in
        let note = "第 \(id) 条：比较容量、清洁方式和占地，再选择适合日常的咖啡器具。"
        let details = [
            "早晨两个人使用，不必为偶尔来客选择过大的容量。",
            "可拆洗的滤篮更容易维护，也要考虑橱柜下方的高度。",
            "提前量好台面深度和插座位置，预算里留出耗材费用。"
        ]
        let content = ([note] + Array(details.prefix(id % 3))).joined(separator: "\n")
        if id % 2 == 1 { return ["message_id": id, "kind": "user", "text": content] }
        return ["message_id": id, "kind": "assistant", "turn": id / 2,
                "segments": [["type": "text", "text": content]], "suggestions": [], "pending": false]
    }
    private var cancelled = false
    private var scheduled: [DispatchWorkItem] = []
    private var streaming = false
    private var completed = false
    private var receivedText = ""
    private var cardFinal = false
    private var cardVisible = false

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        Self.queue.async { self.startResponse() }
    }

    override func stopLoading() {
        Self.queue.async {
            self.cancelled = true
            self.scheduled.forEach { $0.cancel() }
            self.scheduled.removeAll()
            if self.streaming && !self.completed { self.saveReply(status: "interrupted") }
        }
    }

    private func startResponse() {
        guard !cancelled, let url = request.url, url.host == "history-ui.invalid" else {
            client?.urlProtocol(self, didFailWithError: URLError(.unsupportedURL))
            return
        }
        switch url.path {
        case "/api/buyer/conversations/history-ui/messages":
            let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
            let before = query.first(where: { $0.name == "before" }).flatMap { Int($0.value ?? "") }
            let limit = min(100, max(1, query.first(where: { $0.name == "limit" }).flatMap { Int($0.value ?? "") } ?? 30))
            if before != nil && ProcessInfo.processInfo.arguments.contains("--history-page-failure-once") && !Self.failedEarlier {
                Self.failedEarlier = true
                schedule(after: 5) { request in request.reply(["detail": "Earlier history temporarily unavailable"], status: 503) }
            } else {
                let eligible = Self.items.filter { before == nil || ($0["message_id"] as! Int) < before! }
                let page = Array(eligible.suffix(limit))
                let next: Any = eligible.count > limit ? page[0]["message_id"]! : NSNull()
                let response: Object = ["session_id": "history-ui", "status": Self.status,
                                        "items": page, "next_before": next]
                schedule(after: before == nil ? 0.05 : (ProcessInfo.processInfo.arguments.contains("--history-page-wait-for-drag") ? 12 : 5)) { request in request.reply(response) }
            }
        case "/api/buyer/conversations/history-ui/chat":
            startStream()
        case "/api/buyer/products":
            reply(["products": [], "next_offset": NSNull()])
        case "/api/buyer/conversations":
            reply(["sessions": [["session_id": "history-ui", "title": "咖啡器具选购记录"]]])
        case "/api/buyer/cart": reply(["quote": [:]])
        case "/api/buyer/checkouts": reply(["checkouts": []])
        case "/api/buyer/orders": reply(["orders": []])
        case "/api/buyer/actions": reply(["actions": []])
        case "/api/buyer/commands": reply(["commands": []])
        default: reply(["detail": "Unexpected UI fixture request"], status: 404)
        }
    }

    private func schedule(after delay: TimeInterval, _ action: @escaping (HistoryUITestProtocol) -> Void) {
        let work = DispatchWorkItem { [weak self] in
            guard let self, !self.cancelled else { return }
            action(self)
        }
        scheduled.append(work)
        Self.queue.asyncAfter(deadline: .now() + delay, execute: work)
    }

    private func response(status: Int, type: String) {
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: status,
            httpVersion: "HTTP/1.1", headerFields: ["Content-Type": type, "Cache-Control": "no-store"])!, cacheStoragePolicy: .notAllowed)
    }

    private func reply(_ body: Object, status: Int = 200) {
        response(status: status, type: "application/json")
        client?.urlProtocol(self, didLoad: try! JSONSerialization.data(withJSONObject: body))
        client?.urlProtocolDidFinishLoading(self)
    }

    private var card: Object {
        ["component": "products", "stream_id": "history-ui-product", "payload": [
            "title": "适合日常的选择", "items": [["product": [
                "product_id": "AR-1001", "title": "十二杯定时滴滤咖啡机", "price": 79.6,
                "in_stock": true, "category": "home-kitchen"
            ], "reason": "适合多人日常饮用，先确认台面空间。"]]
        ]]
    }

    private func frame(_ type: String, _ payload: Object) {
        let json = String(decoding: try! JSONSerialization.data(withJSONObject: payload), as: UTF8.self)
        client?.urlProtocol(self, didLoad: Data("event: \(type)\ndata: \(json)\n\n".utf8))
    }

    private func startStream() {
        guard Self.items.count == 70 else { reply(["detail": "This fixture has one new reply"], status: 409); return }
        streaming = true
        Self.status = "running"
        Self.items.append(["message_id": 71, "kind": "user", "text": "Help me choose a coffee maker."])
        Self.items.append(["message_id": 72, "kind": "assistant", "segments": [], "pending": true])
        response(status: 200, type: "text/event-stream")
        frame("turn_started", ["session_id": "history-ui", "user_message_id": 71, "assistant_message_id": 72])
        schedule(after: 0.1) { request in request.cardVisible = true; request.frame("ui_partial", request.card) }
        schedule(after: 2) { request in request.cardFinal = true; request.frame("ui", request.card) }
        let answer = "先从日常使用人数和台面空间开始。两个人每天一到两杯，可以优先看紧凑、容易拆洗的机型；如果经常与家人分享，较大的滴滤容量会更方便。选择之前，量一下机器上方打开水箱需要的空间，也留意电源线与插座的位置。清洁方面，滤篮和水箱能否拆下，比只看外观更重要。咖啡浓度还会受到豆子、研磨和水量影响，不必把所有差别都归因于机器。预算里可以留出滤纸、清洁用品和第一袋咖啡豆的费用。对于这款定时滴滤咖啡机，优势是一次能做多杯，取舍是它不适合追求浓缩咖啡的小容量方案。你可以继续阅读前面的比较记录，我会接着整理建议；确认商品与当前报价以后，再决定下一步。"
        let characters = Array(answer)
        let fragments = stride(from: 0, to: characters.count, by: 10).map {
            String(characters[$0..<min($0 + 10, characters.count)])
        }
        for (index, fragment) in fragments.enumerated() {
            schedule(after: Double(index + 1) * 120 / Double(fragments.count)) { request in
                request.receivedText += fragment
                request.frame("text_delta", ["text": fragment])
            }
        }
        schedule(after: 120.2) { request in
            request.completed = true
            request.saveReply(status: "completed")
            request.frame("turn_complete", [:])
            request.client?.urlProtocolDidFinishLoading(request)
        }
    }

    private func saveReply(status: String) {
        Self.status = status
        var segments: [Object] = []
        if cardVisible { segments.append(["type": "ui", "slotKey": "history-ui-product",
                                          "status": cardFinal ? "final" : "partial", "block": card]) }
        if !receivedText.isEmpty { segments.append(["type": "text", "text": receivedText]) }
        Self.items[Self.items.count - 1] = ["message_id": 72, "kind": "assistant",
                                          "segments": segments, "suggestions": [], "pending": false]
    }
}
#endif
