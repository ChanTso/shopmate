import XCTest
import SwiftUI
import BuyerCore
@testable import ShopMate

/// Native transport, shared reduction and SwiftUI rendering under a paced, mixed-card stream.
final class MixedStreamingReplayTests: XCTestCase {
    @MainActor
    func testMixedCardsThroughNativeTransport() throws {
        let suite = "mixed-replay-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let storage = BuyerStorage(defaults: defaults)
        storage.endpoint = "https://mixed-replay.test"
        storage.conversation = "mixed-history"
        let config = URLSessionConfiguration.ephemeral
        config.protocolClasses = [MixedReplayProtocol.self]
        let session = URLSession(configuration: config)
        defer { session.invalidateAndCancel() }
        let model = BuyerModel(api: BuyerAPI(session: session), storage: storage)
        let product: Object = ["product_id": "AR-1001", "title": "十二杯定时滴滤咖啡机", "price": 79.6, "in_stock": true, "category": "home-kitchen"]
        let productBlock: Object = ["component": "products", "stream_id": "recommendation", "payload": ["title": "适合日常的选择", "items": [["product": product, "reason": "定时冲煮，适合日常多人饮用。"]]]]
        let comparison: Object = ["component": "comparison", "stream_id": "comparison", "payload": ["title": "先看清取舍", "entries": [["product": product, "best_for": "日常多人饮用", "pros": ["支持定时", "容量充足"], "cons": ["需要预留台面空间"]]]]]
        let history: [Object] = (0..<60).map { index in
            if index.isMultiple(of: 2) { return ["kind": "user", "text": "第\(index / 2 + 1)轮：帮我比较咖啡器具。"] }
            return ["kind": "assistant", "segments": [
                ["type": "text", "text": "结合容量、清洁方式、占地和预算选择。"],
                ["type": "ui", "slotKey": "saved-\(index)", "status": "final", "block": index.isMultiple(of: 3) ? comparison : productBlock]
            ]]
        }
        let snapshot = try jsonText(["items": history])
        func frame(_ type: String, _ payload: Object) throws -> Data {
            Data("event: \(type)\r\ndata: \(try jsonText(payload))\r\n\r\n".utf8)
        }
        var frames = [try frame("ui_partial", productBlock)]
        for index in 0..<240 {
            if index == 24 { frames.append(try frame("ui", productBlock)) }
            if index == 120 { frames.append(try frame("ui", comparison)) }
            frames.append(try frame("text_delta", ["text": "选购建议"]))
        }
        frames.append(try frame("turn_complete", [:]))
        MixedReplayProtocol.frames = frames
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.first as? UIWindowScene)
        let window = UIWindow(windowScene: scene)
        window.frame = scene.coordinateSpace.bounds
        window.windowLevel = .normal + 1
        window.rootViewController = UIHostingController(rootView: NavigationStack {
            ConversationView(model: model, chat: model.chat)
        }.tint(accent).preferredColorScheme(.light))
        window.makeKeyAndVisible()
        defer { window.isHidden = true; window.rootViewController = nil }
        let options = XCTMeasureOptions()
        options.iterationCount = 3
        measure(metrics: [XCTClockMetric(), XCTCPUMetric(), XCTMemoryMetric(),
            XCTOSSignpostMetric(subsystem: "io.shopmate.buyer.ios", category: "ChatCard", name: "Decode card")], options: options) {
            let finished = expectation(description: "native mixed replay")
            Task { @MainActor in
                do {
                    model.chat.clear()
                    try model.chat.timeline.restore(payload: snapshot)
                    model.chat.messages = model.chat.timeline.messages
                    model.send("请继续比较具体取舍。")
                    while model.chat.running { try await Task.sleep(for: .milliseconds(10)) }
                    XCTAssertNil(model.error)
                    let last = try XCTUnwrap(model.chat.messages.last)
                    XCTAssertEqual(last.segments.filter { !$0.hasBlock }.map(\.text).joined().count, 960)
                    XCTAssertEqual(last.segments.filter { $0.hasBlock }.count, 2)
                    XCTAssertTrue(last.segments.allSatisfy(\.final))
                    let rendered = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in
                        window.drawHierarchy(in: window.bounds, afterScreenUpdates: true)
                    }
                    let attachment = XCTAttachment(image: rendered)
                    attachment.name = "Mixed native conversation final frame"
                    attachment.lifetime = .keepAlways
                    self.add(attachment)
                } catch { XCTFail("Replay failed: \(error)") }
                finished.fulfill()
            }
            wait(for: [finished], timeout: 25)
        }
    }
}

private final class MixedReplayProtocol: URLProtocol {
    static var frames: [Data] = []
    private let delivery = DispatchQueue(label: "native-mixed-replay")
    private var pending: DispatchWorkItem?
    private var stopped = false

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }
    override func startLoading() {
        delivery.async {
            self.client?.urlProtocol(self, didReceive: HTTPURLResponse(url: self.request.url!, statusCode: 200, httpVersion: nil,
                headerFields: ["Content-Type": "text/event-stream"])!, cacheStoragePolicy: .notAllowed)
            self.schedule(0)
        }
    }
    private func schedule(_ index: Int) {
        let work = DispatchWorkItem { [weak self] in
            guard let self else { return }
            guard !self.stopped else { return }
            guard index < Self.frames.count else { self.client?.urlProtocolDidFinishLoading(self); return }
            self.client?.urlProtocol(self, didLoad: Self.frames[index])
            self.schedule(index + 1)
        }
        pending = work
        delivery.asyncAfter(deadline: .now() + .milliseconds(20), execute: work)
    }
    override func stopLoading() {
        delivery.async { self.stopped = true; self.pending?.cancel() }
    }
}
