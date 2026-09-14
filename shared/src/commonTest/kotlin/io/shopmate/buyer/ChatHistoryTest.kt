package io.shopmate.buyer

import kotlin.test.*
import kotlinx.serialization.json.*

class ChatHistoryTest {
    private fun event(type: String, payload: String) = StreamEvent(type, wireJson.parseToJsonElement(payload).jsonObject)
    private fun started(userId: Long, assistantId: Long, session: String = "one") = event("turn_started",
        """{"session_id":"$session","user_message_id":$userId,"assistant_message_id":$assistantId}""")
    private fun user(id: Long, text: String = "问题$id") = """{"message_id":$id,"kind":"user","text":"$text"}"""
    private fun reply(id: Long) = """{"message_id":$id,"kind":"assistant","segments":[{"type":"text","text":"回答$id"}]}"""
    private fun page(vararg items: String, next: Long? = null, session: String = "one") =
        """{"session_id":"$session","status":"completed","items":[${items.joinToString(",")}],"next_before":$next}"""

    @Test fun recentPageUsesPersistentIdsAndRestoresPendingWithoutStartingTransport() {
        val timeline = ChatTimeline()
        timeline.restorePage("""{"session_id":"one","status":"running","items":[{"message_id":6,"kind":"assistant","pending":true,"segments":[{"type":"ui","slotKey":"saved","status":"partial","block":{"component":"products","payload":{}}}]}],"next_before":6}""", "one")
        assertEquals(6L, timeline.messages.single().messageId)
        assertEquals(6L, timeline.nextBefore)
        assertTrue(timeline.messages.single().pending)
        assertFalse(timeline.messages.single().segments.single().final)
        assertFailsWith<IllegalStateException> { timeline.accept(event("text_delta", """{"text":"不能附着到已存回复"}""")) }
    }

    @Test fun olderPagesDoNotReplaceTheCurrentTextOrPartialToFinalCard() {
        val timeline = ChatTimeline()
        timeline.restorePage(page(user(5), reply(6), next = 5), "one")
        timeline.begin("新问题", started(7, 8), "one")
        timeline.accept(event("text_delta", """{"text":"新的回答"}"""))
        timeline.accept(event("ui_partial", """{"component":"products","stream_id":"card","payload":{}}"""))
        val partial = timeline.messages.last()
        val older = page(user(3), reply(4), next = 3)
        assertTrue(timeline.prependPage(older, 5))
        assertSame(partial, timeline.messages.last())
        timeline.accept(event("ui", """{"component":"products","stream_id":"card","payload":{"title":"最终卡片"}}"""))
        val final = timeline.messages.last()
        assertTrue(timeline.prependPage(page(user(1), reply(2)), 3))
        assertFalse(timeline.prependPage(older, 5))
        assertSame(final, timeline.messages.last())
        assertEquals((1L..8L).toList(), timeline.messages.map { it.messageId })
        assertEquals("新的回答", final.segments.first().text)
        assertTrue(final.segments.last().final)
        assertNull(timeline.nextBefore)
        timeline.accept(event("turn_complete", "{}"))
        assertFalse(timeline.messages.last().pending)
        assertFailsWith<IllegalStateException> { timeline.accept(event("text_delta", """{"text":"晚到事件"}""")) }
    }

    @Test fun changedDuplicateAndOverlappingBoundaryCannotOverwriteLoadedMessages() {
        val timeline = ChatTimeline()
        timeline.restorePage(page(user(5), reply(6), next = 5), "one")
        val older = page(user(3), reply(4), next = 3)
        timeline.prependPage(older, 5)
        val messages = timeline.messages
        listOf(
            page(user(3, "篡改文本"), reply(4), next = 3) to 5L,
            page(user(1), reply(2), user(3), reply(4), next = 1) to 5L,
            page(user(3), reply(4), user(5), next = 3) to 5L,
            page(user(1), reply(2), next = 1) to 4L,
        ).forEach { (payload, before) ->
            assertFailsWith<IllegalArgumentException> { timeline.prependPage(payload, before) }
            assertSame(messages, timeline.messages)
            assertEquals(3L, timeline.nextBefore)
        }
        assertFalse(timeline.prependPage(older, 5))
        assertSame(messages, timeline.messages)
    }

    @Test fun invalidPagesLeaveTheMessagesAndCursorIntact() {
        val timeline = ChatTimeline()
        timeline.restorePage(page(user(5), reply(6), next = 5), "one")
        val messages = timeline.messages
        val invalid = listOf(
            page(user(1), session = "other"),
            page(user(2), user(1)),
            page(user(1), user(1)),
            page(user(1), next = 2),
            page(next = 1),
            page("null"),
            page("""{"kind":"user","text":"missing ID"}"""),
            page("""{"message_id":"1","kind":"user","text":"quoted ID"}"""),
            page("""{"message_id":1.0,"kind":"user","text":"decimal ID"}"""),
            page("""{"message_id":1e0,"kind":"user","text":"exponent ID"}"""),
            page("""{"message_id":1e1,"kind":"user","text":"scaled ID"}"""),
            page("""{"message_id":01,"kind":"user","text":"leading zero ID"}"""),
            page("""{"message_id":+1,"kind":"user","text":"plus ID"}"""),
            page("""{"message_id":9223372036854775808,"kind":"user","text":"overflow ID"}"""),
            page(user(0)),
            page(user(-1)),
            page("""{"message_id":1,"kind":"unknown"}"""),
            page("""{"message_id":1,"kind":"user","text":false}"""),
            page("""{"message_id":1,"kind":"assistant","segments":[null]}"""),
            page("""{"message_id":1,"kind":"assistant","segments":[],"suggestions":[false]}"""),
            page("""{"message_id":1,"kind":"assistant","segments":[],"pending":"true"}"""),
            """{"session_id":"one","status":"completed","items":[]}""",
            """{"session_id":"one","items":[],"next_before":null}""",
            page(user(1)).replace("\"next_before\":null", "\"next_before\":\"1\""),
        )
        invalid.forEach { payload ->
            assertFails("Malformed page was accepted: $payload") { timeline.restorePage(payload, "one") }
            assertSame(messages, timeline.messages)
            assertEquals(5L, timeline.nextBefore)
        }
        assertFails { timeline.prependPage(page(user(3), reply(4), next = 3, session = "other"), 5) }
        assertSame(messages, timeline.messages)
        assertEquals(5L, timeline.nextBefore)
    }

