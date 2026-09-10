import BuyerCore

// Compiled against the actual Kotlin/Native framework, including throwing calls and collection bridging.
func checkSharedCore() throws {
    let timeline = ChatTimeline()
    timeline.begin(text: "比较商品")
    let decoder = StreamDecoder()
    _ = try decoder.line(raw: "event: text_delta")
    _ = try decoder.line(raw: "data: {\"text\":\"推荐\"}")
    if let event = try decoder.line(raw: "") {
        try timeline.accept(event: event)
    }
    precondition(timeline.messages.last?.segments.last?.text == "推荐")
    let command = try WriteRecovery.shared.prepare(key: "intent", path: "/cart/add", body: "{\"productId\":\"a\",\"quantity\":1}")
    let encoded = WriteRecovery.shared.encode(pending: command)
    let restored = try WriteRecovery.shared.decode(payload: encoded)
    precondition(restored.key == command.key)
}
