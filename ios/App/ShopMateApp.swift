import SwiftUI
import BuyerCore

let paper = Color(red: 0.965, green: 0.945, blue: 0.902)
let ink = Color(red: 0.10, green: 0.095, blue: 0.065)
let accent = Color(red: 0.745, green: 0.22, blue: 0.157)
let mutedInk = Color(red: 0.45, green: 0.43, blue: 0.37)
let softBorder = Color(red: 0.87, green: 0.83, blue: 0.74)

@main
struct ShopMateApp: App {
    @StateObject private var model = BuyerModel()
    var body: some Scene {
        WindowGroup { BuyerRoot(model: model).tint(accent).preferredColorScheme(.light) }
    }
}

struct BuyerRoot: View {
    @ObservedObject var model: BuyerModel
    var body: some View {
        GeometryReader { geometry in
            VStack(spacing: 0) {
                if let error = model.error {
                    HStack { Image(systemName: "exclamationmark.circle"); Text(error).font(.footnote); Spacer(); Button("关闭") { model.error = nil } }
                        .padding().background(Color(red: 0.98, green: 0.86, blue: 0.82))
                }
                if model.signedIn {
                    if geometry.size.width >= 850 { wideLayout(width: geometry.size.width) }
                    else {
                        TabView(selection: $model.tab) {
                            NavigationStack { CatalogView(model: model) }.tabItem { Label("探索", systemImage: "house") }.tag(0)
                            NavigationStack { ConversationView(model: model, chat: model.chat) }.tabItem { Label("助手", systemImage: "sparkles") }.tag(1)
                            NavigationStack { CartView(model: model) }.tabItem { Label("购物车", systemImage: "bag") }.tag(2)
                            NavigationStack { CheckoutView(model: model) }.tabItem { Label("订单", systemImage: "receipt") }.tag(3)
                            NavigationStack { RecoveryView(model: model) }.tabItem { Label("我的", systemImage: "person") }.tag(4)
                        }.toolbarBackground(paper.opacity(0.96), for: .tabBar)
                    }
                } else { LoginView(model: model) }
            }.frame(maxWidth: .infinity, maxHeight: .infinity).background(paper)
        }
        .alert(item: $model.confirmation) { value in
            Alert(title: Text("请核对后确认"), message: Text(value.message),
                  primaryButton: .default(Text("确认提交"), action: value.action), secondaryButton: .cancel(Text("再看一下")))
        }
        .sheet(isPresented: Binding(get: { model.selected != nil }, set: { if !$0 { model.selected = nil } })) {
            if let product = model.selected { NavigationStack { ProductView(model: model, product: product) } }
        }
    }
    private func wideLayout(width: CGFloat) -> some View {
        HStack(spacing: 0) {
            VStack(spacing: 28) {
                Text("S").font(.system(size: 29, weight: .semibold, design: .serif)).foregroundStyle(.white)
                    .frame(width: 46, height: 46).background(accent, in: RoundedRectangle(cornerRadius: 15)).padding(.bottom, 12)
                railItem(0, "探索", "house")
                railItem(1, "助手", "sparkles")
                railItem(2, "购物车", "bag")
                railItem(3, "订单", "receipt")
                railItem(4, "我的", "person")
                Spacer()
            }.padding(.top, 26).frame(width: 84).background(Color.white.opacity(0.52))
            NavigationStack {
                Group {
                    switch model.tab {
                    case 2: CartView(model: model)
                    case 3: CheckoutView(model: model)
                    case 4: RecoveryView(model: model)
                    default: CatalogView(model: model)
                    }
                }
            }.id(model.tab).frame(maxWidth: .infinity)
            Rectangle().fill(softBorder.opacity(0.7)).frame(width: 1)
            NavigationStack { ConversationView(model: model, chat: model.chat, embedded: true) }
                .frame(width: min(470, max(360, width * 0.38)))
        }
    }
    private func railItem(_ tab: Int, _ title: String, _ icon: String) -> some View {
        Button { model.tab = tab } label: {
            VStack(spacing: 7) {
                Image(systemName: icon).font(.system(size: 21, weight: model.tab == tab ? .semibold : .regular))
                    .frame(width: 52, height: 38).background(model.tab == tab ? accent.opacity(0.1) : .clear, in: Capsule())
                Text(title).font(.caption)
            }.foregroundStyle(model.tab == tab ? accent : mutedInk)
        }.buttonStyle(.plain).accessibilityLabel(title)
    }
}

