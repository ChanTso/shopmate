import SwiftUI
import BuyerCore

struct ConversationView: View {
    @ObservedObject var model: BuyerModel
    @ObservedObject var chat: ConversationState
    @State private var history = false
    @State private var following = true
    var body: some View {
        VStack(spacing: 0) {
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 18) {
                        if chat.messages.isEmpty {
                            Panel {
                                Text("最近想给生活添点什么？").font(.title2.bold())
                                Text("告诉我预算和场景，我会查商品、比较规格，再帮你规划。")
                                Button("帮我推荐一款咖啡机") { chat.draft = "帮我推荐一款有货的咖啡机" }
                            }
                        }
                        ForEach(chat.messages.indices, id: \.self) { i in
                            let message = chat.messages[i]
                            VStack(alignment: .leading, spacing: 12) {
                                Text(message.user ? "我" : "SHOPMATE").font(.caption.bold()).foregroundStyle(accent)
                                ForEach(message.segments.indices, id: \.self) { j in
                                    let segment = message.segments[j]
                                    if let raw = segment.blockJson, let block = try? jsonObject(Data(raw.utf8)) {
                                        RecommendationCard(model: model, block: block, ready: segment.final)
                                    } else { Text(segment.text).textSelection(.enabled) }
                                }
                                ForEach(message.suggestions, id: \.self) { suggestion in
                                    Button(suggestion) { chat.draft = suggestion }.buttonStyle(.bordered)
                                }
                            }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
                                .background(message.user ? Color.brown.opacity(0.10) : Color.white.opacity(0.8), in: RoundedRectangle(cornerRadius: 18))
                        }
                        if chat.running { HStack { ProgressView(); Text(chat.activity).font(.footnote) } }
                        Color.clear.frame(height: 1).id("latest")
                    }.padding(18)
                }
                .simultaneousGesture(DragGesture().onChanged { value in if value.translation.height > 8 { following = false } })
                .onChange(of: chat.revision) { _, _ in if following { proxy.scrollTo("latest", anchor: .bottom) } }
                .onChange(of: chat.messages.count) { _, _ in if following { proxy.scrollTo("latest", anchor: .bottom) } }
                .overlay(alignment: .bottomTrailing) {
                    if !following { Button("回到最新") { following = true; proxy.scrollTo("latest", anchor: .bottom) }.buttonStyle(.borderedProminent).padding() }
                }
            }
            HStack(alignment: .bottom, spacing: 10) {
                TextField("说说你想买什么", text: $chat.draft, axis: .vertical).lineLimit(1...4).textFieldStyle(.roundedBorder).accessibilityIdentifier("chat-input")
                if chat.running { Button("停止") { model.stop() } }
                else { Button("发送") { model.send(chat.draft); chat.draft = ""; following = true }.disabled(chat.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty).accessibilityIdentifier("chat-send") }
            }.padding().background(.white)
        }.background(paper).navigationTitle("购物助手")
            .onChange(of: chat.conversationKey) { _, _ in following = true }
            .sheet(isPresented: $history) {
                NavigationStack {
                    List(model.conversations.indices, id: \.self) { i in
                        let row = model.conversations[i]
                        Button(text(row, "title").isEmpty ? "历史对话" : text(row, "title")) {
                            model.selectConversation(text(row, "session_id")); history = false
                        }.disabled(chat.running)
                    }.navigationTitle("历史对话").toolbar { Button("关闭") { history = false } }
                        .task { await model.fetchConversations() }
                }
            }
            .toolbar { Button("历史") { history = true }; Button("恢复") { model.reload() }; Button("新对话") { model.newConversation() }.disabled(chat.running) }
    }
}

