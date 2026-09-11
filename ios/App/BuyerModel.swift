import Foundation
import Combine
import BuyerCore

@MainActor
final class ConversationState: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var running = false
    @Published var activity = ""
    @Published var draft = ""
    @Published var revision = 0
    @Published var conversationKey = UUID().uuidString
    let timeline = ChatTimeline()
    func clear() { timeline.clear(); messages = []; running = false; activity = "" }
}

struct BuyerApproval: Identifiable {
    let id = UUID()
    let message: String
    let action: () -> Void
}

enum CatalogRoute: Hashable { case seckill }

@MainActor
final class BuyerModel: ObservableObject {
    let api: BuyerAPI
    let storage: BuyerStorage
    let chat = ConversationState()
    @Published var signedIn = false
    @Published var loading = false
    @Published var writing = false
    @Published var error: String?
    @Published var products: [Object] = []
    @Published var quote: Object = [:]
    @Published var checkouts: [Object] = []
    @Published var pending: [PendingWrite] = []
    @Published var confirmation: BuyerApproval?
    func confirm(_ message: String, action: @escaping () -> Void) { confirmation = BuyerApproval(message: message, action: action) }
    @Published var selected: Object?
    @Published private(set) var productReturn: Object?
    private var productReturnTab = 0
    @Published var tab = 0
    @Published var orders: [Object] = []
    @Published var actions: [Object] = []
    @Published var commands: [Object] = []
    @Published var conversations: [Object] = []
    @Published var profile: Object = [:]
    @Published var memories: [Object] = []
    @Published var policies: [Object] = []
    @Published var delivery: Object = [:]
    @Published var offers: [Object] = []
    @Published var tickets: [SeckillTicket] = []
    @Published private(set) var reservationNotice: String?
    @Published var searchQuery = ""
    @Published private(set) var submittedSearchQuery = ""
    @Published var catalogPosition: String?
    @Published var catalogPath: [CatalogRoute] = []
    @Published var hasMoreProducts = false
    @Published var searching = false
    var assistantPage: Object = ["page_type": "home"]
    private var nextProductOffset: Int?
    private var searchTask: Task<Void, Never>?
    private var pollTask: Task<Void, Never>?
    private var applicationActive = false
    private var seckillVisible = false
    private var productTask: Task<Void, Never>?
    private var chatTask: Task<Void, Never>?
    private var chatGeneration = UUID()
    private var loadTask: Task<Void, Never>?
    private var writeTask: Task<Void, Never>?

    convenience init() { self.init(api: BuyerAPI(), storage: BuyerStorage()) }

