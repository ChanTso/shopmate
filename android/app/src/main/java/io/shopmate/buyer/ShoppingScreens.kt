package io.shopmate.buyer

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.*
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import java.math.BigDecimal
import kotlinx.serialization.json.*

@Composable
fun CartScreen(vm: BuyerViewModel, state: BuyerState, confirm: (String, () -> Unit) -> Unit) {
    val quote = state.quote
    LazyColumn(
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            Heading("把期待装进行囊")
            Note("购物车 · 商品价格与库存以确认时为准")
        }
        if (quote == null) item { Text("正在读取购物车…") }
        else {
            if (quote.items.isEmpty())
                item {
                    Sheet(Modifier.fillMaxWidth()) {
                        Text("购物车还是空的")
                        Button(onClick = { vm.navigate("首页") }) { Text("去发现好物") }
                    }
                }
            items(quote.items, key = { it.productId }) { item ->
                Sheet(Modifier.fillMaxWidth()) {
                    Text(item.name, fontWeight = FontWeight.SemiBold)
                    if (item.optionValues.isNotEmpty())
                        Note(item.optionValues.values.joinToString(" / "))
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            money(item.lineTotalMinor, item.currency),
                            Modifier.weight(1f),
                            color = Vermilion,
                            fontSize = 20.sp,
                            fontWeight = FontWeight.Bold,
                        )
                        IconButton(
                            onClick = { vm.setQuantity(item, item.quantity - 1) },
                            enabled = !state.writing,
                        ) {
                            Icon(Icons.Outlined.Remove, "减少数量")
                        }
                        Text(item.quantity.toString())
                        IconButton(
                            onClick = { vm.setQuantity(item, item.quantity + 1) },
                            enabled = !state.writing && item.quantity < 24,
                        ) {
                            Icon(Icons.Outlined.Add, "增加数量")
                        }
                    }
                    if (!item.orderable) Text("当前不可下单，请调整购物车", color = Vermilion)
                }
            }
            if (quote.items.isNotEmpty())
                item {
                    Sheet(Modifier.fillMaxWidth()) {
                        Heading("确认商品报价")
                        Row(
                            Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween,
                        ) {
                            Text("商品合计")
                            Text(
                                money(quote.subtotalMinor, quote.currency),
                                fontWeight = FontWeight.Bold,
                            )
                        }
                        Note("不含配送估算费用。创建订单后，还需要你单独确认模拟付款。")
                        Button(
                            onClick = {
                                val summary =
                                    quote.items.joinToString("\n") {
                                        "${it.name} × ${it.quantity} · ${money(it.lineTotalMinor, it.currency)}"
                                    }
                                confirm(
                                    summary +
                                        "\n\n合计 ${money(quote.subtotalMinor, quote.currency)}。确认创建订单？"
                                ) {
                                    vm.checkout(quote)
                                    vm.navigate("订单")
                                }
                            },
                            enabled = quote.checkoutReady && !state.writing,
                            modifier = Modifier.fillMaxWidth(),
                        ) {
                            Text("核对并创建订单")
                        }
                        TextButton(onClick = vm::delivery, enabled = !state.writing) {
                            Text("查看配送估算")
                        }
                        state.delivery.obj("estimate").rows("options").forEach { option ->
                            Text(
                                listOf(
                                        option.text("method"),
                                        option.text("earliestDate"),
                                        option.text("latestDate"),
                                        money(
                                            option.number("feeMinor"),
                                            state.delivery.obj("estimate").text("currency", "CNY"),
                                        ),
                                    )
                                    .filter { it.isNotBlank() }
                                    .joinToString(" · ")
                            )
                        }
                        if (state.delivery.isNotEmpty()) Note("配送选项仅为估算，不代表已发货或已收取运费。")
                    }
                }
        }
    }
}

