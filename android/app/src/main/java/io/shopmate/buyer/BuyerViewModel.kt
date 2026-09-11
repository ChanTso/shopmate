package io.shopmate.buyer

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import java.net.URLEncoder
import java.util.UUID
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.*
import kotlinx.serialization.json.*

private val emptyObject = JsonObject(emptyMap())

data class BuyerState(
    val signedIn: Boolean = false,
    val screen: String = "首页",
    val loading: Boolean = false,
    val writing: Boolean = false,
    val error: String? = null,
    val notice: String? = null,
    val products: List<Product> = emptyList(),
    val nextOffset: Int? = null,
    val query: String = "",
    val selected: Product? = null,
    val quote: Quote? = null,
    val orders: List<JsonObject> = emptyList(),
    val checkouts: List<JsonObject> = emptyList(),
    val actions: List<JsonObject> = emptyList(),
    val memories: List<JsonObject> = emptyList(),
    val profile: JsonObject = emptyObject,
    val policies: List<JsonObject> = emptyList(),
    val delivery: JsonObject = emptyObject,
    val pending: List<PendingWrite> = emptyList(),
    val commands: List<JsonObject> = emptyList(),
    val offers: List<JsonObject> = emptyList(),
    val tickets: List<SeckillTicket> = emptyList(),
)

data class ChatState(
    val conversationKey: String = "",
    val messages: List<ChatMessage> = emptyList(),
    val conversations: List<Conversation> = emptyList(),
    val streaming: Boolean = false,
    val activity: String = "",
    val draft: String = "",
)

class BuyerViewModel(application: Application) : AndroidViewModel(application) {
    val api = BuyerApi()
    private val store = DeviceStore(application)
    private val mutable = MutableStateFlow(BuyerState())
    val state = mutable.asStateFlow()
    private val mutableChat = MutableStateFlow(ChatState())
    val chat = mutableChat.asStateFlow()
    private var seckillJob: Job? = null
    private var chatJob: Job? = null
    private var restoreJob: Job? = null
    private var catalogJob: Job? = null
    private var assistantPage = buildJsonObject { put("page_type", "home") }

    private fun update(change: (BuyerState) -> BuyerState) {
        mutable.update(change)
    }

    private fun updateChat(change: (ChatState) -> ChatState) {
        mutableChat.update(change)
    }

    init {
        api.commerceRoot = store.commerceEndpoint
        api.root = store.endpoint
        api.token = store.token()
        if (api.token != null) {
            update { it.copy(signedIn = true, pending = store.pending()) }
            refresh()
            restoreChat()
        }
    }

    private fun launchRead(block: suspend () -> Unit) = viewModelScope.launch {
        try {
            block()
        } catch (e: CancellationException) {
            throw e
        } catch (e: Exception) {
            report(e)
        }
    }

    private fun report(e: Exception) {
        if (e is ApiFailure && e.status == 401) {
            viewModelScope.coroutineContext.cancelChildren()
            api.token = null
            store.logout()
            mutable.value = BuyerState(error = e.message)
            mutableChat.value = ChatState()
            return
        }
        update {
            it.copy(
                error =
                    if (e is java.io.IOException && e !is ApiFailure)
                        "连接未完成，请检查网络并刷新核对；未确认的操作保留在操作记录。"
                    else e.message ?: "操作未完成"
            )
        }
    }

    fun dismiss() {
        update { it.copy(error = null, notice = null) }
    }

    fun login(endpoint: String, username: String, password: String, commerceEndpoint: String = api.commerceRoot) = launchRead {
        if (state.value.loading) return@launchRead
        update { it.copy(loading = true, error = null) }
        try {
            api.root = endpoint
            api.commerceRoot = commerceEndpoint
            val reply =
                api.json(
                    "/login",
                    buildJsonObject {
                        put("loginIdentifier", username)
                        put("password", password)
                    },
                )
            store.endpoint = api.root
            store.commerceEndpoint = api.commerceRoot
            store.login(reply.text("subject"), reply.text("accessToken"))
            api.token = reply.text("accessToken")
            mutable.value = BuyerState(signedIn = true, pending = store.pending())
            mutableChat.value = ChatState()
            refresh()
            restoreChat()
        } finally {
            update { it.copy(loading = false) }
        }
    }

    fun logout() {
        viewModelScope.coroutineContext.cancelChildren()
        api.token = null
        store.logout()
        mutable.value = BuyerState()
        mutableChat.value = ChatState()
    }

    fun navigate(screen: String) {
        update { it.copy(screen = screen, selected = null) }
        when (screen) {
            "购物车" -> refreshCart()
            "订单" -> refreshOrders()
            "我的" -> refreshProfile()
            "助手" -> loadConversations()
        }
    }

    fun search(query: String, append: Boolean = false) {
        catalogJob?.cancel()
        catalogJob = launchRead {
            update { it.copy(loading = true, query = query) }
            try {
                val offset = if (append) state.value.nextOffset ?: return@launchRead else 0
                val page =
                    wireJson.decodeFromJsonElement<ProductsPage>(
                        api.json(
                            "/products?query=${URLEncoder.encode(query, "UTF-8")}&offset=$offset&limit=24"
                        )
                    )
                update {
                    it.copy(
                        products = if (append) it.products + page.products else page.products,
                        nextOffset = page.next_offset,
                    )
                }
            } finally {
                update { it.copy(loading = false) }
            }
        }
    }

