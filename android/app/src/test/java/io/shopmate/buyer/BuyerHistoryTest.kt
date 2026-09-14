package io.shopmate.buyer

import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.*
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.test.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class BuyerHistoryTest {
    private fun page(session: String, ids: IntRange, next: Int? = null, pending: Boolean = false) = buildJsonObject {
        put("session_id", session)
        put("status", if (pending) "running" else "completed")
        put("next_before", next?.let(::JsonPrimitive) ?: JsonNull)
        putJsonArray("items") {
            ids.forEach { id -> add(buildJsonObject {
                put("message_id", id)
                if (id % 2 == 1) { put("kind", "user"); put("text", "问题 $id") }
                else {
                    put("kind", "assistant"); put("pending", pending && id == ids.last)
                    putJsonArray("segments") { add(buildJsonObject { put("type", "text"); put("text", "回答 $id") }) }
                }
            }) }
        }
    }

    private fun start(session: String, user: Int, assistant: Int) = StreamEvent("turn_started", buildJsonObject {
        put("session_id", session); put("user_message_id", user); put("assistant_message_id", assistant)
    })
    private fun delta(text: String) = StreamEvent("text_delta", buildJsonObject { put("text", text) })
    private fun card(final: Boolean) = StreamEvent(if (final) "ui" else "ui_partial", buildJsonObject {
        put("component", "products"); put("stream_id", "recommendation")
        putJsonObject("payload") { put("title", if (final) "已完成" else "正在整理") }
    })
    private val complete = StreamEvent("turn_complete", JsonObject(emptyMap()))

    private fun TestScope.fixture(): Triple<BuyerViewModel, HistoryApi, HistoryStorage> {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        val api = HistoryApi()
        val store = HistoryStorage()
        return Triple(BuyerViewModel(api, store), api, store)
    }

    @Test fun `latest page must succeed before a send and failed latest retries as latest`() = runTest {
        val (vm, api) = fixture()
        val initial = CompletableDeferred<JsonObject>()
        api.read = { path -> if (path.contains("/messages")) initial.await() else api.defaultReply(path) }
        api.stream = { id -> flowOf(start(id, 41, 42), delta("新回答"), complete) }
        try {
            vm.selectChat("one")
            vm.draft("继续")
            vm.send()
            assertTrue(vm.chat.value.loadingHistory)
            assertEquals(0, api.sends)
            initial.completeExceptionally(ApiFailure(503, "unavailable", "稍后重试"))
            runCurrent()
            assertFalse(vm.chat.value.loadingHistory)
            assertFalse(vm.chat.value.historyLoaded)
            assertNull(vm.chat.value.historyErrorBefore)
            vm.send()
            assertEquals(0, api.sends)
            api.read = { path -> if (path.contains("/messages")) page("one", 11..40, 11) else api.defaultReply(path) }
            vm.restoreChat()
            vm.send()
            runCurrent()
            assertEquals(1, api.sends)
            assertEquals((11..42).map(Int::toLong), vm.chat.value.messages.map { it.messageId })
            assertEquals(11L, vm.chat.value.nextBefore)
            assertEquals("新回答", vm.chat.value.messages.last().segments.single().text)
            assertEquals(2, api.paths.count { it == "/conversations/one/messages?limit=30" })
            assertNull(vm.state.value.error)
        } finally { vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }

    @Test fun `failed refresh of loaded conversation keeps readable history and its cursor`() = runTest {
        val (vm, api) = fixture()
        api.read = { path -> if (path.contains("/messages")) page("one", 31..60, 31) else api.defaultReply(path) }
        try {
            vm.selectChat("one")
            val messages = vm.chat.value.messages
            val refreshed = CompletableDeferred<JsonObject>()
            api.read = { path -> when {
                path.contains("before=") -> page("one", 1..30)
                path.contains("/messages") -> refreshed.await()
                else -> api.defaultReply(path)
            } }
            vm.restoreChat(); vm.draft("继续"); vm.send()
            assertEquals(messages, vm.chat.value.messages)
            assertEquals(31L, vm.chat.value.nextBefore)
            assertEquals(0, api.sends)
            refreshed.completeExceptionally(ApiFailure(503, "unavailable", "稍后重试")); runCurrent()
            assertEquals(messages, vm.chat.value.messages)
            assertEquals(31L, vm.chat.value.nextBefore)
            assertTrue(vm.chat.value.historyLoaded)
            assertFalse(vm.chat.value.loadingHistory)
            assertNotNull(vm.chat.value.historyError)
            assertNull(vm.chat.value.historyErrorBefore)
            vm.loadEarlierMessages()
            assertEquals((1..60).map(Int::toLong), vm.chat.value.messages.map { it.messageId })
            assertNull(vm.chat.value.nextBefore)
        } finally { vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }

    @Test fun `earlier page can finish during a reply without losing deltas or final card`() = runTest {
        val (vm, api) = fixture()
        val earlier = CompletableDeferred<JsonObject>()
        val events = Channel<StreamEvent>(Channel.UNLIMITED)
        api.read = { path -> when {
            path.contains("before=") -> earlier.await()
            path.contains("/messages") -> page("one", 31..60, 31)
            else -> api.defaultReply(path)
        } }
        api.stream = { events.receiveAsFlow() }
        try {
            vm.selectChat("one")
            vm.loadEarlierMessages()
            vm.draft("继续"); vm.send()
            events.send(start("one", 61, 62)); events.send(delta("第一段")); events.send(card(false)); runCurrent()
            assertTrue(vm.chat.value.streaming)
            assertTrue(vm.chat.value.loadingEarlier)
            earlier.complete(page("one", 1..30)); runCurrent()
            assertEquals((1..62).map(Int::toLong), vm.chat.value.messages.map { it.messageId })
            assertFalse(vm.chat.value.messages.last().segments.last().final)
            events.send(card(true)); events.send(delta("第二段")); events.send(complete); events.close(); runCurrent()
            val reply = vm.chat.value.messages.last()
            assertEquals("第一段第二段", reply.segments.filter { !it.hasBlock }.joinToString("") { it.text })
            assertTrue(reply.segments.single { it.hasBlock }.final)
            assertFalse(reply.pending)
            assertFalse(vm.chat.value.streaming)
            assertNull(vm.chat.value.nextBefore)
            assertNull(vm.state.value.error)
        } finally { events.cancel(); vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }

    @Test fun `earlier failure retains messages and cursor and retries that cursor only`() = runTest {
        val (vm, api) = fixture()
        var fail = true
        api.read = { path -> when {
            path.contains("before=") -> if (fail) throw ApiFailure(503, "unavailable", "稍后重试") else page("one", 1..30)
            path.contains("/messages") -> page("one", 31..60, 31)
            else -> api.defaultReply(path)
        } }
        try {
            vm.selectChat("one"); val messages = vm.chat.value.messages
            vm.loadEarlierMessages()
            assertEquals(messages, vm.chat.value.messages)
            assertEquals(31L, vm.chat.value.nextBefore)
            assertEquals(31L, vm.chat.value.historyErrorBefore)
            assertTrue(vm.chat.value.historyLoaded)
            fail = false; vm.loadEarlierMessages()
            assertEquals(2, api.paths.count { it.endsWith("before=31") })
            assertEquals((1..60).map(Int::toLong), vm.chat.value.messages.map { it.messageId })
            assertNull(vm.chat.value.historyError)
            assertNull(vm.chat.value.historyErrorBefore)
        } finally { vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }

    @Test fun `empty final older page clears cursor without replacing visible messages`() = runTest {
        val (vm, api) = fixture()
        api.read = { path -> when {
            path.contains("before=") -> page("one", IntRange.EMPTY)
            path.contains("/messages") -> page("one", 31..60, 31)
            else -> api.defaultReply(path)
        } }
        try {
            vm.selectChat("one")
            val messages = vm.chat.value.messages
            vm.loadEarlierMessages(); vm.loadEarlierMessages()
            assertEquals(messages, vm.chat.value.messages)
            assertNull(vm.chat.value.nextBefore)
            assertEquals(1, api.paths.count { it.contains("before=") })
        } finally { vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }

    @Test fun `cart refresh failure does not prevent latest history from completing`() = runTest {
        val (vm, api) = fixture()
        val latest = CompletableDeferred<JsonObject>()
        api.read = { path -> when {
            path.contains("/messages") -> latest.await()
            path == "/cart" -> throw ApiFailure(503, "unavailable", "购物车暂不可用")
            else -> api.defaultReply(path)
        } }
        try {
            vm.selectChat("one"); vm.refreshCart()
            assertTrue(vm.chat.value.loadingHistory)
            assertNotNull(vm.state.value.error)
            latest.complete(page("one", 31..60, 31)); runCurrent()
            assertTrue(vm.chat.value.historyLoaded)
            assertFalse(vm.chat.value.loadingHistory)
            assertNull(vm.chat.value.historyError)
            assertEquals((31..60).map(Int::toLong), vm.chat.value.messages.map { it.messageId })
        } finally { vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }

    @Test fun `late cancelled latest cannot replace a selected conversation or its completed reply`() = runTest {
        val (vm, api) = fixture()
        val old = CompletableDeferred<JsonObject>()
        api.read = { path -> when {
            path.contains("/old/messages") -> withContext(NonCancellable) { old.await() }
            path.contains("/new/messages") -> page("new", 1..2)
            else -> api.defaultReply(path)
        } }
        api.stream = { id -> flowOf(start(id, 3, 4), delta("新会话结果"), complete) }
        try {
            vm.selectChat("old"); vm.selectChat("new")
            vm.draft("继续"); vm.send(); runCurrent()
            old.complete(page("old", 1..30)); runCurrent()
            assertEquals("new", vm.chat.value.conversationKey)
            assertEquals(listOf(1L, 2L, 3L, 4L), vm.chat.value.messages.map { it.messageId })
            assertEquals("新会话结果", vm.chat.value.messages.last().segments.single().text)
        } finally { vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }

    @Test fun `late earlier failure after switching cannot clear another account or page`() = runTest {
        val (vm, api, store) = fixture()
        val old = CompletableDeferred<JsonObject>()
        api.read = { path -> when {
            path.contains("before=") -> withContext(NonCancellable) { old.await() }
            path.contains("/one/messages") -> page("one", 31..60, 31)
            path.contains("/two/messages") -> page("two", 1..2)
            else -> api.defaultReply(path)
        } }
        try {
            vm.selectChat("one"); vm.loadEarlierMessages(); vm.selectChat("two")
            old.completeExceptionally(ApiFailure(401, "unauthorized", "旧请求失败")); runCurrent()
            assertEquals("test-buyer", store.owner)
            assertEquals("two", vm.chat.value.conversationKey)
            assertEquals(listOf(1L, 2L), vm.chat.value.messages.map { it.messageId })
            assertNull(vm.chat.value.historyError)
            assertNull(vm.state.value.error)
        } finally { vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }

    @Test fun `stop cancels transport while an earlier page remains independent`() = runTest {
        val (vm, api) = fixture()
        val earlier = CompletableDeferred<JsonObject>()
        var cancelled = false
        api.read = { path -> when {
            path.contains("before=") -> earlier.await()
            path.contains("/messages") -> page("one", 31..60, 31)
            else -> api.defaultReply(path)
        } }
        api.stream = { id -> flow {
            try { emit(start(id, 61, 62)); emit(delta("收到的部分")); emit(card(false)); awaitCancellation() }
            finally { cancelled = true }
        } }
        try {
            vm.selectChat("one"); vm.loadEarlierMessages(); vm.draft("继续"); vm.send()
            vm.stopChat(); runCurrent()
            assertTrue(cancelled)
            assertFalse(vm.chat.value.streaming)
            assertFalse(vm.chat.value.messages.last().pending)
            assertFalse(vm.chat.value.messages.last().segments.last().final)
            assertTrue(vm.chat.value.loadingEarlier)
            earlier.complete(page("one", 1..30)); runCurrent()
            assertEquals((1..62).map(Int::toLong), vm.chat.value.messages.map { it.messageId })
            vm.newChat()
            assertTrue(vm.chat.value.messages.isEmpty())
            assertNull(vm.chat.value.nextBefore)
        } finally { vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }

    @Test fun `text before canonical start fails without inventing message ids`() = runTest {
        val (vm, api) = fixture()
        api.read = { path -> if (path.contains("/messages")) page("one", 1..2) else api.defaultReply(path) }
        api.stream = { flowOf(delta("不合法"), complete) }
        try {
            vm.selectChat("one"); vm.draft("继续"); vm.send(); runCurrent()
            assertEquals(listOf(1L, 2L), vm.chat.value.messages.map { it.messageId })
            assertNotNull(vm.state.value.error)
            assertFalse(vm.chat.value.streaming)
            assertEquals("继续", vm.chat.value.draft)
        } finally { vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }

    @Test fun `restored remote pending does not pretend that local transport is running`() = runTest {
        val (vm, api) = fixture()
        api.read = { path -> if (path.contains("/messages")) page("one", 1..2, pending = true) else api.defaultReply(path) }
        try {
            vm.selectChat("one")
            assertTrue(vm.chat.value.messages.last().pending)
            assertFalse(vm.chat.value.streaming)
            assertTrue(vm.chat.value.historyLoaded)
        } finally { vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }

    @Test fun `logout discards a noncancellable old page result`() = runTest {
        val (vm, api) = fixture()
        val old = CompletableDeferred<JsonObject>()
        api.read = { withContext(NonCancellable) { old.await() } }
        try {
            vm.selectChat("one"); vm.logout()
            old.complete(page("one", 1..30)); runCurrent()
            assertEquals(ChatState(), vm.chat.value)
            assertFalse(vm.state.value.signedIn)
        } finally { vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }
}

private class HistoryApi : BuyerApi() {
    val paths = mutableListOf<String>()
    var sends = 0
    var read: suspend (String) -> JsonObject = ::defaultReply
    var stream: (String) -> Flow<StreamEvent> = { emptyFlow() }
    fun defaultReply(path: String): JsonObject = if (path == "/cart")
        buildJsonObject { putJsonObject("quote") { put("version", 0); put("currency", "CNY"); put("subtotalMinor", 0); put("checkoutReady", false); putJsonArray("items") {} } }
        else JsonObject(emptyMap())
    override suspend fun json(path: String, body: JsonObject?, method: String): JsonObject { paths += path; return read(path) }
    override fun chat(id: String, message: String, page: JsonObject): Flow<StreamEvent> { sends++; return stream(id) }
}

private class HistoryStorage : BuyerStorage {
    override var endpoint = "https://shopmate.test"
    override var commerceEndpoint = "https://commerce.test"
    override var owner = "test-buyer"
    override var conversation: String? = null
    private var accessToken: String? = null
    private var writes = emptyList<PendingWrite>()
    private var reservations = emptyList<SeckillTicket>()
    override fun token() = accessToken
    override fun login(owner: String, token: String) { this.owner = owner; accessToken = token }
    override fun logout() { owner = ""; accessToken = null; conversation = null }
    override fun pending() = writes
    override fun savePending(values: List<PendingWrite>) { writes = values }
    override fun tickets() = reservations
    override fun saveTickets(values: List<SeckillTicket>) { reservations = values }
}