struct LoginView: View {
    @ObservedObject var model: BuyerModel
    @State private var user = ""
    @State private var password = ""
    @State private var endpoint = ""
    @State private var commerceEndpoint = ""
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                Text("ShopMate").font(.system(size: 44, weight: .bold, design: .serif))
                Text("精选生活 · 官方商店").foregroundStyle(mutedInk)
                VStack(alignment: .leading, spacing: 14) {
                    Image(systemName: "sparkles").font(.title2).foregroundStyle(Color(red: 0.84, green: 0.71, blue: 0.48))
                    Text("给生活一点灵感，\n把喜欢带回日常。").font(.system(size: 28, weight: .semibold, design: .serif))
                    Text("发现合适的好物，让购物助手帮你做选择。").font(.subheadline).foregroundStyle(.white.opacity(0.75))
                }.foregroundStyle(.white).padding(26).frame(maxWidth: .infinity, alignment: .leading).background(ink, in: RoundedRectangle(cornerRadius: 26))
                VStack(alignment: .leading, spacing: 16) {
                    Text("欢迎回来").font(.title3.bold())
                    TextField("账号", text: $user).textInputAutocapitalization(.never).autocorrectionDisabled().accessibilityIdentifier("login-user")
                    SecureField("密码", text: $password).accessibilityIdentifier("login-password")
                    Button(model.loading ? "登录中…" : "登录，开始探索") {
                        model.login(endpoint: endpoint, user: user, password: password, commerceEndpoint: commerceEndpoint); password = ""
                    }.buttonStyle(.borderedProminent).controlSize(.large).disabled(model.loading || user.isEmpty || password.isEmpty).accessibilityIdentifier("login-submit")
                }
                DisclosureGroup("连接设置") {
                    TextField("服务地址", text: $endpoint).textInputAutocapitalization(.never).autocorrectionDisabled()
                    TextField("交易服务地址", text: $commerceEndpoint).textInputAutocapitalization(.never).autocorrectionDisabled()
                    Text("模拟器使用 localhost；本地真机开发可使用 Mac 的 .local 主机名，远程服务使用 HTTPS。").font(.footnote).foregroundStyle(.secondary)
                }.font(.footnote)
            }.textFieldStyle(.roundedBorder).padding(28).frame(maxWidth: 560)
        }.frame(maxWidth: .infinity).background(paper).onAppear { endpoint = model.api.root; commerceEndpoint = model.api.commerceRoot }
    }
}

struct Panel<Content: View>: View {
    @ViewBuilder let content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 14) { content }
            .padding(20).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.white.opacity(0.86), in: RoundedRectangle(cornerRadius: 22))
            .overlay(RoundedRectangle(cornerRadius: 22).strokeBorder(softBorder.opacity(0.4), lineWidth: 0.7))
    }
}