struct RecommendationCard: View {
    @ObservedObject var model: BuyerModel
    let block: Object
    let ready: Bool
    private var payload: Object { object(block, "payload") }
    private var component: String { text(block, "component") }
    var body: some View {
        Panel {
            Text(text(payload, "title").isEmpty ? title : text(payload, "title")).font(.headline)
            if !ready { Text("正在整理，完成后可操作").font(.caption).foregroundStyle(.secondary) }
            switch component {
            case "products":
                ForEach(rows(payload, "items").indices, id: \.self) { i in
                    let item = rows(payload, "items")[i]
                    CardProduct(model: model, product: object(item, "product"), reason: text(item, "reason"), ready: ready)
                }
            case "comparison":
                ForEach(rows(payload, "entries").indices, id: \.self) { i in
                    let entry = rows(payload, "entries")[i]
                    CardProduct(model: model, product: object(entry, "product"), reason: text(entry, "best_for"), ready: ready)
                    Text("优点：" + ((entry["pros"] as? [String]) ?? []).joined(separator: "；")).font(.subheadline)
                    Text("取舍：" + ((entry["cons"] as? [String]) ?? []).joined(separator: "；")).font(.subheadline).foregroundStyle(.secondary)
                    Divider()
                }
            case "plan":
                Text(text(payload, "intro"))
                ForEach(rows(payload, "steps").indices, id: \.self) { i in
                    let step = rows(payload, "steps")[i]
                    Text("\(i + 1). " + text(step, "label")).font(.headline)
                    Text(text(step, "detail"))
                    ForEach(rows(step, "products").indices, id: \.self) { j in
                        CardProduct(model: model, product: rows(step, "products")[j], reason: "", ready: ready)
                    }
                }
            case "guide":
                ForEach(rows(payload, "sections").indices, id: \.self) { i in
                    let section = rows(payload, "sections")[i]
                    Text(text(section, "heading")).font(.headline)
                    Text(text(section, "body"))
                }
                ForEach(rows(payload, "related_products").indices, id: \.self) { i in
                    CardProduct(model: model, product: rows(payload, "related_products")[i], reason: "", ready: ready)
                }
            case "checkout":
                Text(text(payload, "note"))
                Button("核对当前购物车") { model.reload(); model.tab = 2 }.disabled(!ready)
            case "order_status":
                Text(text(payload, "summary")); Text(text(payload, "next_step"))
                Button("查看实际订单状态") { model.reload(); model.tab = 3 }.disabled(!ready)
            case "refund_confirmation":
                let action = object(payload, "action")
                Text("订单尾号 " + text(action, "orderId").suffix(8))
                Text(money(action["amountMinor"], currency: text(action, "currency"))).foregroundStyle(accent)
                Text("核对当前申请后再确认；退款受理不代表到账。").font(.footnote)
                Button("核对退款申请") { model.reload(); model.tab = 3 }.disabled(!ready)
            case "web_sources":
                Text(text(payload, "summary"))
                let sources = rows(payload, "citations") + rows(payload, "consulted_sources")
                ForEach(sources.indices, id: \.self) { i in
                    let source = sources[i]
                    if let url = URL(string: text(source, "url")), ["https", "http"].contains(url.scheme ?? ""), url.host != nil {
                        Link(text(source, "title").isEmpty ? url.absoluteString : text(source, "title"), destination: url).disabled(!ready)
                    }
                }
                Text("外部网页仅供参考，价格与订单以商店记录为准。").font(.footnote).foregroundStyle(.secondary)
            default:
                Text("请结合助手说明查看，并在购物车或订单核对操作结果。").font(.footnote)
            }
        }
    }
    private var title: String {
        ["products": "为你找到", "comparison": "商品比较", "plan": "购物方案", "guide": "选购指南", "checkout": "核对购物车", "order_status": "订单进度", "refund_confirmation": "退款申请", "web_sources": "参考来源"][component] ?? "选购建议"
    }
}

struct CardProduct: View {
    @ObservedObject var model: BuyerModel
    let product: Object
    let reason: String
    let ready: Bool
    var body: some View {
        if !text(product, "product_id").isEmpty {
            HStack(alignment: .top, spacing: 12) {
                ProductImage(model: model, product: product).frame(width: 76, height: 76).clipShape(RoundedRectangle(cornerRadius: 12))
                VStack(alignment: .leading, spacing: 6) {
                    Text(text(product, "title")).font(.subheadline.bold())
                    Text(majorMoney(product["price"])).foregroundStyle(accent)
                    if !reason.isEmpty { Text(reason).font(.subheadline).foregroundStyle(.secondary) }
                }
            }
            HStack {
                Button("查看规格") { model.openProduct(text(product, "product_id")) }.disabled(!ready)
                if object(product, "options").isEmpty {
                    Button("加入购物车") {
                        model.confirm("加入 \(text(product, "title")) × 1？结账时核对当前报价。") { model.add(product) }
                    }.buttonStyle(.bordered).disabled(!ready || model.writing || product["in_stock"] as? Bool == false)
                }
            }
        }
    }
}