@Composable
fun OrdersScreen(vm: BuyerViewModel, state: BuyerState, confirm: (String, () -> Unit) -> Unit) {
    var refundOrder by remember { mutableStateOf<JsonObject?>(null) }
    var amount by rememberSaveable { mutableStateOf("") }
    LazyColumn(
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            Heading("订单与售后")
            Note("付款、退款及履约状态来自商店业务系统")
        }
        if (state.pending.isNotEmpty())
            item {
                Sheet(Modifier.fillMaxWidth()) {
                    Text("有操作尚未收到确定结果", color = Vermilion, fontWeight = FontWeight.Bold)
                    Note("先刷新核对；重试会使用原请求，避免重复创建。")
                    state.pending.forEach { pending ->
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text(pending.path, Modifier.weight(1f), fontSize = 12.sp)
                            OutlinedButton(
                                onClick = { vm.retry(pending) },
                                enabled = !state.writing,
                            ) {
                                Text("恢复原操作")
                            }
                        }
                    }
                }
            }
        items(state.checkouts, key = { it.text("checkoutId") }) { checkout ->
            Sheet(Modifier.fillMaxWidth()) {
                Text(
                    "结账 · ${statusLabel(checkout.text("paymentStatus"))}",
                    fontWeight = FontWeight.Bold,
                )
                Text(
                    money(checkout.number("totalMinor"), checkout.text("currency")),
                    color = Vermilion,
                    fontSize = 22.sp,
                )
                checkout.rows("orders").forEach {
                    Text(
                        it.obj("product").text("name") + " × " + it.obj("product").text("quantity")
                    )
                }
                Note("结账单尾号 ${checkout.text("checkoutId").takeLast(8)}")
                if (checkout.text("paymentStatus") != "PAID")
                    Button(
                        onClick = {
                            confirm(
                                "确认模拟支付 ${money(checkout.number("totalMinor"), checkout.text("currency"))}？演示支付不会扣取真实资金。"
                            ) {
                                vm.transact("/checkouts/${checkout.text("checkoutId")}/pay")
                            }
                        },
                        enabled = !state.writing,
                    ) {
                        Text("确认模拟付款")
                    }
            }
        }
        items(state.actions, key = { it.obj("action").text("pendingActionId") }) { row ->
            Sheet(Modifier.fillMaxWidth()) {
                val action = row.obj("action")
                val receipt = row.obj("receipt")
                Text(if (receipt.isEmpty()) "退款申请待核对" else "退款申请已受理", fontWeight = FontWeight.Bold)
                Text(
                    money(action.number("amountMinor"), action.text("currency")),
                    color = Vermilion,
                )
                Note("订单尾号 ${action.text("orderId").takeLast(8)}")
                if (receipt.isEmpty()) {
                    Note(
                        "状态 ${statusLabel(action.text("state"))} · 有效期至 ${localTime(action.text("expiresAt"))}"
                    )
                    Button(
                        onClick = {
                            confirm(
                                "订单尾号 ${action.text("orderId").takeLast(8)}\n退款金额 ${money(action.number("amountMinor"), action.text("currency"))}\n确认提交退款申请？"
                            ) {
                                vm.transact("/actions/${action.text("pendingActionId")}/confirm")
                            }
                        },
                        enabled = !state.writing,
                    ) {
                        Text("核对并确认退款")
                    }
                } else Note("受理不代表资金到账 · 回执尾号 ${receipt.text("receiptId").takeLast(8)}")
            }
        }
        item { Heading("最近订单") }
        if (state.orders.isEmpty()) item { Note("暂无订单，去挑选喜欢的装备吧。") }
        items(state.orders, key = { it.text("orderId") }) { order ->
            Sheet(Modifier.fillMaxWidth()) {
                val product = order.obj("product")
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(
                        statusLabel(order.text("status")),
                        color = Vermilion,
                        fontWeight = FontWeight.Bold,
                    )
                    Note(order.text("createdAt").take(10))
                }
                Text(product.text("name"), fontWeight = FontWeight.SemiBold)
                Text(
                    "数量 ${product.text("quantity")} · ${money(product.number("totalPriceMinor"), product.text("currency"))}"
                )
                val fulfillment = order.obj("fulfillment")
                if (fulfillment.isNotEmpty()) {
                    Text("履约进度：${statusLabel(fulfillment.text("stage"))}")
                    if (fulfillment.text("estimatedDeliveryAt").isNotEmpty())
                        Note("预计送达 ${fulfillment.text("estimatedDeliveryAt")}")
                    if (fulfillment.text("delayReason").isNotEmpty())
                        Note(fulfillment.text("delayReason"))
                } else Note("暂未提供履约信息")
                Note("订单尾号 ${order.text("orderId").takeLast(8)}")
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(
                        onClick = {
                            vm.navigate("助手")
                            vm.draft("查询订单 ${order.text("orderId")} 的状态和售后政策")
                        }
                    ) {
                        Text("问问助手")
                    }
                    if (order.obj("payment").text("state") == "SUCCEEDED")
                        OutlinedButton(
                            onClick = {
                                refundOrder = order
                                val available =
                                    (order.obj("payment").number("amountMinor") ?: 0) -
                                        (order.obj("refunds").number("reservedAmountMinor") ?: 0)
                                amount =
                                    BigDecimal.valueOf(available.coerceAtLeast(0), 2)
                                        .toPlainString()
                            },
                            enabled = !state.writing,
                        ) {
                            Text("申请售后")
                        }
                }
            }
        }
        if (state.commands.any { it.text("state") == "unknown" })
            item {
                Sheet(Modifier.fillMaxWidth()) {
                    Text("服务端待恢复操作", fontWeight = FontWeight.Bold)
                    state.commands
                        .filter { it.text("state") == "unknown" }
                        .forEach { command ->
                            Note("${command.text("kind")} · ${command.text("request_key")}")
                            TextButton(
                                onClick = {
                                    val path =
                                        when (command.text("kind")) {
                                            "checkout" -> "/checkouts/retry"
                                            "refund" -> "/actions/retry"
                                            else -> "/commands/retry"
                                        }
                                    vm.retry(
                                        PendingWrite(
                                            command.text("request_key"),
                                            path,
                                            buildJsonObject {
                                                put("request_key", command.text("request_key"))
                                            },
                                        )
                                    )
                                },
                                enabled = !state.writing,
                            ) {
                                Text("查询并恢复原操作")
                            }
                        }
                }
            }
    }
    refundOrder?.let { order ->
        AlertDialog(
            onDismissRequest = { refundOrder = null },
            title = { Heading("准备退款申请") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text(order.obj("product").text("name"))
                    OutlinedTextField(
                        amount,
                        { amount = it },
                        label = { Text("退款金额（元）") },
                        singleLine = true,
                    )
                    Note("先准备申请，核对后再确认提交。可退额度由业务系统再次校验。")
                }
            },
            confirmButton = {
                Button(
                    onClick = {
                        refundOrder = null
                        vm.refund(order, amount)
                    }
                ) {
                    Text("准备申请")
                }
            },
            dismissButton = { TextButton(onClick = { refundOrder = null }) { Text("取消") } },
        )
    }
}