struct CatalogView: View {
    @ObservedObject var model: BuyerModel
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 24) {
                HStack {
                    Label("精选生活 · 官方商店", systemImage: "leaf").font(.caption).foregroundStyle(mutedInk)
                    Spacer()
                    NavigationLink { SeckillView(model: model) } label: { Label("限量发售", systemImage: "bolt.fill").font(.caption.weight(.medium)) }
                }
                VStack(alignment: .leading, spacing: 16) {
                    HStack { Image(systemName: "sparkles"); Text("把日常，过成喜欢的样子").tracking(1) }.font(.caption).foregroundStyle(Color(red: 0.83, green: 0.72, blue: 0.52))
                    Text("好物不必反复找，\n说说你的生活灵感。").font(.system(size: 28, weight: .semibold, design: .serif)).lineSpacing(5)
                    Text("从一杯咖啡开始，选好属于你的日常。\n助手陪你比较，也替你记住偏好。").font(.subheadline).lineSpacing(5).foregroundStyle(.white.opacity(0.72))
                    Button { model.tab = 1 } label: { HStack(spacing: 12) { Text("和助手聊聊"); Image(systemName: "arrow.up.right") }.font(.subheadline.weight(.semibold)).padding(.vertical, 4) }.buttonStyle(.borderedProminent).controlSize(.large)
                }.padding(25).frame(maxWidth: .infinity, alignment: .leading).foregroundStyle(.white).background(ink, in: RoundedRectangle(cornerRadius: 26))
                HStack(alignment: .firstTextBaseline) {
                    Text("探索生活好物").font(.system(size: 24, weight: .semibold, design: .serif))
                    Spacer(); Text("为日常认真挑选").font(.caption).foregroundStyle(mutedInk)
                }
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 152), spacing: 14)], spacing: 18) {
                    ForEach(model.products.map { IdentifiedObject(id: text($0, "product_id"), value: $0) }) { item in
                        let product = item.value
                        Button { model.openProduct(text(product, "product_id")) } label: {
                            VStack(alignment: .leading, spacing: 0) {
                                ProductImage(model: model, product: product).frame(height: 166).clipped()
                                VStack(alignment: .leading, spacing: 7) {
                                    Text(ProductPresentation.category(product)).font(.system(size: 10, weight: .medium)).foregroundStyle(mutedInk)
                                    Text(ProductPresentation.title(product)).font(.system(size: 14, weight: .medium)).lineLimit(2).frame(minHeight: 38, alignment: .topLeading).foregroundStyle(ink)
                                    Text(majorMoney(product["price"])).font(.system(size: 19, weight: .semibold, design: .rounded)).foregroundStyle(accent)
                                }.padding(12).frame(maxWidth: .infinity, alignment: .leading)
                            }.background(.white).clipShape(RoundedRectangle(cornerRadius: 20))
                                .overlay(RoundedRectangle(cornerRadius: 20).strokeBorder(softBorder.opacity(0.3), lineWidth: 0.7))
                        }.buttonStyle(.plain)
                    }
                }
                if model.searching { ProgressView().frame(maxWidth: .infinity) }
                else if model.hasMoreProducts { Button("继续发现好物") { model.search(append: true) }.buttonStyle(.bordered).frame(maxWidth: .infinity) }
                if !model.searching && model.products.isEmpty { ContentUnavailableView.search(text: model.searchQuery) }
            }.padding(20)
        }.searchable(text: $model.searchQuery, prompt: "搜索商品，寻找生活灵感")
            .onSubmit(of: .search) { model.search() }
            .background(paper).navigationTitle("ShopMate").toolbar { Button { model.reload() } label: { Image(systemName: "arrow.clockwise") }.accessibilityLabel("刷新") }
    }
}

struct ProductImage: View {
    @ObservedObject var model: BuyerModel
    let product: Object
    var body: some View { ProductArtwork(product: product, baseURL: model.api.root) }
}

