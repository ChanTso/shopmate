package io.shopmate.buyer

import kotlinx.coroutines.async
import kotlinx.coroutines.flow.toList
import kotlinx.coroutines.runBlocking
import kotlinx.serialization.json.*
import okhttp3.mockwebserver.MockResponse
import okhttp3.mockwebserver.MockWebServer
import org.junit.Assert.*
import org.junit.Test
import java.io.IOException

class BuyerContractTest {
    @Test fun `checkout submits frozen integer price and versions without display prices`() {
        val quote = Quote(7, "CNY", 37800, true, listOf(QuoteItem("kettle", 2, "烧水壶", 18900, "CNY", 4, 37800, true)))
        val command = quote.checkoutBody()
        assertEquals(7L, command.number("expectedCartVersion"))
        val line = command.rows("items").single()
        assertEquals(18900L, line.number("expectedUnitPriceMinor"))
        assertEquals(4L, line.number("expectedProductVersion"))
        assertEquals(2L, line.number("quantity"))
    }
    @Test fun `unorderable quote cannot become an approval`() {
        assertThrows(IllegalArgumentException::class.java) { Quote(1, null, null, false, emptyList()).checkoutBody() }
    }
    @Test fun `refund converts exact decimals and rejects rounding or overflow`() {
        assertEquals(12345L, refundMinor("123.45"))
        assertEquals(10L, refundMinor("0.1"))
        listOf("1.001", "-1", "1e2", "0", "NaN").forEach { raw -> assertThrows(IllegalArgumentException::class.java) { refundMinor(raw) } }
        assertThrows(ArithmeticException::class.java) { refundMinor("999999999999999999999.99") }
    }
    @Test fun `ordinary shopping sends bearer without a conversation`() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("{\"products\":[],\"next_offset\":null}"))
            val api = BuyerApi().apply { root = server.url("/").toString(); token = "unit-test-token" }
            api.json("/products")
            val request = server.takeRequest()
            assertEquals("/api/buyer/products", request.path)
            assertEquals("Bearer unit-test-token", request.getHeader("Authorization"))
            assertNull(request.getHeader("X-Session-Id"))
        }
    }
    @Test fun `stream handles split UTF8 and terminal frames`() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setHeader("Content-Type", "text/event-stream").setBody("event: text_delta\ndata: {\"text\":\"你好\"}\n\nevent: turn_complete\ndata: {}\n\n").throttleBody(1, 1, java.util.concurrent.TimeUnit.MILLISECONDS))
            val api = BuyerApi().apply { root = server.url("/").toString() }
            val events = api.chat("conversation", "你好", JsonObject(emptyMap())).toList()
            assertEquals(listOf("text_delta", "turn_complete"), events.map { it.type })
            assertEquals("你好", events.first().data.text("text"))
        }
    }
    @Test fun `EOF without terminal is not successful completion`() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setBody("event: text_delta\ndata: {\"text\":\"partial\"}\n\n"))
            val api = BuyerApi().apply { root = server.url("/").toString() }
            try { api.chat("c", "hi", JsonObject(emptyMap())).toList(); fail("Must report a disconnect") }
            catch (e: IOException) { assertTrue(e.message!!.contains("连接中断")) }
        }
    }
    @Test fun `cancelling stream releases the request rather than keeping generation attached`() = runBlocking {
        MockWebServer().use { server ->
            server.enqueue(MockResponse().setSocketPolicy(okhttp3.mockwebserver.SocketPolicy.NO_RESPONSE))
            val api = BuyerApi().apply { root = server.url("/").toString() }
            val task = async(kotlinx.coroutines.Dispatchers.Default) { api.chat("c", "hi", JsonObject(emptyMap())).toList() }
            assertNotNull(server.takeRequest(3, java.util.concurrent.TimeUnit.SECONDS))
            task.cancel(); task.join()
            assertTrue(task.isCancelled)
        }
    }
}
