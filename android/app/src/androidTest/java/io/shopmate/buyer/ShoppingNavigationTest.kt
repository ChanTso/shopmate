package io.shopmate.buyer

import androidx.activity.ComponentActivity
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createAndroidComposeRule
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.cancel
import kotlinx.serialization.json.*
import org.junit.After
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class ShoppingNavigationTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()
    private lateinit var vm: BuyerViewModel

    private fun mount() {
        compose.runOnUiThread { vm = BuyerViewModel(ShoppingApi(), ShoppingStorage()) }
        compose.setContent { androidx.compose.material3.MaterialTheme { BuyerApp(vm) } }
        compose.waitForIdle()
    }

    private fun offset() = compose.onNodeWithTag("catalog-list").fetchSemanticsNode()
        .config[SemanticsProperties.VerticalScrollAxisRange].value()

    @After fun close() { if (::vm.isInitialized) vm.viewModelScope.cancel() }

    @Test fun catalogReadingPositionSurvivesTabAndBack() {
        mount()
        compose.onNodeWithTag("catalog-list").performScrollToNode(hasText("商品 40"))
        val reading = offset()
        assertTrue(reading > 0)
        compose.onNodeWithText("购物车", useUnmergedTree = true).performClick()
        compose.waitForIdle()
        compose.runOnUiThread { compose.activity.onBackPressedDispatcher.onBackPressed() }
        compose.waitForIdle()
        assertEquals("首页", vm.state.value.screen)
        assertEquals(reading, offset(), 1f)
    }

    @Test fun selectedVariantSurvivesAssistantAndReturnsToCatalogPosition() {
        mount()
        compose.onNodeWithTag("catalog-list").performScrollToNode(hasText("商品 40"))
        val reading = offset()
        compose.onNodeWithText("商品 40").performClick()
        compose.onNodeWithTag("variant-red").performScrollTo().performClick()
        compose.onNodeWithText("就这件问助手").performScrollTo().performClick()
        compose.waitForIdle()
        assertEquals("助手", vm.state.value.screen)
        compose.onNodeWithText("返回刚才的商品").performClick()
        compose.onNodeWithTag("variant-red").performScrollTo().assertIsSelected()
        compose.runOnUiThread { compose.activity.onBackPressedDispatcher.onBackPressed() }
        compose.waitForIdle()
        assertFalse(vm.state.value.productOpen)
        assertEquals(reading, offset(), 1f)
    }
}

private class ShoppingApi : BuyerApi() {
    override suspend fun json(path: String, body: JsonObject?, method: String): JsonObject = when {
        path.startsWith("/products?") -> buildJsonObject {
            put("products", wireJson.encodeToJsonElement(kotlinx.serialization.builtins.ListSerializer(Product.serializer()),
                (0..59).map { Product("p$it", "商品 $it", 10.0) }))
        }
        path.startsWith("/products/") -> buildJsonObject {
            put("product", wireJson.encodeToJsonElement(Product.serializer(),
                Product("p40", "商品 40", 10.0, variants = listOf(
                    Product("red", "红色款", 10.0, option_values = mapOf("颜色" to "红")),
                    Product("white", "白色款", 10.0, option_values = mapOf("颜色" to "白"))))))
        }
        path == "/cart" -> buildJsonObject {
            put("quote", wireJson.encodeToJsonElement(Quote.serializer(), Quote(1, "CNY", 0, false, emptyList())))
        }
        else -> JsonObject(emptyMap())
    }
}

private class ShoppingStorage : BuyerStorage {
    override var endpoint = "https://shopmate.test"
    override var commerceEndpoint = "https://commerce.test"
    override val owner = "test-buyer"
    override var conversation: String? = null
    override fun token() = "test-token"
    override fun login(owner: String, token: String) { }
    override fun logout() { }
    override fun tickets() = emptyList<SeckillTicket>()
    override fun saveTickets(values: List<SeckillTicket>) { }
    override fun pending() = emptyList<PendingWrite>()
    override fun savePending(values: List<PendingWrite>) { }
}
