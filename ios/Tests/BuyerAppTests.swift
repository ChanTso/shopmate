import XCTest
import BuyerCore
@testable import ShopMate

final class BuyerAppTests: XCTestCase {
    func testByteLinesPreserveCRLFFrameBoundariesAndChinese() throws {
        var transport = StreamLines()
        let decoder = StreamDecoder()
        let timeline = ChatTimeline()
        timeline.begin(text: "查询")
        let bytes = Data("event: text_delta\r\ndata: {\"text\":\"你好\"}\r\n\r\nevent: turn_complete\ndata: {}\n\n".utf8)
        for byte in bytes {
            if let line = try transport.accept(byte), let event = try decoder.line(raw: line) { try timeline.accept(event: event) }
        }
        try decoder.finish()
        XCTAssertEqual(timeline.messages.last?.segments.last?.text, "你好")
    }
    func testTruncatedStreamDoesNotBecomeSuccess() throws {
        let decoder = StreamDecoder()
        _ = try decoder.line(raw: "event: text_delta")
        _ = try decoder.line(raw: "data: {}")
        _ = try decoder.line(raw: "")
        XCTAssertThrowsError(try decoder.finish())
    }
    func testCredentialsAndOriginalIntentAreIsolatedByBuyerAndServer() throws {
        let suite = "buyer-test-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let storage = BuyerStorage(defaults: defaults)
        storage.endpoint = "https://" + suite + ".test"
        storage.owner = "first"
        try storage.saveToken("test-token")
        let pending = try WriteRecovery.shared.prepare(key: "original", path: "/cart/add", body: "{\"productId\":\"cup\",\"quantity\":1}")
        try storage.savePending([pending])
        storage.owner = "second"
        XCTAssertNil(try storage.token())
        XCTAssertTrue(try storage.pending().isEmpty)
        storage.owner = "first"
        XCTAssertEqual(try storage.token(), "test-token")
        XCTAssertEqual(try storage.pending().first?.key, "original")
        storage.endpoint += ":8443"
        XCTAssertNil(try storage.token())
        XCTAssertTrue(try storage.pending().isEmpty)
        storage.endpoint = "https://" + suite + ".test"
        try storage.savePending([])
        try storage.logout()
    }

    @MainActor
    func testRemoteEndpointRequiresHTTPS() throws {
        let api = BuyerAPI()
        XCTAssertThrowsError(try api.setRoot("http://example.com"))
        XCTAssertThrowsError(try api.setRoot("https://user:password@example.com"))
        try api.setRoot("https://example.com/")
        XCTAssertEqual(api.root, "https://example.com")
    }
    func testSearchResultsCannotReplaceCartOrOrderSnapshots() throws {
        let cached: Object = ["product_id": "AR-1001", "title": "缓存里的旧商品名", "image_url": "/catalog.webp", "category": "home-kitchen"]
        let snapshots: [Object] = [
            ["productId": "AR-1001", "name": "购物车最新名称", "imageUrl": "/cart.webp", "totalPriceMinor": 7960],
            ["productId": "AR-1001", "title": "下单时的名称", "content": ["imageUrl": "/order.webp"], "totalPriceMinor": 7580]
        ]
        for snapshot in snapshots {
            for catalog in [[cached], []] {
                let display = productForDisplay(snapshot, catalog: catalog)
                XCTAssertEqual(ProductPresentation.title(display), ProductPresentation.title(snapshot))
                XCTAssertEqual(ProductPresentation.imageURL(display, baseURL: "https://store.example"), ProductPresentation.imageURL(snapshot, baseURL: "https://store.example"))
                XCTAssertEqual(display["totalPriceMinor"] as? Int, snapshot["totalPriceMinor"] as? Int)
            }
        }
        let missingArtwork: Object = ["productId": "AR-1001", "name": "下单时的名称"]
        let enriched = productForDisplay(missingArtwork, catalog: [cached])
        XCTAssertEqual(ProductPresentation.title(enriched), "下单时的名称")
        XCTAssertEqual(text(enriched, "image_url"), "/catalog.webp")
    }

    func testRefundAmountUsesExactMinorUnits() throws {
        XCTAssertEqual(try refundMinor("79.60"), 7960)
        XCTAssertEqual(try refundMinor("0.01"), 1)
        for value in ["0", "-1", "1.001", "1e2", "NaN", "92233720368547759"] {
            XCTAssertThrowsError(try refundMinor(value), value)
        }
    }
    func testReservationReplaysOriginalIdentityAndTerminalResult() throws {
        let original = SeckillTicket(key: "one-intent", activityId: "sale", activityVersion: 7)
        let admitted = original.result(["reservationId": "reservation", "state": "ADMITTED"])
        XCTAssertFalse(admitted.terminal)
        let completed = admitted.result(["reservationId": "reservation", "state": "ORDERED", "orderId": "order"])
        let restored = try JSONDecoder().decode(SeckillTicket.self, from: JSONEncoder().encode(completed))
        XCTAssertEqual(restored.key, original.key)
        XCTAssertEqual(restored.activityVersion, 7)
        XCTAssertEqual(restored.orderId, "order")
        XCTAssertTrue(restored.terminal)
        XCTAssertTrue(original.result(["reservationId": "r", "state": "REJECTED"]).terminal)
    }
    @MainActor
    func testDevelopmentLocalNetworkDoesNotAllowArbitraryHTTP() throws {
        let api = BuyerAPI()
        try api.setRoot("http://shopmate-mac.local:8101")
        try api.setCommerceRoot("http://shopmate-mac.local:9082")
        XCTAssertThrowsError(try api.setRoot("http://shopmate-mac.local.attacker.example"))
        XCTAssertThrowsError(try api.setRoot("http://example.com"))
        XCTAssertThrowsError(try api.setRoot("https://example.com/path"))
    }