    @Test fun sessionReplacementRejectsLatePagesAndRequiresNewStartMetadata() {
        val timeline = ChatTimeline()
        timeline.restorePage(page(user(5), reply(6), next = 5), "one")
        timeline.begin("问题", started(7, 8), "one")
        timeline.clear()
        assertTrue(timeline.messages.isEmpty())
        assertNull(timeline.nextBefore)
        assertFails { timeline.prependPage(page(user(3), reply(4), next = 3), 5) }
        assertFails { timeline.accept(event("text_delta", """{"text":"旧回复"}""")) }
        timeline.restorePage(page(user(1), reply(2), session = "two"), "two")
        assertFails { timeline.begin("旧会话", started(9, 10), "one") }
        assertFails { timeline.prependPage(page(user(3), reply(4), next = 3), 5) }
        timeline.begin("新会话", started(3, 4, "two"), "two")
        assertEquals(listOf(1L, 2L, 3L, 4L), timeline.messages.map { it.messageId })
    }

    @Test fun startMetadataMustMatchTheSessionAndFollowExistingIds() {
        val timeline = ChatTimeline()
        timeline.restorePage(page(user(5), reply(6)), "one")
        val messages = timeline.messages
        listOf(
            event("text_delta", """{"text":"尚未开始"}"""),
            started(7, 8, "other"),
            started(6, 7),
            started(8, 7),
            started(7, 7),
            event("turn_started", """{"session_id":"one","user_message_id":"7","assistant_message_id":8}"""),
        ).forEach {
            assertFailsWith<IllegalArgumentException> { timeline.begin("问题", it, "one") }
            assertSame(messages, timeline.messages)
        }
        timeline.begin("问题", started(7, 8), "one")
        timeline.interrupt()
        timeline.begin("停止后新回复", started(9, 10), "one")
        timeline.accept(event("text_delta", """{"text":"只写最新回复"}"""))
        assertTrue(timeline.messages.first { it.messageId == 8L }.segments.isEmpty())
        assertEquals("只写最新回复", timeline.messages.last().segments.single().text)
    }

    @Test fun interruptAndErrorEndLocalPendingWithoutFinalizingPartialCards() {
        listOf("interrupt", "error", "turn_complete").forEach { ending ->
            val timeline = ChatTimeline()
            timeline.begin("问题", started(1, 2), "one")
            timeline.accept(event("text_delta", """{"text":"已有内容"}"""))
            timeline.accept(event("ui_partial", """{"component":"products","stream_id":"card","payload":{}}"""))
            val segments = timeline.messages.last().segments
            if (ending == "interrupt") timeline.interrupt() else timeline.accept(event(ending, "{}"))
            assertFalse(timeline.messages.last().pending)
            assertSame(segments, timeline.messages.last().segments)
            assertFalse(timeline.messages.last().segments.last().final)
            assertFails { timeline.accept(event("text_delta", """{"text":"晚到内容"}""")) }
            val messages = timeline.messages
            timeline.interrupt()
            assertSame(messages, timeline.messages)
        }
        val restored = ChatTimeline()
        restored.restorePage("""{"session_id":"one","status":"running","items":[{"message_id":2,"kind":"assistant","segments":[],"pending":true}],"next_before":null}""", "one")
        restored.interrupt()
        assertTrue(restored.messages.single().pending)
    }

    @Test fun emptyFinalPageEndsPagingWithoutChangingTheVisibleMessages() {
        val timeline = ChatTimeline()
        timeline.restorePage(page(user(1), reply(2), next = 1), "one")
        val messages = timeline.messages
        assertFalse(timeline.prependPage(page(), 1))
        assertEquals(messages, timeline.messages)
        assertNull(timeline.nextBefore)
        assertFalse(timeline.prependPage(page(), 1))
    }

    @Test fun turnStartedIsNonterminalAndSignedLongIdsAreRetained() {
        val timeline = ChatTimeline()
        val decoder = StreamDecoder()
        decoder.line("event: turn_started")
        decoder.line("data: {\"session_id\":\"one\",\"user_message_id\":9223372036854775806,\"assistant_message_id\":9223372036854775807}")
        timeline.begin("问题", decoder.line("")!!, "one")
        assertEquals(Long.MAX_VALUE, timeline.messages.last().messageId)
        assertFalse(decoder.terminal)
        assertFailsWith<IllegalStateException> { decoder.finish() }
    }
}
