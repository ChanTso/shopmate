package io.shopmate.buyer

import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.*

@Serializable
data class SeckillTicket(
    val key: String,
    val activityId: String,
    val activityVersion: Long,
    val reservationId: String? = null,
    val state: String = "UNKNOWN",
    val decision: String = "",
    val orderId: String? = null,
) {
    val terminal: Boolean get() = state in setOf("ORDERED", "REJECTED", "CANCELLED", "UNFULFILLED")
    fun result(reply: JsonObject) = copy(
        reservationId = reply.text("reservationId").ifBlank { reservationId },
        state = reply.text("state"), decision = reply.text("decisionCode"),
        orderId = reply.text("orderId").ifBlank { null },
    )
}

@Composable
fun SeckillScreen(vm: BuyerViewModel, state: BuyerState, confirm: (String, () -> Unit) -> Unit) {
    LaunchedEffect(Unit) { vm.loadSeckill() }
    LazyColumn(contentPadding = PaddingValues(18.dp), verticalArrangement = Arrangement.spacedBy(16.dp)) {
        item {
            Heading("限量发售")
            Note("先预约，再等待成单。只有订单生成后才可核对付款；未付款订单会按期限取消。")
            TextButton(onClick = { vm.loadSeckill() }) { Text("刷新活动与预约") }
        }
        if (state.offers.isEmpty()) item { Note("当前没有可展示的活动") }
        items(state.offers, key = { it.text("activityId") }) { offer ->
            Sheet(Modifier.fillMaxWidth()) {
                Heading(offer.text("name"))
                Text(money(offer.number("unitPriceMinor"), offer.text("currency")), color = Vermilion)
                Note("开始 ${offer.text("startsAt")}\n结束 ${offer.text("endsAt")}")
                val existing = state.tickets.lastOrNull { it.activityId == offer.text("activityId") }
                Button(enabled = !state.writing, onClick = {
                    if (existing != null) vm.retrySeckill(existing)
                    else confirm("确认预约 ${offer.text("name")} × 1？活动报价为 ${money(offer.number("unitPriceMinor"), offer.text("currency"))}，最终付款请核对生成的订单。") { vm.reserve(offer) }
                }) { Text(if (existing == null) "确认预约一件" else "查询原预约") }
            }
        }
        item { Heading("我的预约") }
        items(state.tickets, key = { it.key }) { ticket ->
            Sheet(Modifier.fillMaxWidth()) {
                Text(when (ticket.state) {
                    "ORDERED" -> "已成单，请前往订单核对付款状态"
                    "ADMITTED", "PENDING" -> "已接收，正在排队成单"
                    "REJECTED" -> "本次预约未获准"
                    "CANCELLED" -> "预约已取消"
                    "UNFULFILLED" -> "本次预约未能成单"
                    else -> "结果尚未确认，请查询原预约"
                })
                Note("预约尾号 ${(ticket.reservationId ?: ticket.key).takeLast(8)}")
                if (ticket.state == "REJECTED") Note(when (ticket.decision) {
                    "EXHAUSTED" -> "活动配额已售罄"
                    "DUPLICATE_USER" -> "每位顾客限购一次，请查看原订单"
                    "NOT_OPEN" -> "活动尚未开始"
                    "EXPIRED", "ACTIVITY_INACTIVE" -> "活动已结束或暂不可用"
                    "STALE_VERSION" -> "活动已更新，请刷新后核对"
                    else -> "当前条件不满足，请核对活动状态"
                })
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    TextButton(enabled = !state.writing, onClick = { vm.retrySeckill(ticket) }) { Text("查询原预约") }
                    if (ticket.orderId != null) Button(onClick = { vm.navigate("订单") }) { Text("查看订单") }
                }
            }
        }
    }
}
