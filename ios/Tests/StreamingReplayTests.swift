import XCTest
import SwiftUI
import BuyerCore
@testable import ShopMate

/// A fixed render-layer workload; it does not measure model latency or a physical display.
final class StreamingReplayTests: XCTestCase {
    @MainActor
    func testNativeLongConversationReplay() throws {
        let suite = "render-replay-" + UUID().uuidString
        let defaults = try XCTUnwrap(UserDefaults(suiteName: suite))
        defer { defaults.removePersistentDomain(forName: suite) }
        let storage = BuyerStorage(defaults: defaults)
        storage.endpoint = "https://render-replay.test"
        let model = BuyerModel(api: BuyerAPI(), storage: storage)
        let history: [Object] = (0..<60).map { index in
            index.isMultiple(of: 2)
                ? ["kind": "user", "text": "第\(index / 2 + 1)轮：请比较适合日常使用的咖啡器具。"]
                : ["kind": "assistant", "segments": [["type": "text", "text": String(repeating: "先比较容量、清洁方式和占地，再结合预算选择。", count: 12)]]]
        }
        let snapshot = try jsonText(["items": history])
        let scene = try XCTUnwrap(UIApplication.shared.connectedScenes.first as? UIWindowScene)
        let window = UIWindow(windowScene: scene)
        window.frame = scene.coordinateSpace.bounds
        window.windowLevel = .normal + 1
        window.rootViewController = UIHostingController(rootView: NavigationStack {
            ConversationView(model: model, chat: model.chat)
        })
        window.makeKeyAndVisible()
        defer { window.isHidden = true; window.rootViewController = nil }
        let options = XCTMeasureOptions()
        options.iterationCount = 3
        measure(metrics: [XCTClockMetric(), XCTCPUMetric(), XCTMemoryMetric()], options: options) {
            let finished = expectation(description: "fixed 12 second render replay")
            Task { @MainActor in
                do {
                    model.chat.clear()
                    try model.chat.timeline.restore(payload: snapshot)
                    model.chat.timeline.begin(text: "请继续比较，保留具体取舍。")
                    model.chat.messages = model.chat.timeline.messages
                    model.chat.running = true
                    let decoder = StreamDecoder()
                    for _ in 0..<240 {
                        _ = try decoder.line(raw: "event: text_delta")
                        _ = try decoder.line(raw: "data: {\"text\":\"选购建议\"}")
                        let event = try XCTUnwrap(decoder.line(raw: ""))
                        try model.chat.timeline.accept(event: event)
                        model.chat.messages = model.chat.timeline.messages
                        model.chat.revision += 1
                        try await Task.sleep(for: .milliseconds(50))
                    }
                    let rendered = UIGraphicsImageRenderer(bounds: window.bounds).image { _ in
                        window.drawHierarchy(in: window.bounds, afterScreenUpdates: true)
                    }
                    let attachment = XCTAttachment(image: rendered)
                    attachment.name = "Native replay final frame"
                    attachment.lifetime = .keepAlways
                    self.add(attachment)
                    model.chat.running = false
                    XCTAssertEqual(model.chat.messages.last?.segments.last?.text.count, 960)
                } catch { XCTFail("Replay failed: \(error)") }
                finished.fulfill()
            }
            wait(for: [finished], timeout: 25)
        }
    }
}