struct ProductView: View {
    @ObservedObject var model: BuyerModel
    let product: Object
    @State private var approveAdd = false
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                ProductImage(model: model, product: product).frame(height: 300).clipShape(RoundedRectangle(cornerRadius: 24))
                VStack(alignment: .leading, spacing: 10) {
                    Text(ProductPresentation.category(product)).font(.caption).foregroundStyle(mutedInk)
                    Text(ProductPresentation.title(product)).font(.system(size: 28, weight: .semibold, design: .serif))
                    HStack {
                        Text(majorMoney(product["price"])).font(.system(size: 28, weight: .semibold, design: .rounded)).foregroundStyle(accent)
                        Spacer()
                        Label(product["in_stock"] as? Bool == false ? "暂时缺货" : "现货可选", systemImage: "shippingbox").font(.caption).foregroundStyle(mutedInk)
                    }
                }
                if !text(product, "long_description").isEmpty { Text(text(product, "long_description")).font(.subheadline).lineSpacing(6).foregroundStyle(mutedInk) }
                let specifications = object(product, "attributes")
                    .merging(object(product, "specs")) { _, value in value }
                    .merging(object(product, "options")) { _, value in value }
                    .merging(object(product, "option_values")) { _, value in value }
                if !specifications.isEmpty {
                    Panel {
                        Text("商品规格").font(.headline)
                        ForEach(specifications.keys.sorted(), id: \.self) { key in specification(key, value: specifications[key]) }
                    }
                }
                if !rows(product, "variants").isEmpty {
                    Text("选择具体规格").font(.headline)
                    ForEach(rows(product, "variants").map { IdentifiedObject(id: text($0, "product_id"), value: $0) }) { item in
                        Button { model.openProduct(text(item.value, "product_id")) } label: {
                            HStack(alignment: .center, spacing: 12) {
                                VStack(alignment: .leading, spacing: 7) {
                                    Text(ProductPresentation.title(item.value)).font(.subheadline.weight(.medium))
                                    Text(ProductSpecifications.summary(object(item.value, "option_values"))).font(.caption).foregroundStyle(mutedInk)
                                    Text(majorMoney(item.value["price"])).font(.subheadline.weight(.semibold)).foregroundStyle(accent)
                                }
                                Spacer(minLength: 0)
                                if item.value["in_stock"] as? Bool == false { Text("暂时缺货").font(.caption).foregroundStyle(mutedInk) }
                                Image(systemName: "chevron.right").font(.caption).foregroundStyle(mutedInk)
                            }.padding(18).background(.white, in: RoundedRectangle(cornerRadius: 16))
                        }.buttonStyle(.plain)
                    }
                } else {
                    Button { approveAdd = true } label: { Label("确认加入购物车", systemImage: "bag.badge.plus").frame(maxWidth: .infinity).padding(.vertical, 6) }
                        .buttonStyle(.borderedProminent).controlSize(.large).disabled(model.writing || product["in_stock"] as? Bool == false)
                }
                Button { model.askProduct(product) } label: { Label("就这件商品问助手", systemImage: "sparkles").frame(maxWidth: .infinity) }.buttonStyle(.bordered).controlSize(.large)
            }.padding(20)
        }.background(paper).navigationTitle("商品详情").navigationBarTitleDisplayMode(.inline).toolbar { Button("完成") { model.selected = nil } }
            .alert("确认加入购物车", isPresented: $approveAdd) {
                Button("确认提交") { model.add(product) }; Button("再看一下", role: .cancel) { }
            } message: { Text("加入 \(ProductPresentation.title(product)) × 1，结账时再次核对当前报价。") }
    }
    private func specification(_ key: String, value: Any?) -> some View {
        HStack(alignment: .top) {
            Text(ProductSpecifications.label(key)).foregroundStyle(mutedInk)
            Spacer(minLength: 18); Text(ProductSpecifications.value(value)).multilineTextAlignment(.trailing)
        }.font(.subheadline)
    }
}

