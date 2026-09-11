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

}
