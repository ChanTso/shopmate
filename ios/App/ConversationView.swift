import SwiftUI
import BuyerCore

struct ConversationView: View {
    @ObservedObject var model: BuyerModel
    @ObservedObject var chat: ConversationState
    var embedded = false
    @State private var history = false
    @State private var following = true
    var body: some View {
        VStack(spacing: 0) {
            if embedded {
                HStack(spacing: 11) {
                    Image(systemName: "sparkles").font(.title2).foregroundStyle(accent)
                    VStack(alignment: .leading, spacing: 4) { Text("选购有依据，操作有确认").font(.caption.weight(.medium)); Text("边看商品，边继续聊").font(.caption2).foregroundStyle(mutedInk) }
                    Spacer()
                }.padding(.horizontal, 20).padding(.vertical, 12).background(Color.white.opacity(0.4))
            }
            ScrollViewReader { proxy in
                ScrollView {
                    LazyVStack(alignment: .leading, spacing: 22) {
                        if chat.messages.isEmpty { welcome }
                        ForEach(Array(chat.messages.enumerated()), id: \.offset) { _, message in
                            VStack(alignment: .leading, spacing: 14) {
                                HStack(spacing: 8) {
                                    if !message.user { Image(systemName: "sparkles").font(.caption) }
                                    Text(message.user ? "我的想法" : "ShopMate").font(.caption.weight(.semibold))
                                }.foregroundStyle(message.user ? mutedInk : accent)
                                ForEach(Array(message.segments.enumerated()), id: \.offset) { _, segment in
                                    ChatSegmentView(model: model, segment: segment).equatable()
                                }
                                if !message.suggestions.isEmpty {
                                    VStack(alignment: .leading, spacing: 9) {
                                        ForEach(message.suggestions, id: \.self) { suggestion in
                                            Button { chat.draft = suggestion } label: {
                                                HStack(alignment: .firstTextBaseline, spacing: 10) { Text(suggestion).multilineTextAlignment(.leading); Spacer(minLength: 0); Image(systemName: "arrow.up.right").font(.caption2) }
                                                    .font(.caption.weight(.medium)).padding(.horizontal, 13).padding(.vertical, 10).background(paper, in: RoundedRectangle(cornerRadius: 12))
                                            }.buttonStyle(.plain).foregroundStyle(accent)
                                        }
                                    }.padding(.top, 3)
                                }
                            }.padding(message.user ? 18 : 19).frame(maxWidth: .infinity, alignment: .leading)
                                .background(message.user ? Color(red: 0.91, green: 0.875, blue: 0.805) : Color.white.opacity(0.88), in: RoundedRectangle(cornerRadius: 22))
                        }
                        if chat.running {
                            HStack(spacing: 10) { ProgressView().tint(accent); Text(chat.activity).font(.caption).foregroundStyle(mutedInk) }
                                .padding(.horizontal, 4).padding(.vertical, 6)
                        }
                        Color.clear.frame(height: 1).id("latest")
                    }.padding(18)
                }
                .simultaneousGesture(DragGesture().onChanged { value in if value.translation.height > 8 { following = false } })
                .onChange(of: chat.revision) { _, _ in if following { proxy.scrollTo("latest", anchor: .bottom) } }
                .onChange(of: chat.messages.count) { _, _ in if following { proxy.scrollTo("latest", anchor: .bottom) } }
                .overlay(alignment: .bottomTrailing) {
                    if !following { Button { following = true; proxy.scrollTo("latest", anchor: .bottom) } label: { Label("回到最新", systemImage: "arrow.down") }.font(.caption.weight(.semibold)).buttonStyle(.borderedProminent).padding() }
                }
            }
            HStack(alignment: .bottom, spacing: 11) {
                TextField("说说你想买什么…", text: $chat.draft, axis: .vertical).lineLimit(1...4).font(.system(size: 16)).padding(.horizontal, 16).padding(.vertical, 14)
                    .background(paper, in: RoundedRectangle(cornerRadius: 23)).overlay(RoundedRectangle(cornerRadius: 23).strokeBorder(softBorder.opacity(0.65), lineWidth: 0.8).allowsHitTesting(false)).accessibilityIdentifier("chat-input")
                if chat.running {
                    Button { model.stop() } label: { Image(systemName: "stop.fill").font(.system(size: 16)).foregroundStyle(.white).frame(width: 47, height: 47).background(ink, in: Circle()) }.accessibilityLabel("停止生成")
                } else {
                    Button { model.send(chat.draft); chat.draft = ""; following = true } label: {
                        Image(systemName: "arrow.up").font(.system(size: 20, weight: .semibold)).foregroundStyle(.white).frame(width: 47, height: 47)
                            .background(chat.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty ? mutedInk.opacity(0.35) : accent, in: Circle())
                    }.disabled(chat.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty).accessibilityIdentifier("chat-send").accessibilityLabel("发送")
                }
            }.padding(.horizontal, 17).padding(.vertical, 12).background(Color.white.opacity(0.94))
        }.background(paper).navigationTitle("购物助手").navigationBarTitleDisplayMode(.inline)
            .onChange(of: chat.conversationKey) { _, _ in following = true }
            .sheet(isPresented: $history) {
                NavigationStack {
                    List(model.conversations.map { IdentifiedObject(id: text($0, "session_id"), value: $0) }) { item in
                        Button { model.selectConversation(text(item.value, "session_id")); history = false } label: {
                            HStack(spacing: 13) { Image(systemName: "bubble.left").foregroundStyle(accent); Text(text(item.value, "title").isEmpty ? "历史对话" : text(item.value, "title")).foregroundStyle(ink); Spacer(); Image(systemName: "chevron.right").font(.caption).foregroundStyle(mutedInk) }.padding(.vertical, 6)
                        }.disabled(chat.running)
                    }.scrollContentBackground(.hidden).background(paper).navigationTitle("历史对话").toolbar { Button("完成") { history = false } }
                        .task { await model.fetchConversations() }
                }
            }
            .toolbar {
                Button { history = true } label: { Image(systemName: "clock.arrow.circlepath") }.accessibilityLabel("历史对话")
                Menu {
                    Button("恢复对话", systemImage: "arrow.clockwise") { model.reload() }
                    Button("新对话", systemImage: "square.and.pencil") { model.newConversation() }.disabled(chat.running)
                } label: { Image(systemName: "ellipsis.circle") }.accessibilityLabel("对话选项")
            }
    }
    private var welcome: some View {
        VStack(alignment: .leading, spacing: 24) {
            Image(systemName: "sparkles").font(.system(size: 39, weight: .light)).foregroundStyle(accent).padding(.top, 30)
            Text("最近，想给生活\n添点什么？").font(.system(size: 30, weight: .semibold, design: .serif)).lineSpacing(5)
            Text("告诉我你的预算和场景，\n一起选出真正合适的好物。").font(.subheadline).lineSpacing(5).foregroundStyle(mutedInk)
            VStack(spacing: 11) {
                prompt("从一杯咖啡开始", detail: "帮我推荐一款有货的咖啡机", icon: "cup.and.saucer")
                prompt("选购之前，先比较", detail: "比较两款适合家用的咖啡机", icon: "rectangle.split.2x1")
                prompt("把偏好交给助手", detail: "请记住，我喜欢紧凑、易清洁的咖啡器具", icon: "heart")
            }.padding(.top, 6)
        }.frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 5)
    }
    private func prompt(_ title: String, detail: String, icon: String) -> some View {
        Button { chat.draft = detail } label: {
            HStack(spacing: 13) { Image(systemName: icon).font(.title3).foregroundStyle(accent).frame(width: 30); Text(title).font(.subheadline.weight(.medium)); Spacer(); Image(systemName: "arrow.up.right").font(.caption).foregroundStyle(mutedInk) }
                .padding(17).foregroundStyle(ink).background(Color.white.opacity(0.85), in: RoundedRectangle(cornerRadius: 17))
        }.buttonStyle(.plain)
    }
}

