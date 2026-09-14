import XCTest
import SwiftUI
import BuyerCore
@testable import ShopMate

final class BuyerAppTests: XCTestCase {
    func testByteLinesPreserveCRLFFrameBoundariesAndChinese() throws {
        var transport = StreamLines()
        let decoder = StreamDecoder()
        let timeline = ChatTimeline()
        try timeline.begin(text: "查询", event: startEvent("test"), sessionId: "test")
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
        try model.chat.timeline.restorePage(payload: historyPage("history-race", ids: [1, 2]), sessionId: "history-race")
        model.chat.publishTimeline()
        let historyStarted = expectation(description: "old history request")
        var delayed: BuyerTestProtocol?
        BuyerTestProtocol.handle = { request in
            if request.request.url!.path.hasSuffix("/history-race/messages") {
                DispatchQueue.main.async { delayed = request; historyStarted.fulfill() }
            } else if request.request.url!.path.hasSuffix("/chat") {
                request.reply(startFrame("history-race", user: 3, assistant: 4) + "event: text_delta\ndata: {\"text\":\"本轮的新回答\"}\n\nevent: turn_complete\ndata: {}\n\n", type: "text/event-stream")
            } else { request.reply("{}") }
        }
        let oldLoad = model.reload()
        await fulfillment(of: [historyStarted], timeout: 3)
        model.send("继续推荐")
        try await settle { !model.chat.running }
        XCTAssertEqual(model.chat.messages.last?.segments.last?.text, "本轮的新回答")
        delayed?.reply(try historyPage("history-race", ids: [1, 2]))
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
            request.startStream(startFrame("cancel-test") + "event: text_delta\ndata: {\"text\":\"未完成的回答\"}\n\n")
            started.fulfill()
        }
        model.send("先查询")
        await fulfillment(of: [started], timeout: 3)
        try await settle { model.chat.messages.last?.segments.isEmpty == false }
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

extension BuyerAppTests {
    @MainActor
    func testSameSlotCardUpdatesFromPartialToFinalAndReplacement() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        try model.chat.timeline.begin(text: "请推荐一款咖啡机。", event: startEvent("cards"), sessionId: "cards")
        model.chat.messages = model.chat.timeline.messages
        model.chat.running = true
        model.chat.activity = "整理商品"

        let first: Object = ["component": "products", "stream_id": "same-slot", "payload": [
            "title": "日常滴滤方案", "items": [["product": [
                "product_id": "slot-drip", "title": "十二杯滴滤咖啡机", "price": 79.6,
                "in_stock": true, "category": "home-kitchen"
            ], "reason": "适合多人日常饮用。"]]
        ]]
        let replacement: Object = ["component": "products", "stream_id": "same-slot", "payload": [
            "title": "更新为紧凑方案", "items": [["product": [
                "product_id": "slot-espresso", "title": "紧凑浓缩咖啡机", "price": 249.0,
                "in_stock": true, "category": "home-kitchen"
            ], "reason": "更新后的选择：适合小台面。"]]
        ]]
        let decoder = StreamDecoder()
        func publish(_ type: String, _ block: Object) throws -> ChatSegment {
            for line in ["event: " + type, "data: " + (try jsonText(block)), ""] {
                if let event = try decoder.line(raw: line) { try model.chat.timeline.accept(event: event) }
            }
            model.chat.messages = model.chat.timeline.messages
            model.chat.revision += 1
            let message = try XCTUnwrap(model.chat.messages.last)
            XCTAssertFalse(message.user)
            XCTAssertEqual(message.segments.count, 1)
            let segment = try XCTUnwrap(message.segments.first)
            XCTAssertEqual(segment.slot, "same-slot")
            return segment
        }

        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.first as? UIWindowScene)
        let window = UIWindow(windowScene: scene)
        window.frame = scene.coordinateSpace.bounds
        window.windowLevel = .normal + 1
        window.rootViewController = UIHostingController(rootView: NavigationStack {
            ConversationView(model: model, chat: model.chat)
        }.tint(accent).preferredColorScheme(.light))
        window.makeKeyAndVisible()
        defer { window.isHidden = true; window.rootViewController = nil }

