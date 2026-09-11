import SwiftUI
import BuyerCore

let paper = Color(red: 0.965, green: 0.945, blue: 0.902)
let ink = Color(red: 0.10, green: 0.095, blue: 0.065)
let accent = Color(red: 0.745, green: 0.22, blue: 0.157)

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
        VStack(spacing: 0) {
            if let error = model.error {
                HStack { Text(error).font(.footnote); Spacer(); Button("关闭") { model.error = nil } }
                    .padding().background(Color(red: 0.98, green: 0.86, blue: 0.82))
            }
            if model.signedIn {
                TabView(selection: $model.tab) {
                    NavigationStack { CatalogView(model: model) }.tabItem { Label("探索", systemImage: "house") }.tag(0)
                    NavigationStack { ConversationView(model: model, chat: model.chat) }.tabItem { Label("助手", systemImage: "sparkles") }.tag(1)
                    NavigationStack { CartView(model: model) }.tabItem { Label("购物车", systemImage: "bag") }.tag(2)
                    NavigationStack { CheckoutView(model: model) }.tabItem { Label("订单", systemImage: "receipt") }.tag(3)
                    NavigationStack { RecoveryView(model: model) }.tabItem { Label("我的", systemImage: "person") }.tag(4)
                }
            } else { LoginView(model: model) }
        }
        .background(paper)
        .alert(item: $model.confirmation) { value in
            Alert(title: Text("请核对后确认"), message: Text(value.message),
                  primaryButton: .default(Text("确认提交"), action: value.action), secondaryButton: .cancel(Text("再看一下")))
        }
        .sheet(isPresented: Binding(get: { model.selected != nil }, set: { if !$0 { model.selected = nil } })) {
            if let product = model.selected { NavigationStack { ProductView(model: model, product: product) } }
        }
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
                Text("精选生活 · 官方商店").foregroundStyle(.secondary)
                VStack(alignment: .leading, spacing: 14) {
                    Text("给生活一点灵感，\n把喜欢带回日常。").font(.system(size: 28, weight: .semibold, design: .serif))
                    Text("发现合适的好物，让购物助手帮你做选择。").font(.subheadline)
                }.foregroundStyle(.white).padding(24).frame(maxWidth: .infinity, alignment: .leading).background(ink, in: RoundedRectangle(cornerRadius: 24))
                TextField("账号", text: $user).textInputAutocapitalization(.never).autocorrectionDisabled().accessibilityIdentifier("login-user")
                SecureField("密码", text: $password).accessibilityIdentifier("login-password")
                Button(model.loading ? "登录中…" : "登录，开始探索") {
                    model.login(endpoint: endpoint, user: user, password: password, commerceEndpoint: commerceEndpoint); password = ""
                }.buttonStyle(.borderedProminent).disabled(model.loading || user.isEmpty || password.isEmpty).accessibilityIdentifier("login-submit")
                DisclosureGroup("连接设置") {
                    TextField("服务地址", text: $endpoint).textInputAutocapitalization(.never).autocorrectionDisabled()
                    TextField("交易服务地址", text: $commerceEndpoint).textInputAutocapitalization(.never).autocorrectionDisabled()
                    Text("模拟器使用 localhost；本地真机开发可使用 Mac 的 .local 主机名，远程服务使用 HTTPS。").font(.footnote).foregroundStyle(.secondary)
                }
            }.textFieldStyle(.roundedBorder).padding(28)
        }.background(paper).onAppear { endpoint = model.api.root; commerceEndpoint = model.api.commerceRoot }
    }
}

struct Panel<Content: View>: View {
    @ViewBuilder let content: Content
    var body: some View {
        VStack(alignment: .leading, spacing: 12) { content }
            .padding(18).frame(maxWidth: .infinity, alignment: .leading)
            .background(Color.white.opacity(0.8), in: RoundedRectangle(cornerRadius: 20))
    }
}

