import SwiftUI

struct DeliveryView: View {
    let value: Object
    var body: some View {
        let estimate = object(value, "estimate")
        ForEach(rows(estimate, "options").indices, id: \.self) { index in
            let option = rows(estimate, "options")[index]
            Text([(["delivery": "配送", "pickup": "自提"][text(option, "method")] ?? text(option, "method")), text(option, "earliestDate"), text(option, "latestDate"), money(option["feeMinor"], currency: text(estimate, "currency"))].filter { !$0.isEmpty }.joined(separator: " · "))
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
        let order = model.orders.first { text($0, "orderId") == text(action, "orderId") } ?? [:]
        Panel {
            HStack {
                Image(systemName: receipt.isEmpty ? "checkmark.shield" : "checkmark.seal.fill").foregroundStyle(accent)
                Text(receipt.isEmpty ? "请核对退款申请" : "退款申请已受理").font(.headline)
            }
            if !order.isEmpty {
                let product = productForDisplay(object(order, "product"), catalog: model.products)
                HStack(spacing: 12) {
                    ProductImage(model: model, product: product).frame(width: 65, height: 70).clipShape(RoundedRectangle(cornerRadius: 12))
                    VStack(alignment: .leading, spacing: 7) { Text(ProductPresentation.title(product)).font(.subheadline.weight(.medium)).lineLimit(2); Text("订单 · " + text(action, "orderId").suffix(8)).font(.caption2).foregroundStyle(mutedInk) }
                }
            } else { Text("订单 · " + text(action, "orderId").suffix(8)).font(.caption).foregroundStyle(mutedInk) }
            HStack { Text("申请退款").font(.subheadline).foregroundStyle(mutedInk); Spacer(); Text(money(action["amountMinor"], currency: text(action, "currency"))).font(.system(size: 25, weight: .semibold, design: .rounded)).foregroundStyle(accent) }
            if receipt.isEmpty {
                Text(statusLabel(text(action, "state")) + " · 有效期至 " + String(text(action, "expiresAt").prefix(16)).replacingOccurrences(of: "T", with: " ")).font(.caption2).foregroundStyle(mutedInk)
                Button {
                    model.confirm("确认提交订单尾号 \(text(action, "orderId").suffix(8)) 的退款申请，金额 \(money(action["amountMinor"]))？") {
                        model.transact("/actions/" + text(action, "pendingActionId") + "/confirm")
                    }
                } label: { Text("核对并确认退款").frame(maxWidth: .infinity).padding(.vertical, 4) }.buttonStyle(.borderedProminent).controlSize(.large).disabled(model.writing)
            } else { Text("受理不代表资金到账 · 回执 " + text(receipt, "receiptId").suffix(8)).font(.caption2).foregroundStyle(mutedInk) }
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
        let display = productForDisplay(product, catalog: model.products)
        let fulfillment = object(order, "fulfillment")
        let refund = model.actions.first { text(object($0, "action"), "orderId") == text(order, "orderId") && !object($0, "receipt").isEmpty }
        Panel {
            HStack {
                HStack(spacing: 6) { Circle().fill(accent).frame(width: 6, height: 6); Text(statusLabel(text(order, "status"))).font(.caption.weight(.semibold)) }.foregroundStyle(accent)
                Spacer(); Text(String(text(order, "createdAt").prefix(10))).font(.caption2).foregroundStyle(mutedInk)
            }
            HStack(alignment: .top, spacing: 14) {
                ProductImage(model: model, product: display).frame(width: 94, height: 104).clipShape(RoundedRectangle(cornerRadius: 16))
                VStack(alignment: .leading, spacing: 8) {
                    Text(ProductPresentation.title(display)).font(.subheadline.weight(.semibold)).lineLimit(3)
                    Text("数量 \((product["quantity"] as? NSNumber)?.intValue ?? (order["quantity"] as? NSNumber)?.intValue ?? 1)").font(.caption).foregroundStyle(mutedInk)
                    Text(money(product["totalPriceMinor"], currency: text(product, "currency"))).font(.system(size: 20, weight: .semibold, design: .rounded)).foregroundStyle(ink)
                }.frame(maxWidth: .infinity, alignment: .leading)
            }
            if let refund {
                HStack(alignment: .top, spacing: 8) {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(Color(red: 0.30, green: 0.45, blue: 0.33))
                    VStack(alignment: .leading, spacing: 4) {
                        Text("退款申请已受理 · " + money(object(refund, "action")["amountMinor"])).font(.caption.weight(.medium))
                        Text("申请处理中，可在售后回执查看详情。").font(.caption2).foregroundStyle(mutedInk)
                    }
                }.padding(12).frame(maxWidth: .infinity, alignment: .leading).background(paper, in: RoundedRectangle(cornerRadius: 12))
            }
            if !fulfillment.isEmpty {
                HStack(spacing: 8) { Image(systemName: "shippingbox"); Text("履约进度：" + statusLabel(text(fulfillment, "stage"))) }.font(.caption).foregroundStyle(mutedInk)
                if !text(fulfillment, "estimatedDeliveryAt").isEmpty { Text(text(fulfillment, "estimatedDeliveryAt")).font(.caption) }
                if !text(fulfillment, "delayReason").isEmpty { Text(text(fulfillment, "delayReason")).font(.caption).foregroundStyle(mutedInk) }
            }
            Divider().overlay(softBorder.opacity(0.3))
            Text("订单 · " + text(order, "orderId").suffix(8)).font(.caption2.monospaced()).foregroundStyle(mutedInk)
            if text(order, "orderKind") == "SECKILL" && text(order, "status") == "UNPAID" {
                Button("核对并模拟付款") {
                    model.confirm("确认模拟支付 \(money(product["totalPriceMinor"]))？不会扣取真实资金。") { model.transact("/orders/" + text(order, "orderId") + "/pay") }
                }.buttonStyle(.borderedProminent).disabled(model.writing)
            }
            HStack {
                Button { model.chat.draft = "查询订单 " + text(order, "orderId") + " 的状态和售后政策"; model.tab = 1 } label: { Label("问问助手", systemImage: "sparkles") }
                Spacer(minLength: 0)
                if text(object(order, "payment"), "state") == "SUCCEEDED" {
                    Button("申请售后") {
                        let paid = (object(order, "payment")["amountMinor"] as? NSNumber)?.int64Value ?? 0
                        let reserved = (object(order, "refunds")["reservedAmountMinor"] as? NSNumber)?.int64Value ?? 0
                        amount = NSDecimalNumber(decimal: Decimal(max(0, paid - reserved)) / 100).stringValue
                        preparing = true
                    }.disabled(model.writing)
                }
            }.font(.caption.weight(.medium)).buttonStyle(.bordered)
        }.alert("准备退款申请", isPresented: $preparing) {
            TextField("退款金额（元）", text: $amount).keyboardType(.decimalPad)
            Button("准备申请") { model.refund(order, amount: amount) }
            Button("取消", role: .cancel) { }
        } message: { Text("先准备申请，再核对确认。可退额度由商店重新校验。") }
    }
}

// Search results may be stale; cart and order snapshots own their names and supplied artwork.
func productForDisplay(_ source: Object, catalog: [Object]) -> Object {
    guard let current = catalog.first(where: { ProductPresentation.productID($0) == ProductPresentation.productID(source) }) else { return source }
    var result = source
    if text(source, "category").isEmpty { result["category"] = current["category"] }
    let supplied = [text(source, "image_url"), text(source, "imageUrl"), text(object(source, "content"), "imageUrl")]
    if supplied.allSatisfy({ $0.isEmpty }) {
        let images = [text(current, "image_url"), text(current, "imageUrl"), text(object(current, "content"), "imageUrl")]
        result["image_url"] = images.first { !$0.isEmpty }
    }
    return result
}

struct MemoryView: View {
    @ObservedObject var model: BuyerModel
    @State private var policy = "退款"
    @State private var showPolicies = false
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                VStack(alignment: .leading, spacing: 18) {
                    HStack {
                        Image(systemName: "sparkles").font(.system(size: 28, weight: .light)).foregroundStyle(Color(red: 0.83, green: 0.72, blue: 0.52))
                        Spacer(); Text("为你记住").font(.caption).tracking(2).foregroundStyle(.white.opacity(0.65))
                    }
                    Text("你的偏好，\n值得被认真记住。").font(.system(size: 28, weight: .semibold, design: .serif)).lineSpacing(5)
                    Text("从喜欢的风格，到在意的小细节。\n下一次选购，可以从更懂你开始。").font(.subheadline).lineSpacing(5).foregroundStyle(.white.opacity(0.7))
                    HStack(spacing: 16) {
                        Text("\(model.memories.count)").font(.system(size: 36, weight: .medium, design: .serif))
                        VStack(alignment: .leading, spacing: 3) { Text("条长期偏好").font(.caption); Text("由你修改，随时删除").font(.caption2).foregroundStyle(.white.opacity(0.55)) }
                    }.padding(.top, 2)
                }.padding(25).foregroundStyle(.white).frame(maxWidth: .infinity, alignment: .leading).background(ink, in: RoundedRectangle(cornerRadius: 26))
                HStack { Text("我的偏好").font(.system(size: 24, weight: .semibold, design: .serif)); Spacer(); Label("仅为你使用", systemImage: "person.crop.circle").font(.caption).foregroundStyle(mutedInk) }
                if model.memories.isEmpty {
                    Panel {
                        Image(systemName: "heart.text.clipboard").font(.largeTitle).foregroundStyle(accent.opacity(0.65))
                        Text("从一次聊天开始").font(.headline)
                        Text("告诉助手你喜欢什么、在意什么。保存的购物偏好会出现在这里。").font(.subheadline).foregroundStyle(mutedInk).lineSpacing(4)
                        Button("和助手聊聊") { model.tab = 1 }.buttonStyle(.borderedProminent)
                    }
                }
                ForEach(model.memories.map { IdentifiedObject(id: text($0, "key"), value: $0) }) { item in MemoryRow(model: model, fact: item.value) }
                HStack(alignment: .top, spacing: 9) { Image(systemName: "hand.raised"); Text("助手只记住你的购物偏好。商品价格与订单进度会在每次操作时重新核对。").lineSpacing(3) }.font(.caption).foregroundStyle(mutedInk).padding(.horizontal, 3)
                Panel {
                    DisclosureGroup(isExpanded: $showPolicies) {
                        HStack {
                            TextField("配送、退款或其他政策", text: $policy).submitLabel(.search).onSubmit { Task { await model.fetchPolicies(policy) } }
                            Button { Task { await model.fetchPolicies(policy) } } label: { Image(systemName: "magnifyingglass") }.accessibilityLabel("查询政策")
                        }.padding(12).background(paper, in: RoundedRectangle(cornerRadius: 12)).padding(.top, 10)
                        ForEach(Array(model.policies.enumerated()), id: \.offset) { _, item in
                            VStack(alignment: .leading, spacing: 8) { Text(text(item, "title")).font(.subheadline.weight(.semibold)); Text(text(item, "content")).font(.caption).lineSpacing(4).foregroundStyle(mutedInk) }.padding(.top, 12)
                        }
                    } label: {
                        HStack(spacing: 12) { Image(systemName: "shippingbox").font(.title3).foregroundStyle(accent); VStack(alignment: .leading, spacing: 4) { Text("购物政策").font(.subheadline.weight(.semibold)); Text("配送与退换，让选购更安心").font(.caption).foregroundStyle(mutedInk) } }.foregroundStyle(ink)
                    }
                }
            }.padding(20)
        }.background(paper).navigationTitle("助手记忆").navigationBarTitleDisplayMode(.inline).task { await model.fetchProfile(); await model.fetchPolicies(policy) }
    }
}

