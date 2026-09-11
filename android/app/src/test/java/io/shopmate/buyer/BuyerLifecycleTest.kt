package io.shopmate.buyer

import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.*
import kotlinx.coroutines.test.*
import kotlinx.serialization.json.*
import org.junit.Assert.*
import org.junit.Test

@OptIn(ExperimentalCoroutinesApi::class)
class BuyerLifecycleTest {
    private fun product(id: String) = Product(id, "商品 $id", 10.0)
    private fun response(product: Product) = buildJsonObject {
        put("product", wireJson.encodeToJsonElement(Product.serializer(), product))
    }

    private fun TestScope.fixture(): Triple<BuyerViewModel, FakeBuyerApi, MemoryBuyerStorage> {
        Dispatchers.setMain(UnconfinedTestDispatcher(testScheduler))
        val api = FakeBuyerApi()
        val store = MemoryBuyerStorage()
        return Triple(BuyerViewModel(api, store), api, store)
    }

    @Test fun `late detail cannot replace newer product or reopen dismissed detail`() = runTest {
        val (vm, api) = fixture()
        val old = CompletableDeferred<JsonObject>()
        api.read = { path, _, _ -> if (path.endsWith("/A")) withContext(NonCancellable) { old.await() } else response(product("B")) }
        try {
            vm.openProduct("A")
            vm.openProduct("B")
            assertEquals("B", vm.state.value.selected?.product_id)
            old.complete(response(product("A")))
            runCurrent()
            assertEquals("B", vm.state.value.selected?.product_id)
            val closing = CompletableDeferred<JsonObject>()
            api.read = { _, _, _ -> withContext(NonCancellable) { closing.await() } }
            vm.openProduct("C")
            vm.closeProduct()
            closing.complete(response(product("C")))
            runCurrent()
            assertFalse(vm.state.value.productOpen)
            assertNull(vm.state.value.selected)
        } finally { vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }

    @Test fun `contextual assistant returns to original product and selected variant`() = runTest {
        val (vm, api) = fixture()
        val variant = product("red")
        api.read = { _, _, _ -> response(product("family").copy(variants = listOf(variant))) }
        try {
            vm.openProduct("family")
            vm.chooseVariant("red")
            vm.askProduct(variant)
            assertEquals("助手", vm.state.value.screen)
            assertFalse(vm.state.value.productOpen)
            assertEquals("red", vm.state.value.variantId)
            vm.back()
            assertEquals("首页", vm.state.value.screen)
            assertTrue(vm.state.value.productOpen)
            assertEquals("family", vm.state.value.selected?.product_id)
            assertEquals("red", vm.state.value.variantId)
            vm.back()
            assertFalse(vm.state.value.productOpen)
            vm.navigate("限量发售")
            vm.back()
            assertEquals("首页", vm.state.value.screen)
        } finally { vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }

    @Test fun `accepted write is not pending again when followup refresh fails`() = runTest {
        val (vm, api, store) = fixture()
        var writes = 0
        api.read = { path, _, _ ->
            if (path == "/cart/add") { writes++; JsonObject(emptyMap()) }
            else throw ApiFailure(503, "unavailable", "刷新暂时不可用")
        }
        try {
            vm.add(product("cup"))
            assertEquals(1, writes)
            assertTrue(store.pending().isEmpty())
            assertTrue(vm.state.value.notice!!.contains("操作已受理"))
            assertTrue(vm.state.value.notice!!.contains("无法刷新"))
            assertFalse(vm.state.value.writing)
            assertEquals("刷新暂时不可用", vm.state.value.error)
        } finally { vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }

    @Test fun `polling is visible foreground only and resumes original reservation`() = runTest {
        val (vm, api, store) = fixture()
        store.saveTickets(listOf(SeckillTicket("original", "offer", 1, "reservation", "ADMITTED")))
        var polls = 0
        api.sale = { path ->
            if (path.startsWith("/reservations/")) { polls++; buildJsonObject { put("state", "ADMITTED"); put("reservationId", "reservation") } }
            else buildJsonObject { putJsonArray("activities") {} }
        }
        try {
            vm.navigate("限量发售")
            advanceTimeBy(5000); runCurrent()
            assertEquals(0, polls)
            vm.setForeground(true)
            assertEquals(1, polls)
            vm.setForeground(false)
            advanceTimeBy(10000); runCurrent()
            assertEquals(1, polls)
            vm.setForeground(true)
            assertEquals(2, polls)
            vm.navigate("首页")
            advanceTimeBy(10000); runCurrent()
            assertEquals(2, polls)
            vm.navigate("限量发售")
            assertEquals(3, polls)
            assertEquals("original", store.tickets().single().key)
            assertFalse(api.salePaths.any { it.contains("activities/offer/reservations") })
        } finally { vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }

    @Test fun `polling stops on terminal result and has a finite waiting budget`() = runTest {
        val (vm, api, store) = fixture()
        store.saveTickets(listOf(SeckillTicket("original", "offer", 1, "reservation", "ADMITTED")))
        var polls = 0
        api.sale = { path ->
            if (path.startsWith("/reservations/")) { polls++; buildJsonObject { put("state", "ADMITTED"); put("reservationId", "reservation") } }
            else buildJsonObject { putJsonArray("activities") {} }
        }
        try {
            vm.setForeground(true); vm.navigate("限量发售")
            advanceTimeBy(120000); runCurrent()
            assertEquals(30, polls)
            assertTrue(vm.state.value.notice!!.contains("已暂停自动查询"))
            api.sale = { path ->
                if (path.startsWith("/reservations/")) { polls++; buildJsonObject { put("state", "ORDERED"); put("reservationId", "reservation"); put("orderId", "order") } }
                else buildJsonObject { putJsonArray("activities") {} }
            }
            vm.loadSeckill()
            assertEquals(31, polls)
            advanceTimeBy(120000); runCurrent()
            assertEquals(31, polls)
            assertEquals("order", store.tickets().single().orderId)
        } finally { vm.viewModelScope.cancel(); Dispatchers.resetMain() }
    }
}

private class FakeBuyerApi : BuyerApi() {
    var read: suspend (String, JsonObject?, String) -> JsonObject = { _, _, _ -> JsonObject(emptyMap()) }
    var sale: suspend (String) -> JsonObject = { JsonObject(emptyMap()) }
    val salePaths = mutableListOf<String>()
    override suspend fun json(path: String, body: JsonObject?, method: String) = read(path, body, method)
    override suspend fun seckill(path: String, body: JsonObject?, key: String?): JsonObject {
        salePaths += path
        return sale(path)
    }
}

private class MemoryBuyerStorage : BuyerStorage {
    override var endpoint = "https://shopmate.test"
    override var commerceEndpoint = "https://commerce.test"
    override var owner = "test-buyer"
    override var conversation: String? = null
    private var accessToken: String? = null
    private var writes = emptyList<PendingWrite>()
    private var reservations = emptyList<SeckillTicket>()
    override fun token() = accessToken
    override fun login(owner: String, token: String) { this.owner = owner; accessToken = token }
    override fun logout() { owner = ""; accessToken = null }
    override fun pending() = writes
    override fun savePending(values: List<PendingWrite>) { writes = values }
    override fun tickets() = reservations
    override fun saveTickets(values: List<SeckillTicket>) { reservations = values }
}