struct CatalogView: View {
    @ObservedObject var model: BuyerModel
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                VStack(alignment: .leading, spacing: 14) {
                    Text("购物规划 · PLANNER").font(.caption).tracking(2)
                    Text("说出预算和场景，\n助手陪你选好整套").font(.system(size: 27, weight: .semibold, design: .serif))
                    Button("开始规划 →") { model.tab = 1 }.buttonStyle(.borderedProminent)
                }.padding(22).frame(maxWidth: .infinity, alignment: .leading).foregroundStyle(.white).background(ink, in: RoundedRectangle(cornerRadius: 24))
                NavigationLink { SeckillView(model: model) } label: { Label("限量发售", systemImage: "bolt.fill").font(.headline) }
                Text("探索生活好物").font(.title2.bold())
                LazyVGrid(columns: [GridItem(.adaptive(minimum: 150))], spacing: 14) {
                    ForEach(model.products.indices, id: \.self) { index in
                        let product = model.products[index]
                        Button { model.openProduct(text(product, "product_id")) } label: {
                            VStack(alignment: .leading, spacing: 10) {
                                ProductImage(model: model, product: product).frame(height: 150).clipped()
                                Text(text(product, "title")).font(.subheadline).lineLimit(3).foregroundStyle(ink)
                                Text(majorMoney(product["price"])).font(.headline).foregroundStyle(accent)
                            }.padding(12).frame(maxWidth: .infinity, alignment: .leading).background(.white, in: RoundedRectangle(cornerRadius: 18))
                        }.buttonStyle(.plain)
                    }
                }
                if model.searching { ProgressView() }
                else if model.hasMoreProducts { Button("查看更多") { model.search(append: true) } }
                if !model.searching && model.products.isEmpty { ContentUnavailableView.search(text: model.searchQuery) }
            }.padding(18)
        }.searchable(text: $model.searchQuery, prompt: "搜索商品")
            .onSubmit(of: .search) { model.search() }
            .background(paper).navigationTitle("ShopMate").toolbar { Button("刷新") { model.reload() } }
    }
}

struct ProductImage: View {
    @ObservedObject var model: BuyerModel
    let product: Object
    var body: some View {
        let path = text(product, "image_url")
        AsyncImage(url: URL(string: path.hasPrefix("/") ? model.api.root + path : path)) { image in
            image.resizable().scaledToFit()
        } placeholder: { ZStack { paper; Image(systemName: "shippingbox").font(.largeTitle).foregroundStyle(.secondary) } }
    }
}

struct ProductView: View {
    @ObservedObject var model: BuyerModel
    let product: Object
    @State private var approveAdd = false
    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                ProductImage(model: model, product: product).frame(height: 240)
                Text(text(product, "title")).font(.system(size: 28, weight: .semibold, design: .serif))
                Text(majorMoney(product["price"])).font(.title2).foregroundStyle(accent)
                Text(text(product, "long_description"))
                let options = object(product, "options")
                ForEach(options.keys.sorted(), id: \.self) { key in
                    Text(key + "：" + String(describing: options[key] ?? ""))
                }
                let values = object(product, "option_values")
                ForEach(values.keys.sorted(), id: \.self) { key in
                    Text(key + "：" + String(describing: values[key] ?? ""))
                }
                if !rows(product, "variants").isEmpty {
                    Text("选择具体规格").font(.headline)
                    ForEach(rows(product, "variants").indices, id: \.self) { i in
                        let variant = rows(product, "variants")[i]
                        Button {
                            model.openProduct(text(variant, "product_id"))
                        } label: {
                            HStack {
                                Text(text(variant, "title")); Spacer()
                                Text(variant["in_stock"] as? Bool == false ? "暂时缺货" : "查看")
                            }.padding().background(.white, in: RoundedRectangle(cornerRadius: 12))
                        }.buttonStyle(.plain)
                    }
                } else {
                    Button("确认加入购物车") {
                        approveAdd = true
                    }.buttonStyle(.borderedProminent).disabled(model.writing || product["in_stock"] as? Bool == false)
                }
                Button { model.askProduct(product) } label: { Label("就这件商品问助手", systemImage: "sparkles") }.buttonStyle(.bordered)
            }.padding(20)
        }.background(paper).navigationTitle("商品详情").toolbar { Button("关闭") { model.selected = nil } }
            .alert("确认加入购物车", isPresented: $approveAdd) {
                Button("确认提交") { model.add(product) }
                Button("再看一下", role: .cancel) { }
            } message: { Text("加入 \(text(product, "title")) × 1，结账时再次核对当前报价。") }
    }
}

