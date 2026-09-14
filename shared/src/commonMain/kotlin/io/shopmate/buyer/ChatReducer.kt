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

}

/** Run on the UI owner's thread; network and lifecycle cancellation stay platform-owned. */
class ChatTimeline {
    var messages: List<ChatMessage> = emptyList()
        private set
    var nextBefore: Long? = null
        private set
    private var sessionId: String? = null
    private var assistantId: Long? = null
    private val appliedBefore = mutableMapOf<Long, Long?>()

    @Throws(Exception::class)
    fun begin(text: String, event: StreamEvent, sessionId: String) {
        require(event.type == "turn_started") { "回复缺少开始信息" }
        require(sessionId.isNotBlank() && event.data.requiredText("session_id") == sessionId) { "回复会话不匹配" }
        require(this.sessionId == null || this.sessionId == sessionId) { "回复会话已切换" }
        val userId = event.data.positiveId("user_message_id")
        val replyId = event.data.positiveId("assistant_message_id")
        require(userId > (messages.lastOrNull()?.messageId ?: 0L) && replyId > userId) { "回复消息顺序无效" }
        messages = messages + ChatMessage(userId, true, listOf(ChatSegment(text))) +
            ChatMessage(replyId, false, emptyList(), pending = true)
        this.sessionId = sessionId
        assistantId = replyId
    }

    @Throws(Exception::class)
    fun accept(event: StreamEvent) {
        check(assistantId != null) { "回复尚未开始或已经结束" }
        require(event.type != "turn_started") { "回复重复开始" }
        val last = messages.last()
        check(last.messageId == assistantId) { "当前回复不在对话末尾" }
        if (event.type == "turn_complete" || event.type == "error") {
            interrupt()
            return
        }
        val updated = ChatReducer.apply(last, event)
        if (updated !== last) messages = messages.dropLast(1) + updated
    }

    /** End the local stream without changing a restored reply that is pending on the server. */
    fun interrupt() {
        if (assistantId == null) return
        messages = messages.dropLast(1) + messages.last().copy(pending = false)
        assistantId = null
    }

    @Throws(Exception::class)
    fun restorePage(payload: String, sessionId: String) {
        val page = historyPage(payload, sessionId)
        messages = page.messages
        nextBefore = page.nextBefore
        this.sessionId = sessionId
        assistantId = null
        appliedBefore.clear()
    }

    @Throws(Exception::class)
    fun prependPage(payload: String, before: Long): Boolean {
        val currentSession = checkNotNull(sessionId) { "请先加载当前对话" }
        val page = historyPage(payload, currentSession)
        require(before > 0 && page.messages.all { it.messageId < before }) { "历史页超出请求边界" }
        if (appliedBefore.containsKey(before)) {
            val previousNext = appliedBefore[before]
            val previousMessages = messages.filter { it.messageId < before && (previousNext == null || it.messageId >= previousNext) }
            require(page.nextBefore == previousNext && page.messages == previousMessages) { "重复历史页内容不一致" }
            return false
        }
        require(nextBefore == before) { "历史页边界已改变" }
        messages = page.messages + messages
        nextBefore = page.nextBefore
        appliedBefore[before] = page.nextBefore
        return page.messages.isNotEmpty()
    }

    fun clear() {
        messages = emptyList()
        nextBefore = null
        sessionId = null
        assistantId = null
        appliedBefore.clear()
    }
}

private data class HistoryPage(val messages: List<ChatMessage>, val nextBefore: Long?)

private fun historyPage(payload: String, sessionId: String): HistoryPage {
    val page = wireJson.parseToJsonElement(payload).jsonObject
    require(sessionId.isNotBlank() && page.requiredText("session_id") == sessionId) { "历史页会话不匹配" }
    require(page.requiredText("status").isNotBlank()) { "历史页状态缺失" }
    val messages = page.requiredRows("items").map { item ->
        val id = item.positiveId("message_id")
        when (item.requiredText("kind")) {
            "user" -> ChatMessage(id, true, listOf(ChatSegment(item.requiredText("text"))))
            "assistant" -> {
                val segments = item.requiredRows("segments").map { segment ->
                    when (segment.requiredText("type")) {
                        "text", "error" -> ChatSegment(segment.requiredText("text"))
                        "ui" -> {
                            val status = segment.requiredText("status")
                            require(status == "partial" || status == "final") { "卡片状态无效" }
                            ChatSegment(block = segment.getValue("block").jsonObject,
                                slot = segment.requiredText("slotKey"), final = status == "final")
                        }
                        else -> throw IllegalArgumentException("历史消息片段无效")
                    }
                }
                val suggestions = item["suggestions"]?.jsonArray?.map {
                    require(it is JsonPrimitive && it.isString) { "建议必须是文本" }
                    it.content
                } ?: emptyList()
                val pending = item["pending"]?.let {
                    require(it is JsonPrimitive && !it.isString && it.booleanOrNull != null) { "回复状态无效" }
                    it.boolean
                } ?: false
                ChatMessage(id, false, segments, suggestions, pending)
            }
            else -> throw IllegalArgumentException("历史消息类型无效")
        }
    }
    require(messages.zipWithNext().all { (first, second) -> first.messageId < second.messageId }) { "历史消息顺序无效" }
    val next = if (page.getValue("next_before") == JsonNull) null else page.positiveId("next_before")
    require(next == null || next == messages.firstOrNull()?.messageId) { "历史页游标无效" }
    return HistoryPage(messages, next)
}

private fun JsonObject.requiredText(key: String): String {
    val value = getValue(key)
    require(value is JsonPrimitive && value.isString) { "$key 必须是文本" }
    return value.content
}

private fun JsonObject.requiredRows(key: String): List<JsonObject> = getValue(key).jsonArray.map { it.jsonObject }

private fun JsonObject.positiveId(key: String): Long {
    val value = getValue(key)
    require(value is JsonPrimitive && !value.isString) { "$key 必须是整数" }
    // JsonPrimitive.longOrNull accepts exponent notation, which is not a message-ID integer.
    val number = value.content.takeIf { digits ->
        digits.firstOrNull() != '0' && digits.all { it in '0'..'9' }
    }?.toLongOrNull()
    require(number != null && number > 0) { "$key 必须是正整数" }
    return number
}
