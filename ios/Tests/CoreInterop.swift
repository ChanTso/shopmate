import BuyerCore

// Compiled against the actual Kotlin/Native framework, including throwing calls and collection bridging.
func checkSharedCore() throws {
    let timeline = ChatTimeline()
    try timeline.restorePage(payload: "{\"session_id\":\"interop\",\"status\":\"completed\",\"items\":[{\"message_id\":3,\"kind\":\"user\",\"text\":\"旧问题\"},{\"message_id\":4,\"kind\":\"assistant\",\"segments\":[]}],\"next_before\":3}", sessionId: "interop")
    precondition(timeline.nextBefore?.int64Value == 3)
    let inserted = try timeline.prependPage(payload: "{\"session_id\":\"interop\",\"status\":\"completed\",\"items\":[{\"message_id\":1,\"kind\":\"user\",\"text\":\"最早问题\"},{\"message_id\":2,\"kind\":\"assistant\",\"segments\":[]}],\"next_before\":null}", before: 3)
    precondition(inserted)
    let decoder = StreamDecoder()
    _ = try decoder.line(raw: "event: turn_started")
    _ = try decoder.line(raw: "data: {\"session_id\":\"interop\",\"user_message_id\":5,\"assistant_message_id\":6}")
    if let event = try decoder.line(raw: "") {
        try timeline.begin(text: "比较商品", event: event, sessionId: "interop")
    }
    _ = try decoder.line(raw: "event: text_delta")
    _ = try decoder.line(raw: "data: {\"text\":\"推荐\"}")
    if let event = try decoder.line(raw: "") {
        try timeline.accept(event: event)
    }
    precondition(timeline.messages.last?.segments.last?.text == "推荐")
    precondition(timeline.messages.last?.messageId == 6)
    precondition(timeline.nextBefore == nil)
    timeline.interrupt()
    precondition(timeline.messages.last?.pending == false)
    let command = try WriteRecovery.shared.prepare(key: "intent", path: "/cart/add", body: "{\"productId\":\"a\",\"quantity\":1}")
    let encoded = WriteRecovery.shared.encode(pending: command)
    let restored = try WriteRecovery.shared.decode(payload: encoded)
    precondition(restored.key == command.key)
}
