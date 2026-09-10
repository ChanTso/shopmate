package io.shopmate.buyer

import kotlin.test.*
import kotlinx.serialization.json.*

class BuyerCoreTest {
    private fun event(type: String, payload: String) =
        StreamEvent(type, wireJson.parseToJsonElement(payload).jsonObject)

    @Test fun partialCardIsReplacedWithoutLosingSurroundingText() {
        val timeline = ChatTimeline()
        timeline.begin("推荐一套装备")
        timeline.accept(event("text_delta", """{"text":"可以选择"}"""))
        timeline.accept(event("ui_partial", """{"component":"product_grid","stream_id":"one","payload":{}}"""))
        timeline.accept(event("text_delta", """{"text":"，预算内"}"""))
        timeline.accept(event("ui", """{"component":"product_grid","stream_id":"one","payload":{"products":[{"product_id":"a"}]}}"""))
        val message = timeline.messages.last()
        assertEquals(3, message.segments.size)
        assertEquals("可以选择", message.segments[0].text)
        assertTrue(message.segments[1].final)
        assertEquals("a", message.segments[1].block!!.obj("payload").rows("products").single().text("product_id"))
        assertEquals("，预算内", message.segments[2].text)
    }

    @Test fun suggestionsDoNotReplaceProductCards() {
        val timeline = ChatTimeline()
        timeline.begin("比较")
        timeline.accept(event("ui", """{"component":"product_grid","payload":{}}"""))
        timeline.accept(event("ui_partial", """{"component":"suggestions","payload":{"suggestions":["incomplete"]}}"""))
        assertTrue(timeline.messages.last().suggestions.isEmpty())
        timeline.accept(event("ui", """{"component":"suggestions","payload":{"suggestions":["再看一款"]}}"""))
        assertEquals(listOf("再看一款"), timeline.messages.last().suggestions)
        assertEquals(1, timeline.messages.last().segments.size)
    }

    @Test fun decoderRequiresExplicitTerminalAndHandlesMultilineData() {
        val decoder = StreamDecoder()
        assertNull(decoder.line(": heartbeat"))
        decoder.line("event: text_delta")
        decoder.line("data: {")
        decoder.line("data: \"text\":\"你好\"}")
        assertEquals("你好", decoder.line("")!!.data.text("text"))
        assertFailsWith<IllegalStateException> { decoder.finish() }
        decoder.line("event: turn_complete")
        decoder.line("data: {}")
        assertEquals("turn_complete", decoder.line("")!!.type)
        decoder.finish()
    }

    @Test fun malformedDataDoesNotBecomeAnEmptySuccessfulEvent() {
        val decoder = StreamDecoder()
        decoder.line("event: ui")
        decoder.line("data: broken")
        assertFails { decoder.line("") }
    }

    @Test fun restoredHistoryKeepsFinalAndPartialCardDistinction() {
        val timeline = ChatTimeline()
        timeline.restore("""{"items":[{"kind":"user","text":"比较"},{"kind":"assistant","segments":[{"type":"text","text":"结果"},{"type":"ui","slotKey":"p","status":"partial","block":{"component":"product_grid"}}],"suggestions":["继续"]}]}""")
        assertEquals(2, timeline.messages.size)
        assertTrue(timeline.messages.first().user)
        assertFalse(timeline.messages.last().segments.last().final)
        assertEquals(listOf("继续"), timeline.messages.last().suggestions)
    }

    @Test fun invalidSuggestionsAreRejectedAtTheModelBoundary() {
        val timeline = ChatTimeline()
        timeline.begin("比较")
        assertFailsWith<IllegalArgumentException> {
            timeline.accept(event("ui", """{"component":"suggestions","payload":{"suggestions":[{}]}}"""))
        }
        assertTrue(timeline.messages.last().suggestions.isEmpty())
    }

    @Test fun restartPreservesOriginalIntentAndUnknownOutcomes() {
        val original = WriteRecovery.prepare("original-key", "/cart/add", """{"productId":"a","quantity":1}""")
        val restored = WriteRecovery.decode(WriteRecovery.encode(original))
        assertEquals(original, restored)
        assertEquals("original-key", restored.body.text("request_key"))
        listOf(0, 401, 408, 429, 500, 503).forEach { assertTrue(WriteRecovery.retain(it, "")) }
        assertTrue(WriteRecovery.retain(409, "unknown_cart"))
        listOf("INDETERMINATE", "INCONSISTENT_DURABLE_STATE", "RETRYABLE_CONCURRENCY", "COMMERCE_ERROR").forEach {
            assertTrue(WriteRecovery.retain(409, it))
        }
        assertFalse(WriteRecovery.retain(409, "VERSION_CONFLICT"))
        assertFalse(WriteRecovery.retain(403, "forbidden"))
    }

    @Test fun checkoutUsesAuthoritativeIntegerQuoteAndVersions() {
        val body = WriteRecovery.checkoutBody("""{"version":7,"currency":"CNY","subtotalMinor":37800,"checkoutReady":true,"items":[{"productId":"kettle","quantity":2,"name":"壶","unitPriceMinor":18900,"currency":"CNY","productVersion":4,"lineTotalMinor":37800,"orderable":true}]}""")
        val json = wireJson.parseToJsonElement(body).jsonObject
        assertEquals(7L, json.number("expectedCartVersion"))
        assertEquals(18900L, json.rows("items").single().number("expectedUnitPriceMinor"))
    }
}