    @MainActor
    func testLateHistoryCannotReplaceCompletedNewTurn() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        model.storage.conversation = "history-race"
        model.products = [["product_id": "test"]]
        let historyStarted = expectation(description: "old history request")
        var delayed: BuyerTestProtocol?
        BuyerTestProtocol.handle = { request in
            if request.request.url!.path.hasSuffix("/history-race") {
                DispatchQueue.main.async { delayed = request; historyStarted.fulfill() }
            } else if request.request.url!.path.hasSuffix("/chat") {
                request.reply("event: text_delta\ndata: {\"text\":\"本轮的新回答\"}\n\nevent: turn_complete\ndata: {}\n\n", type: "text/event-stream")
            } else { request.reply("{}") }
        }
        let oldLoad = model.reload()
        await fulfillment(of: [historyStarted], timeout: 3)
        model.send("继续推荐")
        try await settle { !model.chat.running }
        XCTAssertEqual(model.chat.messages.last?.segments.last?.text, "本轮的新回答")
        delayed?.reply("{\"items\":[{\"kind\":\"user\",\"text\":\"旧历史\"}]}")
        await oldLoad.value
        XCTAssertEqual(model.chat.messages.last?.segments.last?.text, "本轮的新回答")
        model.logout()
    }

    @MainActor
    func testStopCancelsNativeTransportBeforeNewConversation() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        model.storage.conversation = "cancel-test"
        let started = expectation(description: "stream started")
        let cancelled = expectation(description: "native transport cancelled")
        BuyerTestProtocol.handle = { request in
            request.onStop = { cancelled.fulfill() }
            request.startStream("event: text_delta\ndata: {\"text\":\"未完成的回答\"}\n\n")
            started.fulfill()
        }
        model.send("先查询")
        await fulfillment(of: [started], timeout: 3)
        try await settle { !model.chat.messages.last!.segments.isEmpty }
        model.stop()
        try await settle { !model.chat.running }
        await fulfillment(of: [cancelled], timeout: 3)
        model.newConversation()
        XCTAssertTrue(model.chat.messages.isEmpty)
        XCTAssertNil(model.storage.conversation)
        XCTAssertNil(model.error)
        model.logout()
    }

    @MainActor
    func testConflictingCheckoutKeepsCartAndExplainsRecovery() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        model.tab = 2
        model.quote = ["version": 24, "currency": "CNY", "subtotalMinor": 3900, "checkoutReady": true,
                       "items": [["productId": "cup", "name": "随行杯", "lineTotalMinor": 3900, "quantity": 1, "productVersion": 1, "unitPriceMinor": 3900, "currency": "CNY", "orderable": true]]]
        BuyerTestProtocol.handle = { request in
            request.reply("{\"category\":\"stale_cart\",\"detail\":\"Shopping request conflicts with current business state\"}", status: 409)
        }
        model.confirmCheckout()
        try XCTUnwrap(model.confirmation).action()
        try await settle { !model.writing }
        XCTAssertEqual(model.tab, 2)
        XCTAssertEqual(model.error, "购物车已更新，请刷新后重新核对商品和数量。")
        XCTAssertTrue(model.pending.isEmpty)
        model.logout()
    }

    @MainActor
    private func isolatedModel() throws -> (BuyerModel, URLSession, UserDefaults, String) {
        let suite = "native-lifecycle-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        let storage = BuyerStorage(defaults: defaults)
        storage.endpoint = "https://" + suite + ".test"
        storage.owner = "test-buyer"
        let configuration = URLSessionConfiguration.ephemeral
        configuration.protocolClasses = [BuyerTestProtocol.self]
        let session = URLSession(configuration: configuration)
        let model = BuyerModel(api: BuyerAPI(session: session), storage: storage)
        return (model, session, defaults, suite)
    }

    @MainActor
    private func settle(_ condition: () -> Bool) async throws {
        for _ in 0..<300 {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("Native operation did not settle")
        throw URLError(.timedOut)
    }

}


private final class BuyerTestProtocol: URLProtocol {
    static var handle: ((BuyerTestProtocol) -> Void)?
    var onStop: (() -> Void)?
    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() { Self.handle!(self) }
    override func stopLoading() { onStop?() }
    func startStream(_ body: String) {
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: 200, httpVersion: nil,
            headerFields: ["Content-Type": "text/event-stream"])!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
    }
    func reply(_ body: String, type: String = "application/json", status: Int = 200) {
        client?.urlProtocol(self, didReceive: HTTPURLResponse(url: request.url!, statusCode: status, httpVersion: nil,
            headerFields: ["Content-Type": type])!, cacheStoragePolicy: .notAllowed)
        client?.urlProtocol(self, didLoad: Data(body.utf8))
        client?.urlProtocolDidFinishLoading(self)
    }
}
