import type { OrderFacts } from "@/lib/buyer-types";
import { minorMoney } from "@/lib/buyer-checkout";
import { orderFactLabels, refundStateLabel } from "@/lib/merchant-overview";
import { localDateTime } from "@/lib/retail-format";

export default function RecentOrders({ orders }: { orders: OrderFacts[] }) {
  if (!orders.length) return <p className="p-4 text-sm text-(--ink-soft)">当前没有可读取的订单。</p>;
  return <ul className="divide-y divide-(--line)">{orders.map(order => {
    const labels = orderFactLabels(order);
    const fulfillment = order.fulfillment;
    const currency = order.product.currency;
    return <li key={`${order.orderKind}:${order.orderId}`} className="space-y-3 p-4">
      <div className="flex flex-wrap items-start justify-between gap-2"><div className="min-w-0 flex-1"><h3 className="text-sm font-semibold">{order.product.name} × {order.product.quantity}</h3><p className="mt-1 break-all text-xs text-(--ink-soft)">{order.orderId} · {order.orderKind}</p><p className="break-all text-xs text-(--ink-soft)">SKU {order.product.productId}</p></div><strong className="whitespace-nowrap text-sm tabular-nums">{minorMoney(order.product.totalPriceMinor, currency)} <span className="text-xs font-normal">{currency}</span></strong></div>
      <p className="text-xs text-(--ink-soft)">下单 {localDateTime(order.createdAt)}</p>
      <div className="grid gap-x-3 gap-y-1 text-xs sm:grid-cols-2"><p>订单：{labels.order}</p><p>付款：{labels.payment}</p><p>履约：{labels.fulfillment}</p><p>退款：{labels.refunds}</p></div>
      {fulfillment?.delayReason && <p className="text-xs text-(--warn)">履约延迟说明：{fulfillment.delayReason}</p>}
      <details className="text-xs"><summary className="cursor-pointer font-medium text-(--ink-2)">查看交易与履约事实</summary><div className="mt-3 space-y-3 rounded-lg bg-(--ground) p-3">
        <div><p>历史单价 {minorMoney(order.product.unitPriceMinor, currency)} · 数量 {order.product.quantity} · 商品版本 {order.product.productVersion ?? "未提供"}</p>{order.unpaidDeadline && <p>待付款截止 {localDateTime(order.unpaidDeadline)}</p>}</div>
        {order.payment ? <div><p>付款金额 {minorMoney(order.payment.amountMinor, order.payment.currency)}</p>{order.payment.succeededAt && <p>付款成功 {localDateTime(order.payment.succeededAt)}</p>}</div> : <p>尚无付款尝试记录。</p>}
        {fulfillment ? <div className="space-y-1"><p>履约方式：{fulfillment.method}</p><p>承诺送达 {localDateTime(fulfillment.promisedDeliveryAt)}</p><p>预计送达 {localDateTime(fulfillment.estimatedDeliveryAt)}</p>{fulfillment.packedAt && <p>打包 {localDateTime(fulfillment.packedAt)}</p>}{fulfillment.shippedAt && <p>发货 {localDateTime(fulfillment.shippedAt)}</p>}{fulfillment.deliveredAt && <p>实际送达 {localDateTime(fulfillment.deliveredAt)}</p>}<p>观察 {localDateTime(fulfillment.observedAt)}</p><p className="break-all text-(--ink-soft)">来源：{fulfillment.sourceKind} · {fulfillment.sourceRef}</p></div> : <p>暂无履约记录，付款成功不表示已经发货。</p>}
        {!!order.refunds.byState.length && <div className="space-y-1"><p>退款预留 {minorMoney(order.refunds.reservedAmountMinor, currency)}</p>{order.refunds.byState.map(row => <p key={row.state}>{refundStateLabel(row.state)} · {row.count} 笔 · 申请 {minorMoney(row.requestedAmountMinor, currency)} · 已退 {minorMoney(row.refundedAmountMinor, currency)}</p>)}<p className="text-(--ink-soft)">退款申请或预留不表示退款已经到账。</p></div>}
      </div></details>
    </li>;
  })}</ul>;
}
