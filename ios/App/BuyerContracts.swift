import Foundation

func refundMinor(_ input: String) throws -> Int64 {
    let value = input.trimmingCharacters(in: .whitespacesAndNewlines)
    guard value.range(of: #"^[0-9]+(?:\.[0-9]{1,2})?$"#, options: .regularExpression) != nil,
          let decimal = Decimal(string: value, locale: Locale(identifier: "en_US_POSIX")), decimal > 0 else {
        throw BuyerFailure(status: 400, category: "", message: "请输入大于零、最多两位小数的退款金额")
    }
    let minor = decimal * 100
    guard minor <= Decimal(Int64.max) else { throw BuyerFailure(status: 400, category: "", message: "退款金额过大") }
    return NSDecimalNumber(decimal: minor).int64Value
}

struct SeckillTicket: Codable, Identifiable {
    let key: String
    let activityId: String
    let activityVersion: Int64
    var reservationId: String?
    var state = "UNKNOWN"
    var decision = ""
    var orderId: String?
    var id: String { key }
    var terminal: Bool { ["ORDERED", "REJECTED", "CANCELLED", "UNFULFILLED"].contains(state) }
    func result(_ reply: Object) -> Self {
        var copy = self
        if !text(reply, "reservationId").isEmpty { copy.reservationId = text(reply, "reservationId") }
        copy.state = text(reply, "state"); copy.decision = text(reply, "decisionCode")
        copy.orderId = text(reply, "orderId").isEmpty ? nil : text(reply, "orderId")
        return copy
    }
}

func statusLabel(_ state: String) -> String {
    ["PAID": "已付款", "UNPAID": "待付款", "CANCELLED": "已取消", "SUCCEEDED": "已完成", "REQUESTED": "已受理", "PROCESSING": "处理中", "PENDING": "待确认", "PREPARED": "待确认", "EXPIRED": "已过期", "SHIPPED": "已发货", "DELIVERED": "已送达", "ORDERED": "已成单", "ADMITTED": "排队成单中", "REJECTED": "预约未获准", "UNFULFILLED": "未能成单", "UNKNOWN": "结果待核对"][state] ?? state
}
