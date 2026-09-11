package io.shopmate.buyer

import kotlinx.serialization.Serializable
import kotlinx.serialization.json.*

val wireJson = Json { ignoreUnknownKeys = true }

fun JsonObject.text(key: String, default: String = "") =
    (get(key) as? JsonPrimitive)?.contentOrNull ?: default

fun JsonObject.obj(key: String) = get(key) as? JsonObject ?: JsonObject(emptyMap())

fun JsonObject.rows(key: String) =
    (get(key) as? JsonArray)?.mapNotNull { it as? JsonObject } ?: emptyList()

fun JsonObject.number(key: String) = (get(key) as? JsonPrimitive)?.longOrNull

fun jsonBody(vararg pairs: Pair<String, JsonElement>) = JsonObject(mapOf(*pairs))

@Serializable
data class Product(
    val product_id: String,
    val title: String,
    val price: Double,
    val currency: String = "CNY",
    val brand: String? = null,
    val image_url: String? = null,
    val in_stock: Boolean = true,
    val short_description: String? = null,
    val long_description: String? = null,
    val option_values: Map<String, String> = emptyMap(),
    val options: Map<String, List<String>> = emptyMap(),
    val specs: Map<String, String> = emptyMap(),
    val variants: List<Product> = emptyList(),
    val labels: List<String> = emptyList(),
    val category: String? = null,
)

@Serializable data class ProductsPage(val products: List<Product>, val next_offset: Int? = null)

@Serializable
data class QuoteItem(
    val productId: String,
    val quantity: Int,
    val name: String,
    val unitPriceMinor: Long,
    val currency: String,
    val productVersion: Long,
    val lineTotalMinor: Long?,
    val orderable: Boolean,
    val imageUrl: String? = null,
    val optionValues: Map<String, String> = emptyMap(),
)

@Serializable
data class Quote(
    val version: Long,
    val currency: String?,
    val subtotalMinor: Long?,
    val checkoutReady: Boolean,
    val items: List<QuoteItem>,
) {
    @Throws(Exception::class)
    fun checkoutBody(): JsonObject {
        require(
            checkoutReady &&
                items.isNotEmpty() &&
                currency != null &&
                subtotalMinor != null &&
                subtotalMinor > 0
        ) {
            "请刷新报价并处理缺货商品"
        }
        require(
            items.all {
                it.orderable &&
                    it.currency == currency &&
                    it.quantity in 1..24 &&
                    it.unitPriceMinor > 0 &&
                    it.productVersion > 0
            }
        ) {
            "商品报价已失效"
        }
        return buildJsonObject {
            put("expectedCartVersion", version)
            put("currency", currency)
            putJsonArray("items") {
                items.forEach { item ->
                    add(
                        buildJsonObject {
                            put("productId", item.productId)
                            put("quantity", item.quantity)
                            put("expectedProductVersion", item.productVersion)
                            put("expectedUnitPriceMinor", item.unitPriceMinor)
                        }
                    )
                }
            }
        }
    }
}

@Serializable data class PendingWrite(val key: String, val path: String, val body: JsonObject)

data class StreamEvent(val type: String, val data: JsonObject) {
    val payload: String get() = data.toString()
}

data class ChatSegment(
    val text: String = "",
    val block: JsonObject? = null,
    val slot: String = "",
    val final: Boolean = true,
) {
    // Avoid exporting nested JsonObject collections just to ask Swift whether a card exists.
    val hasBlock: Boolean get() = block != null
    val blockJson: String? get() = block?.toString()
}

data class ChatMessage(
    val user: Boolean,
    val segments: List<ChatSegment>,
    val suggestions: List<String> = emptyList(),
)

data class Conversation(val id: String, val label: String)

fun statusLabel(raw: String): String =
    when (raw) {
        "UNPAID" -> "待付款"
        "PAID",
        "SUCCEEDED" -> "已付款"
        "PARTIALLY_PAID" -> "部分已付款"
        "CANCELLED" -> "已取消"
        "PREPARED" -> "待确认"
        "CONSUMED" -> "已提交"
        "REQUESTED" -> "已受理"
        "PACKED" -> "已打包"
        "SHIPPED" -> "已发货"
        "DELIVERED" -> "已送达"
        else -> raw
    }

