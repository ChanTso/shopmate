import XCTest
import SwiftUI
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
    func testCatalogAndProductDetailDoNotWaitForCartRefresh() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        let cartStarted = expectation(description: "cart refresh is waiting")
        var cartRequest: BuyerTestProtocol?
        BuyerTestProtocol.handle = { request in
            switch request.request.url!.path {
            case "/api/buyer/cart":
                DispatchQueue.main.async { cartRequest = request; cartStarted.fulfill() }
            case "/api/buyer/products":
                request.reply("{\"products\":[{\"product_id\":\"cup\"}],\"next_offset\":null}")
            case "/api/buyer/products/sku":
                request.reply("{\"product\":{\"product_id\":\"sku\"}}")
            default: XCTFail("Unexpected request: \(request.request.url!)")
            }
        }
        let refresh = model.reload()
        await fulfillment(of: [cartStarted], timeout: 3)
        try await settle { !model.searching && !model.products.isEmpty }
        model.openProduct("sku")
        try await settle { model.selected != nil }
        XCTAssertEqual(text(model.products[0], "product_id"), "cup")
        XCTAssertEqual(text(model.selected!, "product_id"), "sku")
        cartRequest?.reply("{\"detail\":\"cart temporarily unavailable\"}", status: 503)
        await refresh.value
        XCTAssertEqual(model.error, "cart temporarily unavailable")
    }

    @MainActor
    func testPaginationUsesSubmittedQueryWhileSearchDraftChanges() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        BuyerTestProtocol.handle = { request in
            let parts = URLComponents(url: request.request.url!, resolvingAgainstBaseURL: false)!
            XCTAssertEqual(parts.queryItems?.first { $0.name == "query" }?.value, "coffee")
            if parts.queryItems?.first(where: { $0.name == "offset" })?.value == "0" {
                request.reply("{\"products\":[{\"product_id\":\"first\"}],\"next_offset\":24}")
            } else {
                XCTAssertEqual(parts.queryItems?.first { $0.name == "offset" }?.value, "24")
                request.reply("{\"products\":[{\"product_id\":\"second\"}],\"next_offset\":null}")
            }
        }
        model.searchQuery = "coffee"
        model.search()
        try await settle { !model.searching }
        model.searchQuery = "tea"
        model.search(append: true)
        try await settle { !model.searching }
        XCTAssertEqual(model.products.map { text($0, "product_id") }, ["first", "second"])
        XCTAssertEqual(model.submittedSearchQuery, "coffee")
        XCTAssertEqual(model.searchQuery, "tea")
        XCTAssertFalse(model.hasMoreProducts)
    }

    @MainActor
    func testSubmittingNewSearchCancelsOlderPage() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        let pageStarted = expectation(description: "older page started")
        let pageCancelled = expectation(description: "older page cancelled")
        BuyerTestProtocol.handle = { request in
            let parts = URLComponents(url: request.request.url!, resolvingAgainstBaseURL: false)!
            if parts.queryItems?.first(where: { $0.name == "query" })?.value == "tea" {
                request.reply("{\"products\":[{\"product_id\":\"tea\"}],\"next_offset\":null}")
            } else if parts.queryItems?.first(where: { $0.name == "offset" })?.value == "0" {
                request.reply("{\"products\":[{\"product_id\":\"coffee\"}],\"next_offset\":24}")
            } else {
                request.onStop = { pageCancelled.fulfill() }
                pageStarted.fulfill()
            }
        }
        model.searchQuery = "coffee"
        model.search()
        try await settle { !model.searching }
        model.search(append: true)
        await fulfillment(of: [pageStarted], timeout: 3)
        model.searchQuery = "tea"
        model.search()
        await fulfillment(of: [pageCancelled], timeout: 3)
        try await settle { !model.searching }
        XCTAssertEqual(model.products.map { text($0, "product_id") }, ["tea"])
        XCTAssertEqual(model.submittedSearchQuery, "tea")
    }

    @MainActor
    func testClosingProductCancelsPendingVariant() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        let started = expectation(description: "variant request started")
        let cancelled = expectation(description: "variant request cancelled")
        BuyerTestProtocol.handle = { request in
            request.onStop = { cancelled.fulfill() }
            started.fulfill()
        }
        model.selected = ["product_id": "parent"]
        model.openProduct("variant")
        await fulfillment(of: [started], timeout: 3)
        model.closeProduct()
        await fulfillment(of: [cancelled], timeout: 3)
        XCTAssertNil(model.selected)
        XCTAssertNil(model.error)
    }

    @MainActor
    func testProductConsultationReturnsToOriginalVariantWithoutReloading() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        let loaded = expectation(description: "load selected variant once")
        BuyerTestProtocol.handle = { request in
            XCTAssertEqual(request.request.url!.path, "/api/buyer/products/blue-small")
            loaded.fulfill()
            request.reply("{\"product\":{\"product_id\":\"blue-small\",\"title\":\"蓝色小号\",\"option_values\":{\"color\":\"blue\",\"size\":\"small\"}}}")
        }
        model.tab = 0
        model.catalogPosition = "catalog-product-18"
        model.openProduct("blue-small")
        await fulfillment(of: [loaded], timeout: 3)
        try await settle { model.selected != nil }
        model.askProduct(try XCTUnwrap(model.selected))
        XCTAssertNil(model.selected)
        XCTAssertEqual(model.tab, 1)
        XCTAssertEqual(text(model.assistantPage, "product_id"), "blue-small")
        model.returnToProduct()
        XCTAssertEqual(model.tab, 0)
        XCTAssertEqual(text(try XCTUnwrap(model.selected), "product_id"), "blue-small")
        XCTAssertEqual(text(object(model.selected!, "option_values"), "size"), "small")
        XCTAssertEqual(model.catalogPosition, "catalog-product-18")
        XCTAssertNil(model.productReturn)
    }

    @MainActor
    func testAcceptedWriteReportsRefreshFailureWithoutRetainingItsIntent() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        let accepted = expectation(description: "one submitted write")
        BuyerTestProtocol.handle = { request in
            if request.request.httpMethod == "POST" {
                accepted.fulfill()
                request.reply("{}")
            } else {
                XCTAssertEqual(request.request.url!.path, "/api/buyer/cart")
                request.reply("{\"detail\":\"refresh unavailable\"}", status: 503)
            }
        }
        model.write(path: "/cart/add", body: ["productId": "cup", "quantity": 1])
        await fulfillment(of: [accepted], timeout: 3)
        try await settle { !model.writing }
        XCTAssertTrue(model.error?.hasPrefix("操作已受理，业务状态刷新未完成") == true)
        XCTAssertTrue(model.error?.contains("refresh unavailable") == true)
        XCTAssertTrue(model.pending.isEmpty)
        XCTAssertTrue(try model.storage.pending().isEmpty)
    }

    @MainActor
    func testRefreshClearsOnlyMatchingConfirmedPendingIntent() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        model.products = [["product_id": "existing"]]
        let keys = ["confirmed", "unknown", "rejected", "missing"]
        let saved = try keys.map { try WriteRecovery.shared.prepare(key: $0, path: "/cart/add", body: "{\"productId\":\"cup\",\"quantity\":1}") }
        try model.storage.savePending(saved)
        model.pending = saved
        BuyerTestProtocol.handle = { request in
            if request.request.url!.path == "/api/buyer/commands" {
                request.reply("{\"commands\":[{\"request_key\":\"confirmed\",\"state\":\"confirmed\",\"result\":{}},{\"request_key\":\"unknown\",\"state\":\"unknown\"},{\"request_key\":\"rejected\",\"state\":\"rejected\"},{\"request_key\":\"unrelated\",\"state\":\"confirmed\",\"result\":{}}]}")
            } else { request.reply("{}") }
        }
        await model.reload().value
        XCTAssertEqual(model.pending.map(\.key), ["unknown", "rejected", "missing"])
        XCTAssertEqual(try model.storage.pending().map(\.key), ["unknown", "rejected", "missing"])
        XCTAssertNil(model.error)
    }

    @MainActor
    func testReservationPollingPausesAndResumesWithVisibilityAndForeground() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        let ticket = SeckillTicket(key: "original", activityId: "sale", activityVersion: 7)
            .result(["reservationId": "reservation", "state": "ADMITTED"])
        try model.storage.saveTickets([ticket])
        let firstStarted = expectation(description: "first foreground query")
        let firstCancelled = expectation(description: "background cancels query")
        let secondStarted = expectation(description: "resume queries original reservation")
        let secondCancelled = expectation(description: "leaving page cancels query")
        var queries = 0
        BuyerTestProtocol.handle = { request in
            DispatchQueue.main.async {
                XCTAssertEqual(request.request.httpMethod, "GET")
                XCTAssertEqual(request.request.url!.path, "/api/reservations/reservation")
                queries += 1
                switch queries {
                case 1:
                    request.onStop = { firstCancelled.fulfill() }
                    firstStarted.fulfill()
                case 2:
                    request.onStop = { secondCancelled.fulfill() }
                    secondStarted.fulfill()
                case 3:
                    request.reply("{\"reservationId\":\"reservation\",\"state\":\"ORDERED\",\"orderId\":\"order\"}")
                default: XCTFail("A visible foreground transition created duplicate polling")
                }
            }
        }
        model.setSeckillVisible(true)
        model.setApplicationActive(true)
        await fulfillment(of: [firstStarted], timeout: 3)
        model.setSeckillVisible(true)
        model.setApplicationActive(true)
        model.setApplicationActive(false)
        await fulfillment(of: [firstCancelled], timeout: 3)
        XCTAssertEqual(queries, 1)
        model.setApplicationActive(true)
        await fulfillment(of: [secondStarted], timeout: 3)
        model.setSeckillVisible(false)
        await fulfillment(of: [secondCancelled], timeout: 3)
        XCTAssertEqual(queries, 2)
        model.setSeckillVisible(true)
        try await settle { model.tickets.first?.terminal == true }
        XCTAssertEqual(queries, 3)
        XCTAssertEqual(model.tickets.first?.key, "original")
        XCTAssertEqual(try model.storage.tickets().first?.orderId, "order")
    }

    @MainActor
    func testCatalogReadingPositionSurvivesTabAndLayoutChanges() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        model.signedIn = true
        model.products = (0..<60).map { ["product_id": "product-\($0)", "title": "第\($0)件商品", "price": 10] }
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.first as? UIWindowScene)
        let window = UIWindow(windowScene: scene)
        window.frame = CGRect(x: 0, y: 0, width: 390, height: 760)
        window.windowLevel = .normal + 1
        let host = UIHostingController(rootView: BuyerRoot(model: model).frame(width: 390, height: 760))
        window.rootViewController = host
        window.makeKeyAndVisible()
        defer {
            captureCatalog("Catalog after wide layout", window: window, view: host.view, anchor: model.catalogPosition)
            window.isHidden = true; window.rootViewController = nil
        }
        try await settle("catalog scroll view mounted") { self.catalogScrollView(host.view) != nil }
        model.catalogPosition = "product-24"
        try await settle("catalog navigated below the first page") {
            (self.catalogScrollView(host.view)?.contentOffset.y ?? 0) > 100
        }
        captureCatalog("Catalog at requested product 24", window: window, view: host.view, anchor: model.catalogPosition)
        let initialOffset = try XCTUnwrap(catalogScrollView(host.view)).contentOffset.y
        model.tab = 2
        try await settle("catalog left for cart tab") { self.catalogScrollView(host.view) == nil }
        model.tab = 0
        try await settle("catalog position restored after tab return") {
            guard let scroll = self.catalogScrollView(host.view) else { return false }
            return scroll.contentOffset.y > 100 && abs(scroll.contentOffset.y - initialOffset) <= 80
        }
        captureCatalog("Catalog after tab return", window: window, view: host.view, anchor: model.catalogPosition)
        window.frame = CGRect(x: 0, y: 0, width: 1000, height: 760)
        host.rootView = BuyerRoot(model: model).frame(width: 1000, height: 760)
        try await settle("catalog position restored after wide layout recreation") {
            host.view.bounds.width >= 850 && (self.catalogScrollView(host.view)?.contentOffset.y ?? 0) > 100
        }
    }

    @MainActor
    private func captureCatalog(_ name: String, window: UIWindow, view: UIView, anchor: String?) {
        let screenshot = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in window.drawHierarchy(in: window.bounds, afterScreenUpdates: true) }
        let frame = XCTAttachment(image: screenshot)
        frame.name = name
        frame.lifetime = .keepAlways
        add(frame)
        let state = XCTAttachment(string: "anchor=\(anchor ?? "nil")\n" + scrollDiagnostics(view))
        state.name = name + " scroll state"
        state.lifetime = .keepAlways
        add(state)
    }

    @MainActor
    private func catalogScrollView(_ view: UIView) -> UIScrollView? {
        guard !view.isHidden, view.alpha > 0 else { return nil }
        if let scroll = view as? UIScrollView, scroll.contentSize.height > scroll.bounds.height + 500 { return scroll }
        return view.subviews.lazy.compactMap { self.catalogScrollView($0) }.first
    }

    @MainActor
    private func scrollDiagnostics(_ view: UIView) -> String {
        let current = (view as? UIScrollView).map { "\(type(of: $0)) bounds=\($0.bounds) content=\($0.contentSize) offset=\($0.contentOffset) hidden=\($0.isHidden)\n" } ?? ""
        return current + view.subviews.map { self.scrollDiagnostics($0) }.joined()
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
    private func settle(_ phase: String = "native operation", _ condition: () -> Bool) async throws {
        for _ in 0..<300 {
            if condition() { return }
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTFail("Did not settle: " + phase)
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
