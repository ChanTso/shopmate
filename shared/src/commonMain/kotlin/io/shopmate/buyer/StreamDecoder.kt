package io.shopmate.buyer

import kotlinx.serialization.json.jsonObject

/** One decoder per HTTP response. Transports supply complete UTF-8 lines. */
class StreamDecoder {
    private var type = ""
    private val data = mutableListOf<String>()
    var terminal: Boolean = false
        private set

    @Throws(Exception::class)
    fun line(raw: String): StreamEvent? {
        if (raw.isEmpty()) {
            if (data.isEmpty()) { type = ""; return null }
            val event = StreamEvent(type, wireJson.parseToJsonElement(data.joinToString("\n")).jsonObject)
            type = ""
            data.clear()
            if (event.type == "turn_complete" || event.type == "error") terminal = true
            return event
        }
        val field = raw.substringBefore(':')
        val value = raw.substringAfter(':', "").removePrefix(" ")
        when (field) {
            "event" -> type = value
            "data" -> data.add(value)
        }
        return null
    }

    @Throws(Exception::class)
    fun finish() {
        check(terminal) { "连接中断，请恢复对话并核对订单或购物车" }
    }
}
