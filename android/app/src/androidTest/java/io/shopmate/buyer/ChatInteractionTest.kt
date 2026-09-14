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
        chat = ChatState(conversationKey = "test-conversation", streaming = true, nextBefore = 31,
            messages = (0..29).map { ChatMessage(it.toLong() + 31, it % 2 == 0,
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

    @Test fun prependingVariableHeightHistoryKeepsClippedMessageAndStreamingText() {
        mount()
        compose.onNodeWithTag("chat-history").performTouchInput { swipeDown() }
        compose.onNodeWithTag("chat-history").performScrollToIndex(1)
        compose.onNodeWithTag("chat-history").performTouchInput {
            swipeUp(startY = centerY, endY = centerY - 70f, durationMillis = 400)
        }
        compose.waitForIdle()
        val anchor = compose.onNodeWithTag("chat-message-31")
        val before = anchor.fetchSemanticsNode().positionInRoot.y
        val viewport = compose.onNodeWithTag("chat-history").fetchSemanticsNode().boundsInRoot
        assertTrue("The anchored row must be partially clipped", before < viewport.top)
        compose.runOnIdle { chat = chat.copy(loadingEarlier = true) }
        compose.waitForIdle()
        assertEquals(before, anchor.fetchSemanticsNode().positionInRoot.y, 1f)
        compose.runOnIdle { chat = chat.copy(loadingEarlier = false, historyError = "暂时失败", historyErrorBefore = 31) }
        compose.waitForIdle()
        assertEquals(before, anchor.fetchSemanticsNode().positionInRoot.y, 1f)
        appendText()
        compose.runOnIdle {
            val earlier = (1..30).map { id -> ChatMessage(id.toLong(), id % 2 == 1,
                listOf(ChatSegment("旧消息 $id：" + "长短不同的历史内容。".repeat(id % 7 + 1)))) }
            chat = chat.copy(messages = earlier + chat.messages, nextBefore = null,
                loadingEarlier = false, historyError = null, historyErrorBefore = null)
        }
        compose.waitForIdle()
        assertEquals("Prepending must retain the message key and its pixel offset", before,
            anchor.fetchSemanticsNode().positionInRoot.y, 1f)
        appendText()
        assertEquals(before, anchor.fetchSemanticsNode().positionInRoot.y, 1f)
        compose.onNodeWithText("回到最新").performClick()
        compose.waitForIdle()
        compose.onNodeWithTag("chat-message-60").assertExists()
        compose.onNodeWithText("回到最新").assertDoesNotExist()
    }

    @Test fun olderPageFinishingWhileAbsentRestoresMessageIdentityAndPixelOffset() {
        mount()
        compose.onNodeWithTag("chat-history").performTouchInput { swipeDown() }
        compose.onNodeWithTag("chat-history").performScrollToIndex(1)
        compose.onNodeWithTag("chat-history").performTouchInput {
            swipeUp(startY = centerY, endY = centerY - 70f, durationMillis = 400)
        }
        compose.waitForIdle()
        val before = compose.onNodeWithTag("chat-message-31").fetchSemanticsNode().positionInRoot.y
        val viewport = compose.onNodeWithTag("chat-history").fetchSemanticsNode().boundsInRoot
        assertTrue("The anchored row must be partially clipped", before < viewport.top)
        compose.runOnIdle { chat = chat.copy(loadingEarlier = true) }
        compose.waitForIdle()
        compose.runOnIdle { visible = false }
        compose.waitForIdle()
        appendText()
        compose.runOnIdle {
            val earlier = (1..30).map { id -> ChatMessage(id.toLong(), id % 2 == 1,
                listOf(ChatSegment("旧消息 $id：" + "长短不同的历史内容。".repeat(id % 7 + 1)))) }
            chat = chat.copy(messages = earlier + chat.messages, nextBefore = null, loadingEarlier = false)
        }
        compose.waitForIdle()
        compose.runOnIdle { visible = true }
        compose.waitForIdle()
        compose.onNodeWithText("回到最新").assertIsDisplayed()
        assertEquals("A hidden prepend must preserve the same message and pixel offset", before,
            compose.onNodeWithTag("chat-message-31").fetchSemanticsNode().positionInRoot.y, 1f)
        appendText()
        assertEquals(before, compose.onNodeWithTag("chat-message-31").fetchSemanticsNode().positionInRoot.y, 1f)
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
