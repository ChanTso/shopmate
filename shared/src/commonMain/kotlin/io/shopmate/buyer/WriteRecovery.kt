package io.shopmate.buyer

import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.*

object WriteRecovery {
    @Throws(Exception::class)
    fun prepare(key: String, path: String, body: String): PendingWrite {
        val payload = wireJson.parseToJsonElement(body).jsonObject
        return PendingWrite(key, path, JsonObject(payload + ("request_key" to JsonPrimitive(key))))
    }

    // Timeout/throttling and unknown outcomes retain the original intent for explicit retry.
    fun retain(status: Int, category: String): Boolean =
        status !in 400..499 || status in listOf(401, 408, 429) ||
            Regex("unknown|uncertain|unavailable").containsMatchIn(category)

    fun encode(pending: PendingWrite): String = wireJson.encodeToString(pending)

    @Throws(Exception::class)
    fun decode(payload: String): PendingWrite = wireJson.decodeFromString(payload)

    fun body(pending: PendingWrite): String = pending.body.toString()

    @Throws(Exception::class)
    fun checkoutBody(quote: String): String = wireJson.decodeFromString<Quote>(quote).checkoutBody().toString()
}