// Only structured catalog vocabulary is localized; product IDs and submitted options stay unchanged.
enum ProductSpecifications {
    static func label(_ key: String) -> String {
        ["weight": "重量", "size": "尺寸", "color": "颜色", "shade": "色号", "capacity": "容量", "carafe": "壶体材质", "programmable": "定时功能", "pressure": "泵压", "steam_wand": "蒸汽奶泡", "water_tank": "水箱", "blade": "刀刃", "length": "长度", "handle": "手柄", "dishwasher_safe": "洗碗机适用", "material": "材质", "oven_safe": "烤箱耐温", "pieces": "件数", "coating": "涂层", "induction_ready": "电磁炉适用", "pfas_free": "不含 PFAS", "finish": "外观"][key] ?? key
    }
    static func value(_ raw: Any?) -> String {
        if let values = raw as? [String] { return values.map { value($0) }.joined(separator: " / ") }
        let source = String(describing: raw ?? "")
        return ["yes": "支持", "no": "不支持", "true": "支持", "false": "不支持", "full": "双人 Full", "king": "加大 King", "queen": "大双人 Queen", "standard": "标准", "twin": "单人 Twin", "blush": "雾粉", "ivory": "象牙白", "sage": "鼠尾草绿", "slate": "岩灰", "amber": "琥珀", "chestnut": "栗棕", "espresso": "浓咖", "honey": "蜜糖", "porcelain": "瓷白", "sand": "沙色", "12 lb": "12 磅", "15 lb": "15 磅", "20 lb": "20 磅", "glass": "玻璃", "stainless": "不锈钢色", "matte black": "哑光黑", "german steel": "德国钢", "laminated wood": "层压木", "enameled cast iron": "珐琅铸铁", "dusk blue": "暮蓝", "ceramic nonstick": "陶瓷不粘"][source.lowercased()] ?? source
    }
    static func summary(_ options: Object) -> String {
        options.keys.sorted().map { label($0) + " · " + value(options[$0]) }.joined(separator: "   ")
    }
}

struct CartView: View {
    @ObservedObject var model: BuyerModel
    var body: some View {
        ScrollView {
            VStack(spacing: 18) {
                if rows(model.quote, "items").isEmpty { ContentUnavailableView("装下一点喜欢", systemImage: "bag", description: Text("还没有商品，去探索属于你的生活好物。")) }
                ForEach(rows(model.quote, "items").map { IdentifiedObject(id: text($0, "productId"), value: $0) }) { row in
                    let item = row.value
                    let display = productForDisplay(item, model: model)
                    Panel {
                        HStack(alignment: .top, spacing: 14) {
                            ProductImage(model: model, product: display).frame(width: 86, height: 96).clipShape(RoundedRectangle(cornerRadius: 14))
                            VStack(alignment: .leading, spacing: 9) {
                                Text(ProductPresentation.title(display)).font(.subheadline.weight(.semibold)).lineLimit(3)
                                Text(money(item["lineTotalMinor"])).font(.headline).foregroundStyle(accent)
                                Text("单件价格以当前报价为准").font(.caption2).foregroundStyle(mutedInk)
                            }.frame(maxWidth: .infinity, alignment: .leading)
                        }
                        HStack {
                            let quantity = (item["quantity"] as? NSNumber)?.intValue ?? 1
                            HStack(spacing: 16) {
                                Button { model.setQuantity(item, quantity: max(0, quantity - 1)) } label: { Image(systemName: "minus").frame(width: 25, height: 28) }.accessibilityLabel("减少数量")
                                Text("\(quantity)").font(.subheadline.monospacedDigit()).frame(minWidth: 18)
                                Button { model.setQuantity(item, quantity: quantity + 1) } label: { Image(systemName: "plus").frame(width: 25, height: 28) }.accessibilityLabel("增加数量")
                            }.padding(.horizontal, 8).background(paper, in: Capsule())
                            Spacer(); Button("移除", role: .destructive) { model.setQuantity(item, quantity: 0) }.font(.caption)
                        }.disabled(model.writing)
                        if item["orderable"] as? Bool != true { Label("当前不可结账，请核对库存与规格", systemImage: "exclamationmark.circle").font(.caption).foregroundStyle(accent) }
                    }
                }
                if !rows(model.quote, "items").isEmpty {
                    Panel {
                        HStack { Text("订单合计").font(.headline); Spacer(); Text(money(model.quote["subtotalMinor"])).font(.system(size: 25, weight: .semibold, design: .rounded)).foregroundStyle(accent) }
                        Button { Task { await model.fetchDelivery() } } label: { Label("查看配送估算", systemImage: "shippingbox") }.font(.subheadline).disabled(model.writing)
                        DeliveryView(value: model.delivery)
                        Divider()
                        Text("创建订单后，再由你确认付款。").font(.caption).foregroundStyle(mutedInk)
                        Button { model.confirmCheckout() } label: { Text("核对并创建订单").frame(maxWidth: .infinity).padding(.vertical, 4) }
                            .buttonStyle(.borderedProminent).controlSize(.large).disabled(model.writing || model.quote["checkoutReady"] as? Bool != true).accessibilityIdentifier("checkout-create")
                    }
                }
            }.padding(20)
        }.background(paper).navigationTitle("购物车").toolbar { Button { model.reload() } label: { Image(systemName: "arrow.clockwise") }.accessibilityLabel("刷新") }
    }
}

