import BuyerCore
import Foundation
import os

enum ChatCardPayload {
    private static let log = OSLog(subsystem: "io.shopmate.buyer.ios", category: "ChatCard")

    static func decode(_ segment: ChatSegment) -> Object? {
        guard segment.block != nil else { return nil }
        let id = OSSignpostID(log: log)
        os_signpost(.begin, log: log, name: "Decode card", signpostID: id)
        defer { os_signpost(.end, log: log, name: "Decode card", signpostID: id) }
        guard let raw = segment.blockJson else { return nil }
        return try? jsonObject(Data(raw.utf8))
    }
}
