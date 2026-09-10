import Foundation
import Combine
import BuyerCore

@MainActor
final class ConversationState: ObservableObject {
    @Published var messages: [ChatMessage] = []
    @Published var running = false
    @Published var activity = ""
    let timeline = ChatTimeline()
    func clear() { timeline.clear(); messages = []; running = false; activity = "" }
}

struct BuyerApproval: Identifiable {
    let id = UUID()
    let message: String
    let action: () -> Void
}

@MainActor
final class BuyerModel: ObservableObject {
    let api = BuyerAPI()
    let storage = BuyerStorage()
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
    @Published var tab = 0
    private var chatTask: Task<Void, Never>?
    private var chatGeneration = UUID()
    private var loadTask: Task<Void, Never>?
    private var writeTask: Task<Void, Never>?

    init() {
        do {
            try api.setRoot(storage.endpoint)
            api.token = try storage.token()
            signedIn = api.token != nil
            if signedIn { pending = try storage.pending(); reload() }
        } catch { self.error = error.localizedDescription }
    }
    private func report(_ failure: Error) {
        if failure is CancellationError || (failure as? URLError)?.code == .cancelled { return }
        if let failure = failure as? BuyerFailure, failure.status == 401 { logout() }
        error = failure.localizedDescription
    }
    func login(endpoint: String, user: String, password: String) {
        guard !loading else { return }
        loading = true; error = nil
        loadTask = Task {
            defer { loading = false }
            do {
                try api.setRoot(endpoint)
                let value = try await api.call("/login", body: ["loginIdentifier": user, "password": password])
                try Task.checkCancellation()
                storage.endpoint = api.root
                storage.owner = text(value, "subject")
                try storage.saveToken(text(value, "accessToken"))
                api.token = text(value, "accessToken")
                signedIn = true; pending = try storage.pending()
                try await refresh()
                try await restoreConversation()
            } catch { report(error) }
        }
    }
    func logout() {
        chatGeneration = UUID()
        chatTask?.cancel(); loadTask?.cancel(); writeTask?.cancel()
        do { try storage.logout() } catch { self.error = error.localizedDescription }
        api.token = nil; signedIn = false; loading = false; writing = false
        products = []; quote = [:]; checkouts = []; pending = []; selected = nil; tab = 0
        chat.clear()
    }
    func reload() {
        loadTask?.cancel()
        loadTask = Task {
            do { try await refresh(); if !chat.running { try await restoreConversation() } }
            catch { report(error) }
        }
    }
    private func refresh() async throws {
        let catalog = try await api.call("/products?limit=24")
        let cart = try await api.call("/cart")
        let orders = try await api.call("/checkouts")
        try Task.checkCancellation()
        products = rows(catalog, "products")
        quote = object(cart, "quote")
        checkouts = rows(orders, "checkouts")
    }
    func openProduct(_ id: String) {
        loadTask?.cancel()
        loadTask = Task {
            do {
                let escaped = id.addingPercentEncoding(withAllowedCharacters: .urlPathAllowed) ?? id
                let value = try await api.call("/products/" + escaped)
                try Task.checkCancellation(); selected = object(value, "product")
            } catch { report(error) }
        }
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
                self.tab = 3
            }
        } catch { report(error) }
    }
    func retry(_ pending: PendingWrite) {
        do { write(path: pending.path, body: try jsonObject(Data(WriteRecovery.shared.body(pending: pending).utf8)), original: pending) }
        catch { report(error) }
    }
    private func write(path: String, body: Object, original: PendingWrite? = nil) {
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
                selected = nil
                try await refresh()
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
                try Task.checkCancellation(); try await refresh()
            } catch { report(error) }
        }
    }
    func stop() { chatTask?.cancel(); chat.activity = "正在停止生成" }
    func newConversation() {
        guard !chat.running else { return }
        storage.conversation = nil; chat.clear()
    }
    private func restoreConversation() async throws {
        guard let id = storage.conversation else { return }
        let saved = try await api.call("/conversations/" + id)
        try Task.checkCancellation()
        guard !chat.running, storage.conversation == id else { return }
        try chat.timeline.restore(payload: jsonText(saved)); chat.messages = chat.timeline.messages
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
                try await api.stream("/conversations/" + id + "/chat", body: ["message": message, "page": ["page_type": "home"]]) { line in
                    try Task.checkCancellation()
                    guard self.chatGeneration == generation else { throw CancellationError() }
                    if let event = try decoder.line(raw: line) {
                        if event.type == "error" {
                            let value = try jsonObject(Data(event.payload.utf8))
                            throw BuyerFailure(status: 502, category: "", message: text(value, "message").isEmpty ? "助手暂未完成，请恢复对话后重试" : text(value, "message"))
                        }
                        try self.chat.timeline.accept(event: event)
                        if ["text_delta", "ui", "ui_partial"].contains(event.type) { self.chat.messages = self.chat.timeline.messages }
                        self.chat.activity = event.type == "turn_complete" ? "本轮已完成" : "正在整理建议"
                    }
                }
                try decoder.finish()
            } catch { report(error) }
        }
    }
}
