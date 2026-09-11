import SwiftUI

struct DeliveryView: View {
    let value: Object
    var body: some View {
        let estimate = object(value, "estimate")
        ForEach(rows(estimate, "options").indices, id: \.self) { index in
            let option = rows(estimate, "options")[index]
            Text([text(option, "method"), text(option, "earliestDate"), text(option, "latestDate"), money(option["feeMinor"], currency: text(estimate, "currency"))].filter { !$0.isEmpty }.joined(separator: " · "))
        }
        if !value.isEmpty { Text("配送仅为估算，不代表已发货或已收取运费。").font(.footnote).foregroundStyle(.secondary) }
    }
}

struct RefundActionView: View {
    @ObservedObject var model: BuyerModel
    let row: Object
    var body: some View {
        let action = object(row, "action")
        let receipt = object(row, "receipt")
        Panel {
            Text(receipt.isEmpty ? "退款申请待核对" : "退款申请已受理").font(.headline)
            Text(money(action["amountMinor"], currency: text(action, "currency"))).foregroundStyle(accent)
            Text("订单尾号 " + text(action, "orderId").suffix(8)).font(.footnote)
            if receipt.isEmpty {
                Text(statusLabel(text(action, "state")) + " · 有效期至 " + text(action, "expiresAt")).font(.footnote)
                Button("核对并确认退款") {
                    model.confirm("确认提交订单尾号 \(text(action, "orderId").suffix(8)) 的退款申请，金额 \(money(action["amountMinor"]))？") {
                        model.transact("/actions/" + text(action, "pendingActionId") + "/confirm")
                    }
                }.buttonStyle(.borderedProminent).disabled(model.writing)
            } else { Text("受理不代表资金到账 · 回执尾号 " + text(receipt, "receiptId").suffix(8)).font(.footnote) }
        }
    }
}

struct OrderDetailPanel: View {
    @ObservedObject var model: BuyerModel
    let order: Object
    @State private var preparing = false
    @State private var amount = ""
    var body: some View {
        let product = object(order, "product")
        let fulfillment = object(order, "fulfillment")
        Panel {
            HStack {
                Text(statusLabel(text(order, "status"))).font(.headline).foregroundStyle(accent)
                Spacer(); Text(String(text(order, "createdAt").prefix(10))).font(.caption)
            }
            Text(text(product, "name")).font(.headline)
            Text(money(product["totalPriceMinor"], currency: text(product, "currency")))
            Text("订单尾号 " + text(order, "orderId").suffix(8)).font(.footnote)
            if !fulfillment.isEmpty {
                Text("履约进度：" + statusLabel(text(fulfillment, "stage")))
                Text(text(fulfillment, "estimatedDeliveryAt")); Text(text(fulfillment, "delayReason"))
            }
            if text(order, "orderKind") == "SECKILL" && text(order, "status") == "UNPAID" {
                Button("核对并模拟付款") {
                    model.confirm("确认模拟支付 \(money(product["totalPriceMinor"]))？不会扣取真实资金。") { model.transact("/orders/" + text(order, "orderId") + "/pay") }
                }.buttonStyle(.borderedProminent).disabled(model.writing)
            }
            HStack {
                Button("问问助手") { model.chat.draft = "查询订单 " + text(order, "orderId") + " 的状态和售后政策"; model.tab = 1 }
                if text(object(order, "payment"), "state") == "SUCCEEDED" {
                    Button("申请售后") {
                        let paid = (object(order, "payment")["amountMinor"] as? NSNumber)?.int64Value ?? 0
                        let reserved = (object(order, "refunds")["reservedAmountMinor"] as? NSNumber)?.int64Value ?? 0
                        amount = NSDecimalNumber(decimal: Decimal(max(0, paid - reserved)) / 100).stringValue
                        preparing = true
                    }.disabled(model.writing)
                }
            }.buttonStyle(.bordered)
        }.alert("准备退款申请", isPresented: $preparing) {
            TextField("退款金额（元）", text: $amount).keyboardType(.decimalPad)
            Button("准备申请") { model.refund(order, amount: amount) }
            Button("取消", role: .cancel) { }
        } message: { Text("先准备申请，再核对确认。可退额度由商店重新校验。") }
    }
}