struct MemoryRow: View {
    @ObservedObject var model: BuyerModel
    let fact: Object
    @State private var editing = false
    @State private var deleting = false
    @State private var value = ""
    private var category: (String, String) {
        switch text(fact, "category") {
        case "preference": ("购物偏好", "heart")
        case "constraint": ("在意的条件", "slider.horizontal.3")
        case "profile": ("个人习惯", "person")
        case "budget": ("预算偏好", "wallet.pass")
        case "interest": ("兴趣灵感", "sparkles")
        default: ("选购备忘", "bookmark")
        }
    }
    var body: some View {
        Panel {
            HStack(spacing: 9) {
                Image(systemName: category.1).font(.system(size: 15)).foregroundStyle(accent).frame(width: 34, height: 34).background(accent.opacity(0.08), in: RoundedRectangle(cornerRadius: 11))
                Text(category.0).font(.caption.weight(.medium)).foregroundStyle(mutedInk)
                Spacer()
                Menu {
                    Button("修改偏好", systemImage: "pencil") { value = text(fact, "value"); editing = true }
                    Button("删除偏好", systemImage: "trash", role: .destructive) { deleting = true }
                } label: { Image(systemName: "ellipsis").font(.headline).foregroundStyle(mutedInk).frame(width: 32, height: 32) }.accessibilityLabel("管理购物偏好")
            }
            Text(text(fact, "value")).font(.system(size: 18, weight: .medium, design: .serif)).lineSpacing(7).fixedSize(horizontal: false, vertical: true)
            HStack { Text("用于今后的选购建议").font(.caption2).foregroundStyle(mutedInk); Spacer(); Button("修改") { value = text(fact, "value"); editing = true }.font(.caption.weight(.medium)) }
        }.alert("修改购物偏好", isPresented: $editing) {
            TextField("偏好", text: $value)
            Button("保存") { Task { await model.editMemory(key: text(fact, "key"), value: value) } }
            Button("取消", role: .cancel) { }
        }.confirmationDialog("删除这条购物偏好？", isPresented: $deleting, titleVisibility: .visible) {
            Button("删除偏好", role: .destructive) { Task { await model.editMemory(key: text(fact, "key"), value: "", delete: true) } }
            Button("保留", role: .cancel) { }
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
