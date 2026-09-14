package io.shopmate.buyer

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.*
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.input.nestedscroll.*
import androidx.compose.ui.platform.testTag
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.serialization.json.*

private data class ReadingAnchor(val key: Any, val offset: Int, val gesture: Long)

@Composable
fun ChatScreen(vm: BuyerViewModel, state: BuyerState) {
    val chat by vm.chat.collectAsStateWithLifecycle()
    ChatContent(vm, state, chat)
}

@Composable
fun ChatContent(vm: BuyerViewModel, state: BuyerState, chat: ChatState) {
    var history by remember { mutableStateOf(false) }
    val list = rememberSaveable(chat.conversationKey, saver = listSaver<LazyListState, Long>(
        save = { state ->
            val firstMessage = state.layoutInfo.visibleItemsInfo.firstOrNull {
                it.key.toString().startsWith("message:")
            }
            listOf(state.firstVisibleItemIndex.toLong(), state.firstVisibleItemScrollOffset.toLong(),
                firstMessage?.key.toString().removePrefix("message:").toLongOrNull() ?: 0L,
                firstMessage?.offset?.toLong() ?: 0L)
        },
        restore = { saved ->
            // An older page can finish while this screen is absent; its saved index is no longer an identity.
            val messageIndex = chat.messages.indexOfFirst { it.messageId == saved[2] }
            if (messageIndex >= 0) LazyListState(messageIndex + 1, -saved[3].toInt())
            else LazyListState(saved[0].toInt(), saved[1].toInt())
        },
    )) { LazyListState() }
    var following by rememberSaveable(chat.conversationKey) { mutableStateOf(true) }
    var gesture by remember(chat.conversationKey) { mutableLongStateOf(0) }
    var readingAnchor by remember(chat.conversationKey) { mutableStateOf<ReadingAnchor?>(null) }
    val requestEarlier by rememberUpdatedState(newValue = {
        if (chat.historyLoaded && !chat.loadingHistory && !chat.loadingEarlier && chat.nextBefore != null) {
            val visible = list.layoutInfo.visibleItemsInfo.firstOrNull { it.key.toString().startsWith("message:") }
            readingAnchor = visible?.let { ReadingAnchor(it.key, it.offset, gesture) }
            following = false
            vm.loadEarlierMessages()
        }
    })
    val currentHistoryError by rememberUpdatedState(chat.historyError)
    val scroll = remember(list) {
        object : NestedScrollConnection {
            override fun onPreScroll(available: Offset, source: NestedScrollSource): Offset {
                if (source == NestedScrollSource.UserInput && available.y != 0f) {
                    gesture++
                    if (available.y > 0) following = false
                }
                return Offset.Zero
            }
            override fun onPostScroll(consumed: Offset, available: Offset, source: NestedScrollSource): Offset {
                if (source == NestedScrollSource.UserInput && consumed.y < 0 && !list.canScrollForward)
                    following = true
                return Offset.Zero
            }
        }
    }
    LaunchedEffect(list, chat.conversationKey) {
        snapshotFlow { !following && !list.isScrollInProgress && list.firstVisibleItemIndex <= 1 }
            .collect { atStart -> if (atStart && currentHistoryError == null) requestEarlier() }
    }
    LaunchedEffect(chat.messages.firstOrNull()?.messageId) {
        val anchor = readingAnchor ?: return@LaunchedEffect
        readingAnchor = null
        // Stable keys preserve the viewport natively; an explicit offset also preserves a clipped first row.
        if (!following && gesture == anchor.gesture && !list.isScrollInProgress) {
            val index = chat.messages.indexOfFirst { "message:${it.messageId}" == anchor.key }
            if (index >= 0) list.scrollToItem(index + 1, -anchor.offset)
        }
    }
    Column(Modifier.fillMaxSize().imePadding()) {
        Row(
            Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 10.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Column(Modifier.weight(1f)) {
                Heading("购物助手")
                Note("选购有依据，操作有确认")
            }
            IconButton(
                onClick = {
                    vm.loadConversations()
                    history = true
                }
            ) {
                Icon(Icons.Outlined.History, "历史对话")
            }
            IconButton(onClick = vm::newChat, enabled = !chat.streaming) {
                Icon(Icons.Outlined.AddComment, "新对话")
            }
        }
        LazyColumn(
            Modifier.weight(1f).nestedScroll(scroll).testTag("chat-history"),
            state = list,
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            item(key = "history-control") {
                Box(Modifier.fillMaxWidth().height(56.dp), contentAlignment = Alignment.Center) {
                    when {
                        chat.loadingHistory || chat.loadingEarlier ->
                            CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                        chat.historyError != null -> TextButton(
                            onClick = { if (chat.historyErrorBefore != null) requestEarlier() else vm.restoreChat() },
                            modifier = Modifier.testTag("history-retry"),
                        ) { Text(if (chat.historyErrorBefore != null) "加载失败，重试更早消息" else "对话加载失败，重试") }
                        chat.nextBefore != null -> TextButton(onClick = requestEarlier,
                            modifier = Modifier.testTag("history-earlier")) { Text("查看更早消息") }
                        chat.messages.isNotEmpty() -> Note("已到对话开头")
                    }
                }
            }
            if (chat.messages.isEmpty() && chat.historyLoaded)
                item(key = "welcome") {
                    Sheet(Modifier.fillMaxWidth()) {
                        Text("最近想给生活添点什么？", fontSize = 23.sp, fontWeight = FontWeight.Bold)
                        Note("告诉我预算、人数和使用场景，我可以查商品、比较规格，再帮你规划装备。")
                        listOf("预算2000元，配置家庭咖啡角", "帮我比较两款咖啡机", "查询我的订单和售后政策").forEach { text ->
                            OutlinedButton(
                                onClick = { vm.draft(text) },
                                modifier = Modifier.fillMaxWidth(),
                            ) {
                                Text(text)
                            }
                        }
                    }
                }
            items(chat.messages, key = { "message:${it.messageId}" }) { message ->
                if (message.user)
                    Row(Modifier.fillMaxWidth().testTag("chat-message-${message.messageId}"), horizontalArrangement = Arrangement.End) {
                        Text(
                            message.segments.joinToString("") { it.text },
                            Modifier.widthIn(max = 500.dp)
                                .background(Line, RoundedCornerShape(20.dp))
                                .padding(16.dp),
                        )
                    }
                else
                    Column(
                        Modifier.fillMaxWidth().testTag("chat-message-${message.messageId}"),
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        Text(
                            "SHOPMATE",
                            color = Vermilion,
                            fontSize = 11.sp,
                            fontWeight = FontWeight.Bold,
                            letterSpacing = 2.sp,
                        )
                        message.segments.forEach { segment ->
                            if (segment.block == null) SelectionContainerCompat(segment.text)
                            else AgentCard(segment, vm, state)
                        }
                        if (message.pending && !chat.streaming) Note("这段回复尚未完成，可稍后从服务端恢复。")
                        message.suggestions.forEach { suggestion ->
                            SuggestionChip(
                                onClick = { vm.draft(suggestion) },
                                label = { Text(suggestion) },
                                enabled = !chat.streaming,
                            )
                        }
                    }
            }
            item(key = "latest") {
                if (chat.streaming) {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                        Note(chat.activity.ifBlank { "助手正在整理回答…" })
                    }
                } else if (chat.messages.isNotEmpty()) {
                    TextButton(
                        onClick = {
                            vm.restoreChat()
                            vm.refreshCart()
                            vm.refreshOrders()
                        }
                    ) { Text("从服务端恢复对话与操作结果") }
                }
            }
        }
        LaunchedEffect(chat.messages, chat.streaming, following) {
            if (following && chat.messages.isNotEmpty()) {
                // One fixed history header precedes messages; the actual footer follows the growing reply.
                list.requestScrollToItem(chat.messages.size + 1)
            }
        }
        if (!following) {
            TextButton(onClick = { following = true }, modifier = Modifier.align(Alignment.CenterHorizontally)) {
                Icon(Icons.Outlined.ArrowDownward, null, Modifier.size(16.dp))
                Text("回到最新")
            }
        }
        Row(
            Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surface).padding(12.dp),
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedTextField(
                chat.draft,
                vm::draft,
                modifier = Modifier.weight(1f),
                placeholder = { Text("说说你想买什么…") },
                maxLines = 4,
                shape = RoundedCornerShape(18.dp),
            )
            FilledIconButton(
                onClick = if (chat.streaming) vm::stopChat else vm::send,
                enabled = chat.streaming || (chat.historyLoaded && !chat.loadingHistory && chat.draft.isNotBlank()),
                modifier = Modifier.size(52.dp),
            ) {
                Icon(
                    if (chat.streaming) Icons.Outlined.Stop else Icons.Outlined.ArrowUpward,
                    if (chat.streaming) "停止生成" else "发送",
                )
            }
        }
    }
    if (history)
        AlertDialog(
            onDismissRequest = { history = false },
            title = { Text("历史对话") },
            text = {
                LazyColumn {
                    items(chat.conversations) { conversation ->
                        TextButton(
                            onClick = {
                                history = false
                                vm.selectChat(conversation.id)
                            },
                            enabled = !chat.streaming,
                        ) {
                            Text(conversation.label)
                        }
                    }
                }
            },
            confirmButton = { TextButton(onClick = { history = false }) { Text("关闭") } },
        )
}