struct MemoryView: View {
    @ObservedObject var model: BuyerModel
    @State private var policy = "退款"
    var body: some View {
        List {
            Section("助手记忆") {
                Text("购物偏好可修改或删除。价格、订单和权限以商店记录为准。").font(.footnote)
                if model.memories.isEmpty { Text("尚未记录长期偏好") }
                ForEach(model.memories.indices, id: \.self) { MemoryRow(model: model, fact: model.memories[$0]) }
            }
            Section("购物政策") {
                HStack {
                    TextField("查找政策", text: $policy)
                    Button("查询") { Task { await model.fetchPolicies(policy) } }
                }
                ForEach(model.policies.indices, id: \.self) { i in
                    VStack(alignment: .leading, spacing: 8) {
                        Text(text(model.policies[i], "title")).font(.headline)
                        Text(text(model.policies[i], "content"))
                    }
                }
            }
        }.navigationTitle("偏好与政策").task { await model.fetchProfile(); await model.fetchPolicies(policy) }
    }
}

struct MemoryRow: View {
    @ObservedObject var model: BuyerModel
    let fact: Object
    @State private var editing = false
    @State private var value = ""
    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(text(fact, "value"))
            Text(text(fact, "category")).font(.caption).foregroundStyle(.secondary)
            HStack {
                Button("修改") { value = text(fact, "value"); editing = true }
                Button("删除", role: .destructive) { Task { await model.editMemory(key: text(fact, "key"), value: "", delete: true) } }
            }.buttonStyle(.borderless)
        }.alert("修改购物偏好", isPresented: $editing) {
            TextField("偏好", text: $value)
            Button("保存") { Task { await model.editMemory(key: text(fact, "key"), value: value) } }
            Button("取消", role: .cancel) { }
        }
    }
}

struct SeckillView: View {
    @ObservedObject var model: BuyerModel
    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 18) {
                Text("先预约，再等待成单。付款前核对订单，未付款订单会按期限取消。").foregroundStyle(.secondary)
                ForEach(model.offers.indices, id: \.self) { i in
                    let offer = model.offers[i]
                    Panel {
                        Text(text(offer, "name")).font(.title3.bold())
                        Text(money(offer["unitPriceMinor"], currency: text(offer, "currency"))).foregroundStyle(accent)
                        Text("开始 " + text(offer, "startsAt")).font(.caption)
                        Text("结束 " + text(offer, "endsAt")).font(.caption)
                        Button("预约／查询原预约") {
                            model.confirm("确认预约 \(text(offer, "name")) × 1？最终付款请核对生成的订单。") { model.reserve(offer) }
                        }.buttonStyle(.borderedProminent).disabled(model.writing)
                    }
                }
                if model.offers.isEmpty { Text("当前没有可展示的活动") }
                Text("我的预约").font(.title2.bold())
                ForEach(model.tickets) { ticket in
                    Panel {
                        Text(statusLabel(ticket.state)).font(.headline)
                        Text("预约尾号 " + (ticket.reservationId ?? ticket.key).suffix(8)).font(.footnote)
                        if ticket.state == "REJECTED" { Text(rejection(ticket.decision)).foregroundStyle(.secondary) }
                        HStack {
                            Button("查询原预约") { model.retrySeckill(ticket) }.disabled(model.writing)
                            if ticket.orderId != nil { Button("查看订单") { model.reload(); model.tab = 3 } }
                        }.buttonStyle(.bordered)
                    }
                }
            }.padding(18)
        }.background(paper).navigationTitle("限量发售")
            .task { await model.loadSeckill() }
            .toolbar { Button("刷新") { Task { await model.loadSeckill() } } }
    }
    private func rejection(_ code: String) -> String {
        ["EXHAUSTED": "活动配额已售罄", "DUPLICATE_USER": "每人限购一次，请查看原订单", "NOT_OPEN": "活动尚未开始", "STALE_VERSION": "活动已更新，请刷新后核对", "EXPIRED": "活动已结束", "ACTIVITY_INACTIVE": "活动暂不可用"][code] ?? "当前条件不满足，请核对活动状态"
    }
}