struct ChatSegmentView: View, Equatable {
    let model: BuyerModel
    let segment: ChatSegment

    static func == (lhs: Self, rhs: Self) -> Bool {
        // The reducer replaces changed segments; unchanged cards retain their immutable instance.
        lhs.model === rhs.model && lhs.segment === rhs.segment
    }

    var body: some View {
        if let block = ChatCardPayload.decode(segment) {
            RecommendationCard(model: model, block: block, ready: segment.final)
        } else {
            Text(segment.text).font(.system(size: 16)).lineSpacing(6).textSelection(.enabled)
        }
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
                ProductImage(model: model, product: product).frame(width: 94, height: 108).clipShape(RoundedRectangle(cornerRadius: 12))
                VStack(alignment: .leading, spacing: 6) {
                    Text(ProductPresentation.title(product)).font(.subheadline.weight(.semibold))
                    Text(majorMoney(product["price"])).font(.system(size: 21, weight: .semibold, design: .rounded)).foregroundStyle(accent)
                    if !reason.isEmpty { Text(reason).font(.subheadline).foregroundStyle(.secondary) }
                }
            }
            HStack {
                Button("查看规格") { model.openProduct(text(product, "product_id")) }.disabled(!ready)
                if object(product, "options").isEmpty {
                    Button("加入购物车") {
                        model.confirm("加入 \(ProductPresentation.title(product)) × 1？结账时核对当前报价。") { model.add(product) }
                    }.buttonStyle(.bordered).disabled(!ready || model.writing || product["in_stock"] as? Bool == false)
                }
            }
        }
    }
}