@Composable
fun ProfileScreen(vm: BuyerViewModel, state: BuyerState) {
    var policy by rememberSaveable { mutableStateOf("退款") }
    var edit by remember { mutableStateOf<JsonObject?>(null) }
    var value by rememberSaveable { mutableStateOf("") }
    LazyColumn(
        contentPadding = PaddingValues(20.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        item {
            Heading(state.profile.text("display_name", "我的商店"))
            Note(state.profile.text("default_location", "欢迎来到 ShopMate"))
        }
        item {
            Sheet(Modifier.fillMaxWidth()) {
                Heading("助手记忆")
                Note("你可以修改或删除购物偏好。商品价格、订单和权限始终以业务系统为准。")
            }
        }
        if (state.memories.isEmpty()) item { Note("尚未记录长期偏好，可以在对话中告诉助手。") }
        items(state.memories, key = { it.text("key") }) { fact ->
            Sheet(Modifier.fillMaxWidth()) {
                Text(fact.text("value"))
                Note(fact.text("category"))
                Row {
                    TextButton(
                        onClick = {
                            edit = fact
                            value = fact.text("value")
                        }
                    ) {
                        Text("修改")
                    }
                    TextButton(onClick = { vm.editMemory(fact.text("key"), "", true) }) {
                        Text("删除")
                    }
                }
            }
        }
        item {
            Heading("订单与购物政策")
            Row(verticalAlignment = Alignment.CenterVertically) {
                OutlinedTextField(policy, { policy = it }, Modifier.weight(1f), singleLine = true)
                IconButton(onClick = { vm.policy(policy) }) { Icon(Icons.Outlined.Search, "查政策") }
            }
        }
        items(state.policies) { item ->
            Sheet(Modifier.fillMaxWidth()) {
                Text(item.text("title"), fontWeight = FontWeight.Bold)
                Text(item.text("content"))
            }
        }
        item {
            OutlinedButton(onClick = vm::logout, modifier = Modifier.fillMaxWidth()) {
                Text("退出登录")
            }
        }
    }
    edit?.let { fact ->
        AlertDialog(
            onDismissRequest = { edit = null },
            title = { Text("修改购物偏好") },
            text = { OutlinedTextField(value, { value = it }) },
            confirmButton = {
                Button(
                    onClick = {
                        vm.editMemory(fact.text("key"), value)
                        edit = null
                    }
                ) {
                    Text("保存")
                }
            },
            dismissButton = { TextButton(onClick = { edit = null }) { Text("取消") } },
        )
    }
}