        func capture(_ name: String) async throws {
            // Yield for SwiftUI publication and scrolling before capturing the actual window.
            try await Task.sleep(for: .milliseconds(250))
            window.layoutIfNeeded()
            let screenshot = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in
                window.drawHierarchy(in: window.bounds, afterScreenUpdates: true)
            }
            let attachment = XCTAttachment(image: screenshot)
            attachment.name = name
            attachment.lifetime = .keepAlways
            self.add(attachment)
        }

        let partial = try publish("ui_partial", first)
        XCTAssertFalse(partial.final)
        try await capture("01 Partial - drip product with operation warning")

        // Identical payload isolates the final flag that enables native card operations.
        let finalized = try publish("ui", first)
        XCTAssertTrue(finalized.final)
        XCTAssertFalse(partial === finalized)
        XCTAssertFalse(partial.final)
        XCTAssertEqual(partial.blockJson, finalized.blockJson)
        try await capture("02 Final - same drip product without operation warning")

        let updated = try publish("ui", replacement)
        XCTAssertTrue(updated.final)
        XCTAssertFalse(finalized === updated)
        XCTAssertNotEqual(finalized.blockJson, updated.blockJson)
        let payload = object(try XCTUnwrap(ChatCardPayload.decode(updated)), "payload")
        XCTAssertEqual(text(payload, "title"), "更新为紧凑方案")
        let product = object(try XCTUnwrap(rows(payload, "items").first), "product")
        XCTAssertEqual(text(product, "product_id"), "slot-espresso")
        XCTAssertEqual(text(product, "title"), "紧凑浓缩咖啡机")
        XCTAssertEqual(product["price"] as? Double, 249.0)
        try await capture("03 Same slot replacement - espresso product at 249")
    }
}

private func startFrame(_ session: String, user: Int64 = 1, assistant: Int64 = 2) -> String {
    "event: turn_started\ndata: {\"session_id\":\"\(session)\",\"user_message_id\":\(user),\"assistant_message_id\":\(assistant)}\n\n"
}

private func startEvent(_ session: String, user: Int64 = 1, assistant: Int64 = 2) throws -> StreamEvent {
    let decoder = StreamDecoder()
    var event: StreamEvent?
    for line in startFrame(session, user: user, assistant: assistant).components(separatedBy: "\n") {
        if let value = try decoder.line(raw: line) { event = value }
    }
    return try XCTUnwrap(event)
}

private func historyPage(_ session: String, ids: [Int64], before: Int64? = nil) throws -> String {
    let items: [Object] = ids.map { id in
        if id % 2 == 1 { return ["message_id": id, "kind": "user", "text": "历史问题\(id)"] }
        return ["message_id": id, "kind": "assistant", "segments": [["type": "text", "text": "历史回答\(id)"]], "pending": false]
    }
    return try jsonText(["session_id": session, "status": "completed", "items": items, "next_before": before.map { $0 as Any } ?? NSNull()])
}