    fun openProduct(id: String) = launchRead {
        val product =
            wireJson.decodeFromJsonElement<Product>(
                api.json("/products/${URLEncoder.encode(id, "UTF-8")}").getValue("product")
            )
        update { it.copy(selected = product) }
    }

    fun closeProduct() {
        update { it.copy(selected = null) }
    }

    fun refresh() {
        search(state.value.query)
        refreshCart()
        refreshOrders()
    }

    private suspend fun readCart() {
        val quote = wireJson.decodeFromJsonElement<Quote>(api.json("/cart").getValue("quote"))
        update { it.copy(quote = quote) }
    }

    fun refreshCart() = launchRead { readCart() }

    private suspend fun readOrders() {
        val orders = api.json("/orders").rows("orders")
        val checkouts = api.json("/checkouts").rows("checkouts")
        val actions = api.json("/actions").rows("actions")
        val commands = api.json("/commands").rows("commands")
        update {
            it.copy(
                orders = orders,
                checkouts = checkouts,
                actions = actions,
                commands = commands,
                pending = store.pending(),
            )
        }
    }

    fun refreshOrders() = launchRead { readOrders() }

    fun refreshProfile() = launchRead {
        val profile = api.json("/profile").obj("profile")
        val memory = api.json("/memory").rows("facts")
        update { it.copy(profile = profile, memories = memory) }
    }

    fun policy(query: String) = launchRead {
        val data = api.json("/policies?query=${URLEncoder.encode(query, "UTF-8")}")
        update { it.copy(policies = data.rows("policies")) }
    }

    fun editMemory(key: String, value: String, delete: Boolean = false) = launchRead {
        api.json(
            "/memory",
            buildJsonObject {
                put("key", key)
                if (!delete) put("value", value)
            },
            if (delete) "DELETE" else "PATCH",
        )
        refreshProfile()
    }

    fun delivery() = launchRead {
        val result = api.json("/delivery/cart", emptyObject)
        update { it.copy(delivery = result) }
    }

    private fun write(path: String, body: JsonObject, retry: PendingWrite? = null) {
        if (state.value.writing) return
        update { it.copy(writing = true, error = null) }
        viewModelScope.launch {
            var request: PendingWrite? = null
            try {
                val key = retry?.key ?: UUID.randomUUID().toString()
                request =
                    retry
                        ?: WriteRecovery.prepare(key, path, body.toString())
                store.savePending(store.pending().filterNot { it.key == key } + request)
                update { it.copy(pending = store.pending()) }
                api.json(request.path, request.body)
                store.savePending(store.pending().filterNot { it.key == key })
                update { it.copy(pending = store.pending(), notice = "操作已受理，请以最新业务状态为准") }
                readCart()
                readOrders()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                if (
                    request != null &&
                        e is ApiFailure &&
                        !WriteRecovery.retain(e.status, e.category)
                ) {
                    store.savePending(store.pending().filterNot { it.key == request.key })
                    update { it.copy(pending = store.pending()) }
                }
                report(e)
            } finally {
                update { it.copy(writing = false) }
            }
        }
    }

    fun retry(value: PendingWrite) {
        val original = store.pending().firstOrNull { it.key == value.key } ?: value
        write(original.path, original.body, original)
    }

    fun loadSeckill() = launchRead {
        update { it.copy(tickets = store.tickets()) }
        val offers = api.seckill("/seckill/activities").rows("activities")
        update { it.copy(offers = offers) }
        pollSeckill()
    }

    private fun saveTicket(ticket: SeckillTicket) {
        val values = store.tickets().filterNot { it.key == ticket.key } + ticket
        store.saveTickets(values)
        update { it.copy(tickets = values) }
    }

    fun reserve(offer: JsonObject) {
        if (state.value.writing) return
        val previous = store.tickets().lastOrNull { it.activityId == offer.text("activityId") && it.state != "REJECTED" }
        if (previous != null) { retrySeckill(previous); return }
        retrySeckill(SeckillTicket(UUID.randomUUID().toString(), offer.text("activityId"),
            requireNotNull(offer.number("activityVersion"))))
    }

    fun retrySeckill(ticket: SeckillTicket) {
        if (state.value.writing) return
        update { it.copy(writing = true) }
        launchRead {
            try {
                val original = store.tickets().firstOrNull { it.key == ticket.key } ?: ticket
                saveTicket(original)
                val result = if (original.reservationId == null)
                    api.seckill("/seckill/activities/${original.activityId}/reservations",
                        buildJsonObject { put("quantity", 1); put("expectedActivityVersion", original.activityVersion) }, original.key)
                    else api.seckill("/reservations/${original.reservationId}")
                saveTicket(original.result(result))
                pollSeckill()
            } finally { update { it.copy(writing = false) } }
        }
    }

