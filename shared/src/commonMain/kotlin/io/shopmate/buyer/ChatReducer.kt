package io.shopmate.buyer

import kotlinx.serialization.json.*

object ChatReducer {
    @Throws(Exception::class)
    fun apply(message: ChatMessage, event: StreamEvent): ChatMessage = when (event.type) {
        "text_delta" -> {
            val last = message.segments.lastOrNull()
            val text = event.data.text("text")
            message.copy(segments = if (last != null && last.block == null)
                message.segments.dropLast(1) + last.copy(text = last.text + text)
                else message.segments + ChatSegment(text))
        }
        "ui", "ui_partial" -> {
            if (event.data.text("component") == "suggestions") {
                if (event.type == "ui") message.copy(suggestions =
                    (event.data.obj("payload")["suggestions"] as? JsonArray)
                        ?.map { it.jsonPrimitive.content } ?: emptyList())
                else message
            } else {
                val slot = event.data.text("stream_id", event.data.text("component"))
                val segment = ChatSegment(block = event.data, slot = slot, final = event.type == "ui")
                val index = message.segments.indexOfFirst { it.slot == slot && it.block != null }
                message.copy(segments = if (index < 0) message.segments + segment
                    else message.segments.toMutableList().also { it[index] = segment })
            }
        }
        else -> message
    }

    @Throws(Exception::class)
    fun restore(payload: String): List<ChatMessage> =
        wireJson.parseToJsonElement(payload).jsonObject.rows("items").map { item ->
            if (item.text("kind") == "user") ChatMessage(true, listOf(ChatSegment(item.text("text"))))
            else ChatMessage(false, item.rows("segments").map { segment ->
                if (segment.text("type") == "ui") ChatSegment(block = segment.obj("block"),
                    slot = segment.text("slotKey"), final = segment.text("status") == "final")
                else ChatSegment(segment.text("text"))
            }, (item["suggestions"] as? JsonArray)?.map { it.jsonPrimitive.content } ?: emptyList())
        }
}

/** Run on the UI owner's thread; network and lifecycle cancellation stay platform-owned. */
class ChatTimeline {
    var messages: List<ChatMessage> = emptyList()
        private set

    fun begin(text: String) {
        messages = messages + ChatMessage(true, listOf(ChatSegment(text))) + ChatMessage(false, emptyList())
    }

    @Throws(Exception::class)
    fun accept(event: StreamEvent) {
        val last = messages.lastOrNull() ?: return
        if (!last.user) messages = messages.dropLast(1) + ChatReducer.apply(last, event)
    }

    @Throws(Exception::class)
    fun restore(payload: String) { messages = ChatReducer.restore(payload) }

    fun clear() { messages = emptyList() }
}
