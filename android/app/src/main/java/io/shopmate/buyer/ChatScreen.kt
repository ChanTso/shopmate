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
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import kotlinx.serialization.json.*

@Composable
fun ChatScreen(vm: BuyerViewModel, state: BuyerState) {
    var history by remember { mutableStateOf(false) }
    val list = rememberLazyListState()
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
            IconButton(onClick = vm::newChat, enabled = !state.streaming) {
                Icon(Icons.Outlined.AddComment, "新对话")
            }
        }
        LazyColumn(
            Modifier.weight(1f),
            state = list,
            contentPadding = PaddingValues(16.dp),
            verticalArrangement = Arrangement.spacedBy(14.dp),
        ) {
            if (state.messages.isEmpty())
                item {
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
            itemsIndexed(state.messages) { _, message ->
                if (message.user)
                    Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                        Text(
                            message.segments.joinToString("") { it.text },
                            Modifier.widthIn(max = 500.dp)
                                .background(Line, RoundedCornerShape(20.dp))
                                .padding(16.dp),
                        )
                    }
                else
                    Column(
                        Modifier.fillMaxWidth(),
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
                        message.suggestions.forEach { suggestion ->
                            SuggestionChip(
                                onClick = { vm.draft(suggestion) },
                                label = { Text(suggestion) },
                                enabled = !state.streaming,
                            )
                        }
                    }
            }
            if (state.streaming)
                item {
                    Row(
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(10.dp),
                    ) {
                        CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp)
                        Note(state.activity.ifBlank { "助手正在整理回答…" })
                    }
                }
            if (state.messages.isNotEmpty() && !state.streaming)
                item {
                    TextButton(
                        onClick = {
                            vm.restoreChat()
                            vm.refreshCart()
                            vm.refreshOrders()
                        }
                    ) {
                        Text("从服务端恢复对话与操作结果")
                    }
                }
        }
        LaunchedEffect(state.messages.size) {
            if (list.layoutInfo.totalItemsCount > 0)
                list.animateScrollToItem(list.layoutInfo.totalItemsCount - 1)
        }
        Row(
            Modifier.fillMaxWidth().background(MaterialTheme.colorScheme.surface).padding(12.dp),
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            OutlinedTextField(
                state.draft,
                vm::draft,
                modifier = Modifier.weight(1f),
                placeholder = { Text("说说你想买什么…") },
                maxLines = 4,
                shape = RoundedCornerShape(18.dp),
            )
            FilledIconButton(
                onClick = if (state.streaming) vm::stopChat else vm::send,
                enabled = state.streaming || state.draft.isNotBlank(),
                modifier = Modifier.size(52.dp),
            ) {
                Icon(
                    if (state.streaming) Icons.Outlined.Stop else Icons.Outlined.ArrowUpward,
                    if (state.streaming) "停止生成" else "发送",
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
                    items(state.conversations) { conversation ->
                        TextButton(
                            onClick = {
                                history = false
                                vm.selectChat(conversation.id)
                            },
                            enabled = !state.streaming,
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