    init(api: BuyerAPI, storage: BuyerStorage) {
        self.api = api
        self.storage = storage
        do {
            try api.setRoot(storage.endpoint)
            try api.setCommerceRoot(storage.commerceEndpoint)
            api.token = try storage.token()
            signedIn = api.token != nil
            if signedIn { pending = try storage.pending(); reload() }
        } catch { self.error = error.localizedDescription }
    }
    func report(_ failure: Error) {
        if failure is CancellationError || (failure as? URLError)?.code == .cancelled { return }
        if let failure = failure as? BuyerFailure, failure.status == 401 { logout() }
        error = failure.localizedDescription
    }
    func login(endpoint: String, user: String, password: String, commerceEndpoint: String = "http://localhost:9082") {
        guard !loading else { return }
        loading = true; error = nil
        loadTask = Task {
            defer { loading = false }
            do {
                try api.setRoot(endpoint)
                try api.setCommerceRoot(commerceEndpoint)
                let value = try await api.call("/login", body: ["loginIdentifier": user, "password": password])
                try Task.checkCancellation()
                storage.endpoint = api.root
                storage.commerceEndpoint = api.commerceRoot
                storage.owner = text(value, "subject")
                try storage.saveToken(text(value, "accessToken"))
                api.token = text(value, "accessToken")
                signedIn = true; pending = try storage.pending()
                search()
                try await refresh()
                try await restoreConversation()
            } catch { report(error) }
        }
    }
    func logout() {
        chatGeneration = UUID()
        chatTask?.cancel(); loadTask?.cancel(); writeTask?.cancel(); searchTask?.cancel(); pollTask?.cancel(); productTask?.cancel()
        pollTask = nil; seckillVisible = false; reservationNotice = nil
        do { try storage.logout() } catch { self.error = error.localizedDescription }
        api.token = nil; signedIn = false; loading = false; writing = false
        products = []; quote = [:]; checkouts = []; pending = []; selected = nil; productReturn = nil; tab = 0
        orders = []; actions = []; commands = []; conversations = []; profile = [:]; memories = []
        policies = []; delivery = [:]; offers = []; tickets = []; searchQuery = ""; searching = false
        hasMoreProducts = false; nextProductOffset = nil; submittedSearchQuery = ""
        catalogPosition = nil; catalogPath = []
        confirmation = nil; assistantPage = ["page_type": "home"]
        chat.clear(); chat.draft = ""; chat.conversationKey = UUID().uuidString
    }
    @discardableResult
    func reload() -> Task<Void, Never> {
        if products.isEmpty && !searching { search() }
        loadTask?.cancel()
        let task = Task {
            do { try await refresh(); if !chat.running { try await restoreConversation() } }
            catch { report(error) }
        }
        loadTask = task
        return task
    }
    private func refresh() async throws {
        let cart = try await api.call("/cart")
        let orders = try await api.call("/checkouts")
        try Task.checkCancellation()
        quote = object(cart, "quote")
        checkouts = rows(orders, "checkouts")
        self.orders = rows(try await api.call("/orders"), "orders")
        actions = rows(try await api.call("/actions"), "actions")
        commands = rows(try await api.call("/commands"), "commands")
        let confirmed = Set(commands.filter { text($0, "state") == "confirmed" }.map { text($0, "request_key") })
        let saved = try storage.pending()
        let remaining = saved.filter { !confirmed.contains($0.key) }
        if remaining.count != saved.count { try storage.savePending(remaining) }
        pending = remaining
    }
    func openProduct(_ id: String) {
        productTask?.cancel()
        productTask = Task {
            do {
                let escaped = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id
                let value = try await api.call("/products/" + escaped)
                try Task.checkCancellation(); selected = object(value, "product"); productReturn = nil
            } catch { report(error) }
        }
    }
    func closeProduct() {
        productTask?.cancel()
        selected = nil
    }
    func add(_ product: Object) {
        write(path: "/cart/add", body: ["productId": text(product, "product_id"), "quantity": 1])
    }
    func confirmCheckout() {
        do {
            let body = try WriteRecovery.shared.checkoutBody(quote: jsonText(quote))
            let approved = try jsonObject(Data(body.utf8))
            confirm("确认按当前报价创建订单，合计 \(money(quote["subtotalMinor"]))？") {
                self.write(path: "/checkouts", body: approved)
            }
        } catch { report(error) }
    }
    func retry(_ pending: PendingWrite) {
        do { write(path: pending.path, body: try jsonObject(Data(WriteRecovery.shared.body(pending: pending).utf8)), original: pending) }
        catch { report(error) }
    }
    func write(path: String, body: Object, original: PendingWrite? = nil) {
        guard !writing else { return }
        writing = true; error = nil
        writeTask = Task {
            var command: PendingWrite?
            defer { writing = false }
            do {
                let value = try original ?? WriteRecovery.shared.prepare(key: UUID().uuidString, path: path, body: jsonText(body))
                command = value
                let saved = try storage.pending().filter { $0.key != value.key } + [value]
                try storage.savePending(saved); pending = saved
                _ = try await api.call(value.path, body: jsonObject(Data(WriteRecovery.shared.body(pending: value).utf8)))
                try Task.checkCancellation()
                let remaining = try storage.pending().filter { $0.key != value.key }
                try storage.savePending(remaining); pending = remaining
                closeProduct()
                if value.path == "/checkouts" { tab = 3 }
                await refreshAfterAcceptedWrite()
            } catch {
                if let failure = error as? BuyerFailure, let command,
                   !WriteRecovery.shared.retain(status: Int32(failure.status), category: failure.category) {
                    do {
                        let remaining = try storage.pending().filter { $0.key != command.key }
                        try storage.savePending(remaining); pending = remaining
                    } catch { self.error = error.localizedDescription }
                }
                report(error)
            }
        }
    }
    func pay(_ checkout: Object) {
        guard !writing else { return }
        writing = true
        writeTask = Task {
            defer { writing = false }
            do {
                _ = try await api.call("/checkouts/" + text(checkout, "checkoutId") + "/pay", body: [:])
                try Task.checkCancellation(); await refreshAfterAcceptedWrite()
            } catch { report(error) }
        }
    }
    private func refreshAfterAcceptedWrite() async {
        do { try await refresh() }
        catch {
            if error is CancellationError || (error as? URLError)?.code == .cancelled { return }
            report(error)
            self.error = "操作已受理，业务状态刷新未完成，请刷新核对。" + error.localizedDescription
        }
    }
    func stop() { chatTask?.cancel(); chat.activity = "正在停止生成" }
    func newConversation() {
        guard !chat.running else { return }
        storage.conversation = nil; chat.clear(); chat.conversationKey = UUID().uuidString
        assistantPage = ["page_type": "home"]
    }
    private func restoreConversation() async throws {
        guard let id = storage.conversation else { return }
        let generation = chatGeneration
        let saved = try await api.call("/conversations/" + id)
        try Task.checkCancellation()
        // A completed newer turn must not be replaced by an older in-flight history response.
        guard !chat.running, storage.conversation == id, chatGeneration == generation else { return }
        try chat.timeline.restore(payload: jsonText(saved)); chat.messages = chat.timeline.messages; chat.revision += 1
    }
    func send(_ raw: String) {
        let message = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !message.isEmpty, !chat.running else { return }
        chat.running = true; chat.activity = "正在查询"; error = nil
        let generation = UUID()
        chatGeneration = generation
        chatTask = Task {
            defer { if chatGeneration == generation { chat.running = false } }
            do {
                var id = storage.conversation
                if id == nil {
                    let value = try await api.call("/conversations", body: [:])
                    try Task.checkCancellation()
                    id = text(value, "session_id"); storage.conversation = id
                }
                guard let id, !id.isEmpty else { throw URLError(.badServerResponse) }
                chat.timeline.begin(text: message); chat.messages = chat.timeline.messages
                let decoder = StreamDecoder()
                try await api.stream("/conversations/" + id + "/chat", body: ["message": message, "page": self.assistantPage]) { line in
                    try Task.checkCancellation()
                    guard self.chatGeneration == generation else { throw CancellationError() }
                    if let event = try decoder.line(raw: line) {
                        if event.type == "error" {
                            let value = try jsonObject(Data(event.payload.utf8))
                            throw BuyerFailure(status: 502, category: "", message: text(value, "message").isEmpty ? "助手暂未完成，请恢复对话后重试" : text(value, "message"))
                        }
                        try self.chat.timeline.accept(event: event)
                        if ["text_delta", "ui", "ui_partial"].contains(event.type) { self.chat.messages = self.chat.timeline.messages; self.chat.revision += 1 }
                        self.chat.activity = event.type == "turn_complete" ? "本轮已完成" : "正在整理建议"
                    }
                }
                try decoder.finish()
            } catch { report(error) }
        }
    }
    func search(append: Bool = false) {
        let offset: Int
        if append {
            guard !searching, let nextProductOffset else { return }
            offset = nextProductOffset
        } else {
            searchTask?.cancel()
            submittedSearchQuery = searchQuery
            products = []; nextProductOffset = nil; hasMoreProducts = false; catalogPosition = nil
            offset = 0
        }
        let query = submittedSearchQuery
        searching = true
        searchTask = Task {
            do {
                var parts = URLComponents()
                parts.queryItems = [URLQueryItem(name: "query", value: query), URLQueryItem(name: "offset", value: String(offset)), URLQueryItem(name: "limit", value: "24")]
                let page = try await api.call("/products?" + (parts.percentEncodedQuery ?? ""))
                let result = rows(page, "products")
                try Task.checkCancellation()
                products = append ? products + result : result
                nextProductOffset = (page["next_offset"] as? NSNumber)?.intValue
                hasMoreProducts = nextProductOffset != nil; searching = false
            } catch { if !Task.isCancelled { searching = false; report(error) } }
        }
    }
    func setQuantity(_ item: Object, quantity: Int) {
        var body: Object = ["productId": text(item, "productId"), "expectedCartVersion": quote["version"] ?? 0]
        if quantity > 0 { body["quantity"] = quantity }
        write(path: quantity == 0 ? "/cart/remove" : "/cart/set", body: body)
    }
    func fetchDelivery() async {
        do { delivery = try await api.call("/delivery/cart", body: [:]) } catch { report(error) }
    }
    func fetchProfile() async {
        do {
            let value = try await api.call("/profile")
            let facts = try await api.call("/memory")
            try Task.checkCancellation(); profile = object(value, "profile"); memories = rows(facts, "facts")
        } catch { report(error) }
    }
    func editMemory(key: String, value: String, delete: Bool = false) async {
        do {
            let body: Object = delete ? ["key": key] : ["key": key, "value": value]
            _ = try await api.call("/memory", body: body, method: delete ? "DELETE" : "PATCH")
            try Task.checkCancellation(); await fetchProfile()
        } catch { report(error) }
    }
    func fetchPolicies(_ query: String) async {
        do {
            var parts = URLComponents(); parts.queryItems = [URLQueryItem(name: "query", value: query)]
            let value = try await api.call("/policies?" + (parts.percentEncodedQuery ?? ""))
            try Task.checkCancellation(); policies = rows(value, "policies")
        } catch { report(error) }
    }
    func fetchConversations() async {
        do {
            let value = try await api.call("/conversations")
            try Task.checkCancellation(); conversations = rows(value, "sessions")
        } catch { report(error) }
    }
    func selectConversation(_ id: String) {
        guard !chat.running else { return }
        storage.conversation = id; chat.clear(); chat.conversationKey = id
        loadTask?.cancel()
        loadTask = Task { do { try await restoreConversation() } catch { report(error) } }
    }
    func askProduct(_ product: Object) {
        assistantPage = ["page_type": "product", "product_id": text(product, "product_id")]
        chat.draft = "帮我分析「" + text(product, "title") + "」，是否适合我？"
        productReturnTab = tab
        closeProduct(); productReturn = product; tab = 1
    }
    func returnToProduct() {
        guard let product = productReturn else { return }
        productTask?.cancel()
        selected = product; productReturn = nil; tab = productReturnTab
    }
    func transact(_ path: String) {
        guard !writing else { return }
        writing = true
        writeTask = Task {
            defer { writing = false }
            do { _ = try await api.call(path, body: [:]); try Task.checkCancellation(); await refreshAfterAcceptedWrite() }
            catch { report(error) }
        }
    }
    func refund(_ order: Object, amount: String) {
        do {
            let minor = try refundMinor(amount)
            write(path: "/actions/prepare", body: ["orderId": text(order, "orderId"), "amountMinor": minor, "currency": text(object(order, "product"), "currency")])
        } catch { report(error) }
    }
    func recoverCommand(_ command: Object) {
        let kind = text(command, "kind")
        let path = kind == "checkout" ? "/checkouts/retry" : kind == "refund" ? "/actions/retry" : "/commands/retry"
        let key = text(command, "request_key")
        do {
            let original = try WriteRecovery.shared.prepare(key: key, path: path, body: jsonText(["request_key": key]))
            retry(original)
        } catch { report(error) }
    }
    func loadSeckill(refreshReservations: Bool = true) async {
        if refreshReservations { pollSeckill() }
        do {
            tickets = try storage.tickets()
            let result = try await api.seckill("/seckill/activities")
            try Task.checkCancellation(); offers = rows(result, "activities")
        } catch { report(error) }
    }
    private func saveTicket(_ ticket: SeckillTicket) throws {
        let saved = try storage.tickets().filter { $0.key != ticket.key } + [ticket]
        try storage.saveTickets(saved); tickets = saved
    }
    func reserve(_ offer: Object) {
        let id = text(offer, "activityId")
        if let previous = tickets.last(where: { $0.activityId == id && $0.state != "REJECTED" }) { retrySeckill(previous); return }
        guard let version = offer["activityVersion"] as? NSNumber else { return }
        retrySeckill(SeckillTicket(key: UUID().uuidString, activityId: id, activityVersion: version.int64Value))
    }
    func retrySeckill(_ ticket: SeckillTicket) {
        guard !writing else { return }
        writing = true
        writeTask = Task {
            defer { writing = false }
            do {
                let original = try storage.tickets().first(where: { $0.key == ticket.key }) ?? ticket
                try saveTicket(original)
                let reply: Object
                if let id = original.reservationId { reply = try await api.seckill("/reservations/" + id) }
                else {
                    reply = try await api.seckill("/seckill/activities/" + original.activityId + "/reservations", body: ["quantity": 1, "expectedActivityVersion": original.activityVersion], key: original.key)
                }
                try Task.checkCancellation(); try saveTicket(original.result(reply)); pollSeckill()
            } catch { report(error) }
        }
    }
    func setApplicationActive(_ active: Bool) {
        guard applicationActive != active else { return }
        applicationActive = active
        pollSeckill()
    }
    func setSeckillVisible(_ visible: Bool) {
        guard seckillVisible != visible else { return }
        seckillVisible = visible
        pollSeckill()
    }
    private func pollSeckill() {
        pollTask?.cancel()
        pollTask = nil
        guard applicationActive && seckillVisible else { return }
        reservationNotice = nil
        pollTask = Task {
            do {
                for attempt in 0..<30 {
                    let waiting = try storage.tickets().filter { $0.reservationId != nil && !$0.terminal }
                    if waiting.isEmpty { return }
                    for ticket in waiting {
                        let reply = try await api.seckill("/reservations/" + (ticket.reservationId ?? ""))
                        try Task.checkCancellation(); try saveTicket(ticket.result(reply))
                    }
                    if !tickets.contains(where: { $0.reservationId != nil && !$0.terminal }) { return }
                    if attempt == 29 {
                        reservationNotice = "预约仍待确认，可点击“查询原预约”继续核对。"
                        return
                    }
                    try await Task.sleep(for: .seconds(2))
                }
            } catch { report(error) }
        }
    }

}