extension BuyerAppTests {
    @MainActor
    func testFirstHistoryDoesNotWaitForCommerceAndGatesSending() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        model.storage.conversation = "initial-page"
        model.products = [["product_id": "test"]]
        let requested = expectation(description: "history independent of Commerce")
        var history: BuyerTestProtocol?
        BuyerTestProtocol.handle = { request in
            if request.request.url!.path.hasSuffix("/messages") {
                DispatchQueue.main.async { history = request; requested.fulfill() }
            } else { request.reply("{}", status: 503) }
        }
        let load = model.reload()
        await fulfillment(of: [requested], timeout: 3)
        XCTAssertTrue(model.chat.requiresHistory)
        model.send("等待历史后才能开始")
        XCTAssertFalse(model.chat.running)
        history?.reply(try historyPage("initial-page", ids: [31, 32], before: 31))
        await load.value
        XCTAssertFalse(model.chat.requiresHistory)
        XCTAssertEqual(model.chat.messages.map(\.messageId), [31, 32])
        XCTAssertEqual(model.chat.nextBefore, 31)
    }

    @MainActor
    func testEarlierPageMergesDuringStreamWithoutReplacingTail() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        model.storage.conversation = "paged-stream"
        try model.chat.timeline.restorePage(payload: historyPage("paged-stream", ids: [31, 32], before: 31), sessionId: "paged-stream")
        model.chat.publishTimeline()
        let pageStarted = expectation(description: "earlier page in flight")
        let streamStarted = expectation(description: "new stream in flight")
        var page: BuyerTestProtocol?
        var stream: BuyerTestProtocol?
        BuyerTestProtocol.handle = { request in
            if request.request.url!.path.hasSuffix("/messages") {
                DispatchQueue.main.async { page = request; pageStarted.fulfill() }
            } else {
                DispatchQueue.main.async {
                    stream = request
                    request.startStream(startFrame("paged-stream", user: 33, assistant: 34) + "event: text_delta\ndata: {\"text\":\"新回复\"}\n\n")
                    streamStarted.fulfill()
                }
            }
        }
        let load = try XCTUnwrap(model.loadEarlier())
        await fulfillment(of: [pageStarted], timeout: 3)
        model.send("一边翻页，一边回答")
        await fulfillment(of: [streamStarted], timeout: 3)
        try await settle { model.chat.messages.last?.segments.last?.text == "新回复" }
        page?.reply(try historyPage("paged-stream", ids: Array(1...30)))
        await load.value
        XCTAssertTrue(model.chat.running)
        XCTAssertEqual(model.chat.messages.map(\.messageId), Array(1...34))
        XCTAssertEqual(model.chat.messages.last?.segments.last?.text, "新回复")
        XCTAssertNil(model.chat.nextBefore)
        stream?.appendStream("event: text_delta\ndata: {\"text\":\"继续\"}\n\nevent: turn_complete\ndata: {}\n\n")
        stream?.finishStream()
        try await settle { !model.chat.running }
        XCTAssertEqual(model.chat.messages.last?.segments.last?.text, "新回复继续")
        XCTAssertEqual(model.chat.messages.last?.pending, false)
    }

    @MainActor
    func testEarlierPageRetryKeepsCursorAndLoadedMessages() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        model.storage.conversation = "page-retry"
        try model.chat.timeline.restorePage(payload: historyPage("page-retry", ids: [31, 32], before: 31), sessionId: "page-retry")
        model.chat.publishTimeline()
        let old = try historyPage("page-retry", ids: Array(1...30))
        var queries: [String] = []
        BuyerTestProtocol.handle = { request in
            queries.append(request.request.url!.query!)
            if queries.count == 1 { request.reply("{}", status: 503) }
            else { request.reply(old) }
        }
        await model.loadEarlier()?.value
        XCTAssertEqual(model.chat.nextBefore, 31)
        XCTAssertEqual(model.chat.messages.map(\.messageId), [31, 32])
        XCTAssertNotNil(model.chat.historyError)
        model.retryHistory()
        try await settle { !model.chat.earlierLoading }
        XCTAssertEqual(queries, ["limit=30&before=31", "limit=30&before=31"])
        XCTAssertNil(model.chat.nextBefore)
        XCTAssertNil(model.chat.historyError)
        XCTAssertEqual(model.chat.messages.count, 32)
    }

    @MainActor
    func testLatestPageRetryDoesNotBecomeAnEarlierPageRequest() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        model.storage.conversation = "latest-retry"
        model.products = [["product_id": "test"]]
        try model.chat.timeline.restorePage(payload: historyPage("latest-retry", ids: [31, 32], before: 31), sessionId: "latest-retry")
        model.chat.publishTimeline()
        let latest = try historyPage("latest-retry", ids: [33, 34], before: 33)
        var queries: [String] = []
        BuyerTestProtocol.handle = { request in
            if request.request.url!.path.hasSuffix("/messages") {
                queries.append(request.request.url!.query!)
                if queries.count == 1 { request.reply("{}", status: 503) }
                else { request.reply(latest) }
            } else { request.reply("{}") }
        }
        await model.reload().value
        XCTAssertNotNil(model.chat.historyError)
        XCTAssertFalse(model.chat.requiresHistory)
        model.retryHistory()
        try await settle { queries.count == 2 && !model.chat.latestLoading }
        XCTAssertEqual(queries, ["limit=30", "limit=30"])
        XCTAssertEqual(model.chat.messages.map(\.messageId), [33, 34])
        XCTAssertEqual(model.chat.nextBefore, 33)
    }

    @MainActor
    func testEarlierPageCannotLeakAcrossConversationSwitch() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        model.storage.conversation = "previous"
        try model.chat.timeline.restorePage(payload: historyPage("previous", ids: [31, 32], before: 31), sessionId: "previous")
        model.chat.publishTimeline()
        let requested = expectation(description: "previous page")
        var old: BuyerTestProtocol?
        let next = try historyPage("next", ids: [1, 2])
        BuyerTestProtocol.handle = { request in
            if request.request.url!.path.contains("/previous/") {
                DispatchQueue.main.async { old = request; requested.fulfill() }
            } else { request.reply(next) }
        }
        let load = model.loadEarlier()
        await fulfillment(of: [requested], timeout: 3)
        model.selectConversation("next")
        try await settle { !model.chat.requiresHistory && model.chat.messages.count == 2 }
        old?.reply("{}", status: 503)
        await load?.value
        XCTAssertEqual(model.storage.conversation, "next")
        XCTAssertEqual(model.chat.messages.map(\.messageId), [1, 2])
        XCTAssertNil(model.chat.historyError)
        XCTAssertNil(model.error)
    }

    @MainActor
    func testFailedHistoryIsReportedBeforeCommerceFinishesAndCannotLeakAfterSwitch() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        model.storage.conversation = "failed-history"
        model.products = [["product_id": "test"]]
        let commerceStarted = expectation(description: "Commerce remains in flight")
        let next = try historyPage("next", ids: [1, 2])
        BuyerTestProtocol.handle = { request in
            if request.request.url!.path.hasSuffix("/cart") { commerceStarted.fulfill() }
            else if request.request.url!.path.contains("/failed-history/") { request.reply("{}", status: 503) }
            else { request.reply(next) }
        }
        let oldLoad = model.reload()
        await fulfillment(of: [commerceStarted], timeout: 3)
        try await settle { model.chat.historyError != nil }
        XCTAssertNotNil(model.error, "The owned history error is reported without waiting for Commerce")
        model.error = nil
        model.selectConversation("next")
        await oldLoad.value
        try await settle { !model.chat.requiresHistory }
        XCTAssertEqual(model.storage.conversation, "next")
        XCTAssertNil(model.error)
        XCTAssertNil(model.chat.historyError)
    }

    @MainActor
    func testDraftSurvivesBeforeStartFailureAndCancellation() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        model.storage.conversation = "draft"
        for status in [409, 503] {
            BuyerTestProtocol.handle = { request in request.reply("{}", status: status) }
            model.chat.draft = "保留输入"
            model.send(model.chat.draft)
            try await settle { !model.chat.running }
            XCTAssertEqual(model.chat.draft, "保留输入")
            XCTAssertTrue(model.chat.messages.isEmpty)
        }
        let requested = expectation(description: "waiting for start")
        BuyerTestProtocol.handle = { _ in requested.fulfill() }
        model.send(model.chat.draft)
        await fulfillment(of: [requested], timeout: 3)
        model.stop()
        try await settle { !model.chat.running }
        XCTAssertEqual(model.chat.draft, "保留输入")
        XCTAssertTrue(model.chat.messages.isEmpty)
    }

    @MainActor
    func testStartClearsOnlyTheSubmittedDraft() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        model.storage.conversation = "draft-start"
        let requested = expectation(description: "delayed start")
        var stream: BuyerTestProtocol?
        BuyerTestProtocol.handle = { request in
            DispatchQueue.main.async { stream = request; requested.fulfill() }
        }
        model.chat.draft = "原始输入"
        model.send(model.chat.draft)
        await fulfillment(of: [requested], timeout: 3)
        model.chat.draft = "连接期间的新输入"
        stream?.reply(startFrame("draft-start") + "event: turn_complete\ndata: {}\n\n", type: "text/event-stream")
        try await settle { !model.chat.running }
        XCTAssertEqual(model.chat.draft, "连接期间的新输入")
        XCTAssertEqual(model.chat.messages.first?.segments.first?.text, "原始输入")
        BuyerTestProtocol.handle = { request in
            request.reply(startFrame("draft-start", user: 3, assistant: 4) + "event: turn_complete\ndata: {}\n\n", type: "text/event-stream")
        }
        model.send(model.chat.draft)
        try await settle { !model.chat.running }
        XCTAssertEqual(model.chat.draft, "")
        XCTAssertEqual(model.chat.messages[2].segments.first?.text, "连接期间的新输入")
    }

    @MainActor
    func testProtocolFailureAndServerErrorEndOnlyLocalReply() async throws {
        let (model, session, defaults, suite) = try isolatedModel()
        defer { model.logout(); session.invalidateAndCancel(); defaults.removePersistentDomain(forName: suite) }
        model.storage.conversation = "stream-failure"
        BuyerTestProtocol.handle = { request in
            request.reply("event: text_delta\ndata: {\"text\":\"缺少身份\"}\n\nevent: turn_complete\ndata: {}\n\n", type: "text/event-stream")
        }
        model.send("无开始信息")
        try await settle { !model.chat.running }
        XCTAssertTrue(model.chat.messages.isEmpty)
        XCTAssertNotNil(model.error)
        BuyerTestProtocol.handle = { request in
            request.reply(startFrame("stream-failure") + "event: text_delta\ndata: {\"text\":\"保留这部分\"}\n\nevent: error\ndata: {\"message\":\"生成中断\"}\n\n", type: "text/event-stream")
        }
        model.send("有开始信息后失败")
        try await settle { !model.chat.running }
        XCTAssertEqual(model.chat.messages.last?.segments.last?.text, "保留这部分")
        XCTAssertEqual(model.chat.messages.last?.pending, false)
        XCTAssertEqual(model.error, "生成中断")
    }
}