@Composable
private fun SelectionContainerCompat(text: String) {
    androidx.compose.foundation.text.selection.SelectionContainer { Text(text, lineHeight = 25.sp) }
}

@Composable
private fun AgentCard(segment: ChatSegment, vm: BuyerViewModel, state: BuyerState) {
    val block = segment.block ?: return
    val payload = block.obj("payload")
    val component = block.text("component")
    Sheet(Modifier.fillMaxWidth()) {
        val title =
            payload.text(
                "title",
                when (component) {
                    "comparison" -> "商品比较"
                    "products" -> "为你找到"
                    "plan" -> "装备方案"
                    "checkout" -> "核对购物车"
                    "order_status" -> "订单进度"
                    "refund_confirmation" -> "退款申请"
                    "web_sources" -> "网页参考来源"
                    else -> "选购参考"
                },
            )
        Text(title, fontSize = 19.sp, fontWeight = FontWeight.Bold)
        if (!segment.final) Note("正在整理，完成后可操作")
        when (component) {
            "products" ->
                payload.rows("items").forEach { row ->
                    CardProduct(row.obj("product"), row.text("reason"), segment.final, vm, state)
                }
            "comparison" -> {
                payload.rows("entries").forEach { entry ->
                    CardProduct(
                        entry.obj("product"),
                        entry.text("best_for"),
                        segment.final,
                        vm,
                        state,
                    )
                    listOf("pros" to "优点", "cons" to "取舍").forEach { (key, label) ->
                        (entry[key] as? JsonArray)
                            ?.map { it.jsonPrimitive.content }
                            ?.takeIf { it.isNotEmpty() }
                            ?.let { Note("$label：${it.joinToString("；")}") }
                    }
                    HorizontalDivider(color = Line)
                }
            }
            "plan" -> {
                if (payload.text("intro").isNotBlank()) Text(payload.text("intro"))
                payload.rows("steps").forEachIndexed { index, step ->
                    Text("${index + 1}. ${step.text("label")}", fontWeight = FontWeight.SemiBold)
                    if (step.text("detail").isNotBlank()) Note(step.text("detail"))
                    step.rows("products").forEach { CardProduct(it, "", segment.final, vm, state) }
                }
            }
            "guide" -> {
                payload.rows("sections").forEach {
                    Text(it.text("heading"), fontWeight = FontWeight.SemiBold)
                    Text(it.text("body"))
                }
                payload.rows("related_products").forEach {
                    CardProduct(it, "", segment.final, vm, state)
                }
            }
            "checkout" -> {
                Text(payload.text("note", "请到购物车核对当前商品、数量与金额，再确认创建订单。"))
                Button(onClick = { vm.navigate("购物车") }, enabled = segment.final) { Text("核对购物车") }
            }
            "refund_confirmation" -> {
                val action = payload.obj("action")
                Text("订单 ${action.text("orderId")}")
                Text(
                    money(action.number("amountMinor"), action.text("currency", "CNY")),
                    color = Vermilion,
                )
                Note("请读取当前申请后确认；退款受理不代表资金到账。")
                Button(onClick = { vm.navigate("订单") }, enabled = segment.final) { Text("核对退款申请") }
            }
            "order_status" -> {
                Text(payload.text("summary"))
                if (payload.text("next_step").isNotEmpty()) Note(payload.text("next_step"))
                TextButton(onClick = { vm.navigate("订单") }) { Text("查看实际订单状态") }
            }
            "web_sources" -> {
                val context = LocalContext.current
                if (payload.text("summary").isNotEmpty()) Text(payload.text("summary"))
                (payload.rows("citations") + payload.rows("consulted_sources"))
                    .distinctBy { it.text("url") }
                    .forEach { source ->
                        val url = source.text("url")
                        val uri = Uri.parse(url)
                        TextButton(
                            onClick = { context.startActivity(Intent(Intent.ACTION_VIEW, uri)) },
                            enabled =
                                segment.final &&
                                    uri.scheme in listOf("https", "http") &&
                                    !uri.host.isNullOrBlank(),
                        ) {
                            Text(source.text("title", url))
                        }
                    }
                Note("外部网页仅供参考，库存、价格与订单以商店业务数据为准。")
            }
            else -> Note("此结果请结合助手文字说明查看；操作状态可在购物车或订单中核对。")
        }
    }
}

@Composable
private fun CardProduct(
    raw: JsonObject,
    reason: String,
    final: Boolean,
    vm: BuyerViewModel,
    state: BuyerState,
) {
    if (raw.text("product_id").isEmpty() || raw["price"] == null || raw.text("title").isEmpty())
        return
    val product = wireJson.decodeFromJsonElement<Product>(raw)
    Text(product.title, fontWeight = FontWeight.SemiBold)
    Text(decimalMoney(product.price, product.currency), color = Vermilion)
    if (reason.isNotEmpty()) Note(reason)
    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        TextButton(onClick = { vm.openProduct(product.product_id) }, enabled = final) {
            Text("查看规格")
        }
        if (product.options.isEmpty())
            OutlinedButton(
                onClick = { vm.add(product) },
                enabled = final && product.in_stock && !state.writing,
            ) {
                Text("加入购物车")
            }
    }
}
