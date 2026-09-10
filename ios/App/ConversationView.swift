import SwiftUI
import BuyerCore

struct ConversationView: View {
    @ObservedObject var model: BuyerModel
    @ObservedObject var chat: ConversationState
    @State private var draft = ""
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
                                Button("帮我推荐一款咖啡机") { draft = "帮我推荐一款有货的咖啡机" }
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
                                    Button(suggestion) { draft = suggestion }.buttonStyle(.bordered)
                                }
                            }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
                                .background(message.user ? Color.brown.opacity(0.10) : Color.white.opacity(0.8), in: RoundedRectangle(cornerRadius: 18))
                        }
                        if chat.running { HStack { ProgressView(); Text(chat.activity).font(.footnote) } }
                        Color.clear.frame(height: 1).id("latest")
                    }.padding(18)
                }
                .simultaneousGesture(DragGesture().onChanged { value in if value.translation.height > 8 { following = false } })
                .onChange(of: chat.messages.last?.segments.last?.text.count ?? 0) { _, _ in if following { proxy.scrollTo("latest", anchor: .bottom) } }
                .onChange(of: chat.messages.count) { _, _ in if following { proxy.scrollTo("latest", anchor: .bottom) } }
                .overlay(alignment: .bottomTrailing) {
                    if !following { Button("回到最新") { following = true; proxy.scrollTo("latest", anchor: .bottom) }.buttonStyle(.borderedProminent).padding() }
                }
            }
            HStack(alignment: .bottom, spacing: 10) {
                TextField("说说你想买什么", text: $draft, axis: .vertical).lineLimit(1...4).textFieldStyle(.roundedBorder).accessibilityIdentifier("chat-input")
                if chat.running { Button("停止") { model.stop() } }
                else { Button("发送") { model.send(draft); draft = ""; following = true }.disabled(draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty).accessibilityIdentifier("chat-send") }
            }.padding().background(.white)
        }.background(paper).navigationTitle("购物助手")
            .toolbar { Button("恢复") { model.reload() }; Button("新对话") { model.newConversation() }.disabled(chat.running) }
    }
}

struct RecommendationCard: View {
    @ObservedObject var model: BuyerModel
    let block: Object
    let ready: Bool
    private var payload: Object { object(block, "payload") }
    private var component: String { text(block, "component") }
    private var products: [Object] {
        switch component {
        case "products": return rows(payload, "items").map { object($0, "product") }
        case "comparison": return rows(payload, "entries").map { object($0, "product") }
        case "plan": return rows(payload, "steps").flatMap { rows($0, "products") }
        case "guide": return rows(payload, "related_products")
        default: return []
        }
    }
    var body: some View {
        Panel {
            Text(text(payload, "title").isEmpty ? "选购建议" : text(payload, "title")).font(.headline)
            if !ready { Text("正在整理，完成后可操作").font(.caption).foregroundStyle(.secondary) }
            if !text(payload, "intro").isEmpty { Text(text(payload, "intro")) }
            if !text(payload, "summary").isEmpty { Text(text(payload, "summary")) }
            ForEach(products.indices, id: \.self) { i in
                let product = products[i]
                if !text(product, "product_id").isEmpty {
                    Text(text(product, "title")).font(.subheadline.bold())
                    Text(majorMoney(product["price"])).foregroundStyle(accent)
                    HStack {
                        Button("查看规格") { model.openProduct(text(product, "product_id")) }.disabled(!ready)
                        if object(product, "options").isEmpty {
                            Button("加入购物车") {
                                model.confirm("加入 \(text(product, "title")) × 1？结账时将核对当前报价。") { model.add(product) }
                            }.buttonStyle(.bordered).disabled(!ready || model.writing || product["in_stock"] as? Bool == false)
                        }
                    }
                    Divider()
                }
            }
            if component == "checkout" { Button("核对购物车") { model.tab = 2 }.disabled(!ready) }
            if products.isEmpty && component != "checkout" {
                Text("请结合助手说明查看；付款状态以订单回执为准。").font(.footnote).foregroundStyle(.secondary)
            }
        }
    }
}