private extension BuyerTestProtocol {
    func appendStream(_ body: String) { client?.urlProtocol(self, didLoad: Data(body.utf8)) }
    func finishStream() { client?.urlProtocolDidFinishLoading(self) }
}


private final class HistoryInteractionScrollView: UIScrollView {
    var dragging = false
    var decelerating = false
    override var isDragging: Bool { dragging }
    override var isDecelerating: Bool { decelerating }
}

extension BuyerAppTests {
    @MainActor
    func testHistoryWaitSuspendsForDraggingAndDeceleration() async throws {
        let (position, scroll, window) = try mountedHistoryPosition()
        defer { window.isHidden = true; window.rootViewController = nil }
        for dragging in [true, false] {
            scroll.dragging = dragging
            scroll.decelerating = !dragging
            var resumed = false
            let entered = expectation(description: "scroll wait entered")
            let waiting = Task {
                entered.fulfill()
                try await position.waitUntilScrollingStops()
                resumed = true
            }
            await fulfillment(of: [entered], timeout: 1)
            XCTAssertFalse(resumed)
            scroll.dragging = false
            scroll.decelerating = false
            try await waiting.value
            XCTAssertTrue(resumed)
        }
    }

    @MainActor
    func testHistoryWaitCanBeCancelledWhileGestureContinues() async throws {
        let (position, scroll, window) = try mountedHistoryPosition()
        defer { window.isHidden = true; window.rootViewController = nil }
        scroll.dragging = true
        let entered = expectation(description: "cancellable scroll wait entered")
        let waiting = Task {
            entered.fulfill()
            try await position.waitUntilScrollingStops()
        }
        await fulfillment(of: [entered], timeout: 1)
        waiting.cancel()
        do {
            try await waiting.value
            XCTFail("A cancelled earlier-page wait must not continue to merge")
        } catch is CancellationError {
            XCTAssertTrue(scroll.isDragging)
        }
    }

    @MainActor
    private func mountedHistoryPosition() throws -> (ConversationReadingPosition, HistoryInteractionScrollView, UIWindow) {
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.first as? UIWindowScene)
        let window = UIWindow(windowScene: scene)
        window.frame = scene.coordinateSpace.bounds
        window.windowLevel = .normal + 1
        let controller = UIViewController()
        window.rootViewController = controller
        let scroll = HistoryInteractionScrollView(frame: window.bounds)
        let position = ConversationReadingPosition()
        let marker = ConversationViewportMarker.ViewportView(position: position)
        scroll.addSubview(marker)
        controller.view.addSubview(scroll)
        window.makeKeyAndVisible()
        XCTAssertNotNil(marker.window)
        return (position, scroll, window)
    }
}