    private fun pollSeckill() {
        seckillJob?.cancel()
        seckillJob = launchRead {
            repeat(30) {
                val pending = store.tickets().filter { it.reservationId != null && !it.terminal }
                if (pending.isEmpty()) return@launchRead
                for (ticket in pending) saveTicket(ticket.result(api.seckill("/reservations/${ticket.reservationId}")))
                delay(2000)
            }
        }
    }

    fun add(product: Product) {
        write(
            "/cart/add",
            buildJsonObject {
                put("productId", product.product_id)
                put("quantity", 1)
            },
        )
    }

    fun setQuantity(item: QuoteItem, quantity: Int) {
        val quote = state.value.quote ?: return
        write(
            if (quantity == 0) "/cart/remove" else "/cart/set",
            buildJsonObject {
                put("productId", item.productId)
                put("expectedCartVersion", quote.version)
                if (quantity > 0) put("quantity", quantity)
            },
        )
    }

    fun checkout(quote: Quote) {
        try {
            write("/checkouts", quote.checkoutBody())
        } catch (e: IllegalArgumentException) {
            report(e)
        }
    }

    fun refund(order: JsonObject, amount: String) {
        try {
            write(
                "/actions/prepare",
                buildJsonObject {
                    put("orderId", order.text("orderId"))
                    put("amountMinor", refundMinor(amount))
                    put("currency", order.obj("product").text("currency"))
                },
            )
        } catch (e: IllegalArgumentException) {
            report(e)
        } catch (e: ArithmeticException) {
            report(e)
        }
    }

    fun transact(path: String) {
        if (state.value.writing) return
        update { it.copy(writing = true) }
        launchRead {
            try {
                api.json(path, emptyObject)
                readOrders()
                readCart()
                update { it.copy(notice = "已刷新执行结果") }
            } finally {
                update { it.copy(writing = false) }
            }
        }
    }

    fun draft(value: String) {
        updateChat { it.copy(draft = value) }
    }

    fun askProduct(product: Product) {
        assistantPage = buildJsonObject {
            put("page_type", "product")
            put("product_id", product.product_id)
        }
        update { it.copy(screen = "助手") }
        updateChat { it.copy(draft = "帮我分析 ${product.title}，是否适合我？") }
    }

    fun loadConversations() = launchRead {
        val rows = api.json("/conversations").rows("sessions")
        updateChat {
            it.copy(
                conversations =
                    rows.map { row ->
                        Conversation(
                            row.text("session_id"),
                            row.text("title", row.text("session_id").take(12)),
                        )
                    }
            )
        }
    }

    fun newChat() {
        if (chat.value.streaming) return
        restoreJob?.cancel()
        store.conversation = null
        updateChat { ChatState(conversationKey = UUID.randomUUID().toString()) }
    }

    fun selectChat(id: String) {
        if (chat.value.streaming) return
        store.conversation = id
        restoreChat()
    }

    fun restoreChat() {
        restoreJob?.cancel()
        restoreJob = launchRead {
            if (chat.value.streaming) return@launchRead
            val id = store.conversation ?: return@launchRead
            val reply = api.json("/conversations/$id")
            val messages = ChatReducer.restore(reply.toString())
            if (store.conversation == id && !chat.value.streaming)
                updateChat { it.copy(messages = messages, conversationKey = id) }
        }
    }

    fun stopChat() {
        chatJob?.cancel()
        update { it.copy(notice = "已停止连接。已受理操作不会撤销，可恢复对话并刷新业务记录") }
    }

    fun send() {
        val message = chat.value.draft.trim()
        if (chat.value.streaming || message.isEmpty()) return
        restoreJob?.cancel()
        update { it.copy(error = null) }
        updateChat { it.copy(streaming = true, activity = "正在连接助手…") }
        chatJob = viewModelScope.launch {
            try {
                val id =
                    store.conversation
                        ?: api.json("/conversations", emptyObject).text("session_id").also {
                            store.conversation = it
                        }
                updateChat {
                    it.copy(
                        conversationKey = id,
                        draft = "",
                        messages =
                            it.messages +
                                ChatMessage(true, listOf(ChatSegment(message))) +
                                ChatMessage(false, emptyList()),
                    )
                }
                val page = assistantPage
                api.chat(id, message, page).collect { event ->
                    when (event.type) {
                        "text_delta", "ui", "ui_partial" ->
                            updateLast { ChatReducer.apply(it, event) }
                        "tool_call" ->
                            updateChat { it.copy(activity = event.data.text("label", "正在查询业务数据…")) }
                        "progress" ->
                            updateChat { it.copy(activity = event.data.text("message", "正在分析…")) }
                        "cart_update" -> refreshCart()
                        "error" ->
                            update { it.copy(error = event.data.text("message", "助手未完成，请恢复后核对")) }
                    }
                }
                readCart()
                readOrders()
            } catch (e: CancellationException) {
                throw e
            } catch (e: Exception) {
                report(e)
            } finally {
                updateChat { it.copy(streaming = false, activity = "") }
            }
        }
    }

    private fun updateLast(change: (ChatMessage) -> ChatMessage) {
        updateChat { it.copy(messages = it.messages.dropLast(1) + change(it.messages.last())) }
    }
}