struct IdentifiedObject: Identifiable { let id: String; let value: Object }

struct CheckoutView: View {
    @ObservedObject var model: BuyerModel
    @State private var showReceipts = false
    var body: some View {
        ScrollView {
            LazyVStack(alignment: .leading, spacing: 18) {
                let outstanding = model.checkouts.filter { rows($0, "orders").contains { text($0, "status") == "UNPAID" } }
                if model.orders.isEmpty && model.checkouts.isEmpty { ContentUnavailableView("好物正在等你", systemImage: "receipt", description: Text("下单后，你可以在这里查看进度和售后。")) }
                if !outstanding.isEmpty { Text("等待你的确认").font(.subheadline).foregroundStyle(mutedInk) }
                ForEach(outstanding.map { IdentifiedObject(id: text($0, "checkoutId"), value: $0) }) { item in
                    let checkout = item.value
                    Panel {
                        HStack { Label("待付款", systemImage: "clock").font(.headline).foregroundStyle(accent); Spacer(); Text(money(checkout["totalMinor"])).font(.title2.weight(.semibold)) }
                        ForEach(rows(checkout, "orders").map { IdentifiedObject(id: text($0, "orderId"), value: $0) }) { row in
                            HStack(spacing: 12) {
                                ProductImage(model: model, product: productForDisplay(object(row.value, "product"), model: model)).frame(width: 68, height: 72).clipShape(RoundedRectangle(cornerRadius: 12))
                                Text(ProductPresentation.title(productForDisplay(object(row.value, "product"), model: model))).font(.subheadline.weight(.medium)).lineLimit(2)
                            }
                        }
                        HStack {
                            Text("结账单 · " + text(checkout, "checkoutId").suffix(8)).font(.caption2).foregroundStyle(mutedInk)
                            Spacer()
                            Button("核对并模拟付款") { model.confirm("确认模拟支付 \(money(checkout["totalMinor"]))？不会扣取真实资金。") { model.pay(checkout) } }
                                .buttonStyle(.borderedProminent).disabled(model.writing).accessibilityIdentifier("checkout-pay")
                        }
                    }
                }
                let pendingActions = model.actions.filter { object($0, "receipt").isEmpty }
                ForEach(pendingActions.map { IdentifiedObject(id: text(object($0, "action"), "pendingActionId"), value: $0) }) { item in RefundActionView(model: model, row: item.value) }
                HStack { Text("我的订单").font(.system(size: 24, weight: .semibold, design: .serif)); Spacer(); Text("\(model.orders.count) 笔记录").font(.caption).foregroundStyle(mutedInk) }.padding(.top, 6)
                ForEach(model.orders.map { IdentifiedObject(id: text($0, "orderId"), value: $0) }) { item in OrderDetailPanel(model: model, order: item.value) }
                let receipts = model.actions.filter { !object($0, "receipt").isEmpty }
                if !receipts.isEmpty {
                    DisclosureGroup(isExpanded: $showReceipts) {
                        ForEach(receipts.map { IdentifiedObject(id: text(object($0, "action"), "pendingActionId"), value: $0) }) { item in RefundActionView(model: model, row: item.value) }
                    } label: { Label("售后回执 · \(receipts.count)", systemImage: "checkmark.seal").font(.subheadline) }.padding(.vertical, 12)
                }
            }.padding(20)
        }.background(paper).navigationTitle("订单").toolbar { Button { model.reload() } label: { Image(systemName: "arrow.clockwise") }.accessibilityLabel("刷新") }
    }
}

