package io.shopmate.buyer

import android.app.Application
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveableStateHolder
import androidx.compose.ui.semantics.SemanticsProperties
import androidx.compose.ui.test.*
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import kotlinx.coroutines.cancel
import org.junit.After
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

class ChatInteractionTest {
    @get:Rule val compose = createComposeRule()
    private lateinit var vm: BuyerViewModel
    private var chat by mutableStateOf(ChatState())
    private var visible by mutableStateOf(true)

    private fun mount() {
        val app = InstrumentationRegistry.getInstrumentation().targetContext.applicationContext as Application
        vm = BuyerViewModel(app)
        chat = ChatState(conversationKey = "test-conversation", streaming = true,
            messages = (0..29).map { ChatMessage(it % 2 == 0,
                listOf(ChatSegment("消息 $it：" + "这是一段用于检查阅读位置的会话内容。".repeat(12)))) })
        compose.setContent {
            MaterialTheme {
                val holder = rememberSaveableStateHolder()
                if (visible) holder.SaveableStateProvider("assistant") {
                    ChatContent(vm, BuyerState(), chat)
                }
            }
        }
        compose.waitForIdle()
    }

    private fun offset(): Float = compose.onNodeWithTag("chat-history")
        .fetchSemanticsNode().config[SemanticsProperties.VerticalScrollAxisRange].value()

    private fun appendText() {
        compose.runOnIdle {
            val last = chat.messages.last()
            chat = chat.copy(messages = chat.messages.dropLast(1) + last.copy(
                segments = listOf(ChatSegment(last.segments.single().text + "新增流式内容。".repeat(100)))))
        }
        compose.waitForIdle()
    }

    @After fun stop() { if (::vm.isInitialized) vm.viewModelScope.cancel() }

    @Test fun growingReplyFollowsUntilReaderScrollsAway() {
        mount()
        val beforeGrowth = offset()
        appendText()
        assertTrue("Growing reply should stay at the latest content", offset() > beforeGrowth)
        compose.onNodeWithTag("chat-history").performTouchInput { swipeDown() }
        compose.onNodeWithText("回到最新").assertIsDisplayed()
        val reading = offset()
        appendText()
        assertEquals("New deltas must not move the historical reading position", reading, offset(), 1f)
        compose.onNodeWithText("回到最新").performClick()
        compose.waitForIdle()
        assertTrue(offset() > reading)
    }

    @Test fun leavingAndReturningKeepsHistoricalReadingPosition() {
        mount()
        compose.onNodeWithTag("chat-history").performTouchInput { swipeDown() }
        compose.onNodeWithText("回到最新").assertIsDisplayed()
        val reading = offset()
        compose.runOnIdle { visible = false }
        compose.waitForIdle()
        appendText()
        compose.runOnIdle { visible = true }
        compose.waitForIdle()
        compose.onNodeWithText("回到最新").assertIsDisplayed()
        assertEquals(reading, offset(), 1f)
    }
}