struct CartView: View {
    @ObservedObject var model: BuyerModel
    var body: some View {
        ScrollView {
            VStack(spacing: 16) {
                if rows(model.quote, "items").isEmpty { Text("购物车为空，去挑选喜欢的好物吧。") }
                ForEach(rows(model.quote, "items").indices, id: \.self) { i in
                    let item = rows(model.quote, "items")[i]
                    Panel {
                        Text(text(item, "name")).font(.headline)
                        Text("数量 \((item["quantity"] as? NSNumber)?.intValue ?? 0) · \(money(item["lineTotalMinor"]))")
                        HStack {
                            let quantity = (item["quantity"] as? NSNumber)?.intValue ?? 1
                            Button("减一") { model.setQuantity(item, quantity: max(0, quantity - 1)) }
                            Button("加一") { model.setQuantity(item, quantity: quantity + 1) }
                            Spacer()
                            Button("移除", role: .destructive) { model.setQuantity(item, quantity: 0) }
                        }.buttonStyle(.bordered).disabled(model.writing)
                        if item["orderable"] as? Bool != true { Text("当前不可结账，请核对库存与规格").foregroundStyle(accent) }
                    }
                }
                Panel {
                    Button("查看配送估算") { Task { await model.fetchDelivery() } }.disabled(model.writing)
                    DeliveryView(value: model.delivery)
                    Text("合计 \(money(model.quote["subtotalMinor"]))").font(.title2.bold())
                    Text("按当前商品、价格与购物车版本创建订单。付款还需要单独确认。").font(.footnote).foregroundStyle(.secondary)
                    Button("核对并创建订单") {
                        model.confirmCheckout()
                    }.buttonStyle(.borderedProminent).disabled(model.writing || model.quote["checkoutReady"] as? Bool != true).accessibilityIdentifier("checkout-create")
                }
            }.padding(18)
        }.background(paper).navigationTitle("购物车").toolbar { Button("刷新") { model.reload() } }
    }
}

struct CheckoutView: View {
    @ObservedObject var model: BuyerModel
    var body: some View {
        ScrollView {
            LazyVStack(spacing: 16) {
                ForEach(model.actions.indices, id: \.self) { RefundActionView(model: model, row: model.actions[$0]) }
                ForEach(model.orders.indices, id: \.self) { OrderDetailPanel(model: model, order: model.orders[$0]) }
                if model.orders.isEmpty && model.checkouts.isEmpty { Text("暂无订单记录") }
                Text("结账记录").font(.headline)
                ForEach(model.checkouts.indices, id: \.self) { i in
                    let checkout = model.checkouts[i]
                    Panel {
                        Text(text(checkout, "paymentStatus") == "PAID" ? "已付款" : "待核对付款").font(.headline)
                        Text(money(checkout["totalMinor"])).font(.title2).foregroundStyle(accent)
                        ForEach(rows(checkout, "orders").indices, id: \.self) { j in
                            let order = rows(checkout, "orders")[j]
                            Text(text(object(order, "product"), "name"))
                            Text("订单尾号 \(text(order, "orderId").suffix(8))").font(.caption).foregroundStyle(.secondary)
                        }
                        Text("结账单尾号 \(text(checkout, "checkoutId").suffix(8))").font(.caption)
                        if rows(checkout, "orders").contains(where: { text($0, "status") == "UNPAID" }) {
                            Button("核对并模拟付款") {
                                model.confirm("确认模拟支付 \(money(checkout["totalMinor"]))？不会扣取真实资金。") { model.pay(checkout) }
                            }.buttonStyle(.borderedProminent).disabled(model.writing).accessibilityIdentifier("checkout-pay")
                        }
                    }
                }
            }.padding(18)
        }.background(paper).navigationTitle("订单与回执").toolbar { Button("刷新") { model.reload() } }
    }
}

struct RecoveryView: View {
    @ObservedObject var model: BuyerModel
    var body: some View {
        List {
            Section {
                Text(text(model.profile, "display_name").isEmpty ? "我的商店" : text(model.profile, "display_name")).font(.title2)
                Text(text(model.profile, "default_location"))
                NavigationLink("助手记忆与购物政策") { MemoryView(model: model) }
            }
            Section("服务端待核对操作") {
                ForEach(model.commands.indices, id: \.self) { i in
                    let command = model.commands[i]
                    if text(command, "state") == "unknown" {
                        Button("恢复原操作 · " + text(command, "request_key").suffix(8)) {
                            model.confirm("查询原操作的结果，必要时沿用原标识重试。") { model.recoverCommand(command) }
                        }.disabled(model.writing)
                    }
                }
            }
            Section("待核对操作") {
                if model.pending.isEmpty { Text("没有待核对操作") }
                ForEach(model.pending, id: \.key) { pending in
                    VStack(alignment: .leading, spacing: 8) {
                        Text("原意图 \(pending.key.suffix(8))")
                        Button("核对并重试原操作") { model.confirm("沿用原请求继续核对，不会创建新的操作标识。") { model.retry(pending) } }.disabled(model.writing)
                    }
                }
            }
            Section {
                Button("恢复已保存对话与业务状态") { model.reload() }
                Text("停止生成不撤销已受理操作；未知结果沿用原请求恢复。交易结果以商店记录为准。").font(.footnote)
                Button("退出登录", role: .destructive) { model.logout() }
            }
        }.navigationTitle("我的").task { await model.fetchProfile() }
    }
}