struct RecoveryView: View {
    @ObservedObject var model: BuyerModel
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 22) {
                HStack(spacing: 16) {
                    Image(systemName: "person.crop.circle.fill").font(.system(size: 64, weight: .ultraLight)).foregroundStyle(accent.opacity(0.85))
                    VStack(alignment: .leading, spacing: 7) {
                        Text(text(model.profile, "display_name").isEmpty ? "我的商店" : text(model.profile, "display_name")).font(.system(size: 25, weight: .semibold, design: .serif))
                        Label(text(model.profile, "default_location").isEmpty ? "探索日常的美好" : text(model.profile, "default_location"), systemImage: "location").font(.caption).foregroundStyle(mutedInk)
                    }
                }.padding(.vertical, 12)
                NavigationLink { MemoryView(model: model) } label: {
                    HStack(alignment: .top, spacing: 16) {
                        Image(systemName: "sparkles").font(.title).foregroundStyle(Color(red: 0.83, green: 0.72, blue: 0.52))
                        VStack(alignment: .leading, spacing: 10) { Text("越了解你，越会挑选。").font(.system(size: 23, weight: .semibold, design: .serif)); Text("管理助手记住的偏好，\n让每次选购都更合心意。").font(.subheadline).lineSpacing(4).foregroundStyle(.white.opacity(0.7)); Text("查看 \(model.memories.count) 条购物偏好  →").font(.caption.weight(.medium)).padding(.top, 5) }
                        Spacer(minLength: 0)
                    }.padding(24).foregroundStyle(.white).frame(maxWidth: .infinity, alignment: .leading).background(ink, in: RoundedRectangle(cornerRadius: 24))
                }.buttonStyle(.plain)
                Panel {
                    NavigationLink { CheckoutView(model: model) } label: { settingsRow("订单与售后", subtitle: "查看商品、付款与退款进度", icon: "shippingbox") }
                    Divider()
                    NavigationLink { MemoryView(model: model) } label: { settingsRow("购物偏好与政策", subtitle: "配送、退换与选购偏好", icon: "heart.text.clipboard") }
                }.buttonStyle(.plain)
                let unknown = model.commands.filter { text($0, "state") == "unknown" }
                if !unknown.isEmpty || !model.pending.isEmpty {
                    Panel {
                        Label("待核对操作", systemImage: "arrow.clockwise.circle").font(.headline)
                        Text("中断前的操作还在记录中，沿用原请求核对结果。").font(.caption).foregroundStyle(mutedInk)
                        ForEach(unknown.map { IdentifiedObject(id: text($0, "request_key"), value: $0) }) { item in
                            Button("核对原操作 · " + text(item.value, "request_key").suffix(8)) { model.confirm("查询原操作的结果，必要时沿用原标识重试。") { model.recoverCommand(item.value) } }.disabled(model.writing)
                        }
                        ForEach(model.pending, id: \.key) { pending in Button("核对并重试 · " + pending.key.suffix(8)) { model.confirm("沿用原请求继续核对，不会创建新的操作标识。") { model.retry(pending) } }.disabled(model.writing) }
                    }
                }
                Button { model.reload() } label: { Label("恢复已保存对话与业务状态", systemImage: "arrow.clockwise").font(.subheadline).frame(maxWidth: .infinity) }.buttonStyle(.bordered).controlSize(.large)
                Button("退出登录", role: .destructive) { model.logout() }.font(.subheadline).frame(maxWidth: .infinity).padding(.vertical, 12)
            }.padding(22)
        }.background(paper).navigationTitle("我的").task { await model.fetchProfile() }
    }
    private func settingsRow(_ title: String, subtitle: String, icon: String) -> some View {
        HStack(spacing: 13) {
            Image(systemName: icon).font(.title3).foregroundStyle(accent).frame(width: 30)
            VStack(alignment: .leading, spacing: 4) { Text(title).font(.subheadline.weight(.semibold)); Text(subtitle).font(.caption).foregroundStyle(mutedInk) }
            Spacer(); Image(systemName: "chevron.right").font(.caption).foregroundStyle(mutedInk)
        }.foregroundStyle(ink).padding(.vertical, 4)
    }
}
