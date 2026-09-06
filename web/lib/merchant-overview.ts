import type { OrderFacts } from "./buyer-types.ts";
import type { InventoryAlert, MetricPoint, OrderIssue, OverviewResponse, ReportingWindow } from "./types.ts";
import { windowLabel } from "./retail-format.ts";

export interface DayValue { date: string; value: number | null; }
export type AttentionFilter = "all" | "orders" | "stock" | "slow";
export type AttentionItem = { kind: "issue"; issue: OrderIssue } | { kind: "inventory"; alert: InventoryAlert };

function localDay(instant: number, timeZone: string): string {
  const parts = new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).formatToParts(instant);
  const value = (kind: string) => parts.find(part => part.type === kind)!.value;
  return `${value("year")}-${value("month")}-${value("day")}`;
}

/** An absent daily observation is a gap, including days with no paid-order bucket. */
export function dailySlots(points: readonly MetricPoint[], window: ReportingWindow): DayValue[] {
  const first = Date.parse(`${localDay(Date.parse(window.start), window.timeZone)}T00:00:00Z`);
  const last = Date.parse(`${localDay(Date.parse(window.end) - 1, window.timeZone)}T00:00:00Z`);
  const values = new Map(points.map(point => [point.date, point.value]));
  const slots: DayValue[] = [];
  for (let day = first; day <= last; day += 86_400_000) {
    const date = new Date(day).toISOString().slice(0, 10);
    const value = values.get(date);
    slots.push({ date, value: value != null && Number.isFinite(value) ? value : null });
  }
  return slots;
}

/** Keep the original day index when splitting lines around unknown values. */
export function trendRuns(slots: readonly DayValue[]): { index: number; date: string; value: number }[][] {
  const runs: { index: number; date: string; value: number }[][] = [];
  let current: { index: number; date: string; value: number }[] = [];
  slots.forEach((point, index) => {
    if (point.value === null) { current = []; return; }
    if (!current.length) runs.push(current);
    current.push({ ...point, index, value: point.value });
  });
  return runs;
}

export function attentionItems(attention: OverviewResponse["needs_attention"], filter: AttentionFilter): AttentionItem[] {
  const issues = attention.order_issues.map(issue => ({ kind: "issue" as const, issue }));
  const low = [...attention.low_stock]
    .sort((a, b) => Number(b.stock === 0) - Number(a.stock === 0) || (a.days_of_cover ?? Infinity) - (b.days_of_cover ?? Infinity))
    .map(alert => ({ kind: "inventory" as const, alert }));
  const slow = attention.slow_movers.map(alert => ({ kind: "inventory" as const, alert }));
  if (filter === "orders") return issues;
  if (filter === "stock") return low;
  if (filter === "slow") return slow;
  return [...low.slice(0, 1), ...issues, ...low.slice(1), ...slow];
}

export function metricQuestion(label: string, data: Pick<OverviewResponse, "window" | "prior_window" | "snapshot">): string {
  return `分析“${label}”：当前报告期间为 ${windowLabel(data.window)}，对照期间为 ${windowLabel(data.prior_window)}，币种 ${data.snapshot.currency ?? "CNY"}。读取该指标的实际数据，解释变化与可核对的贡献；未知或缺失不能当零。成交订单指付款 SKU 子单，转化分母是全店访问次数。`;
}

const ORDER_LABELS: Record<string, string> = { UNPAID: "未付款", PAID: "已付款", CANCELLED: "已取消" };
const PAYMENT_LABELS: Record<string, string> = { PENDING: "付款待处理", SUCCEEDED: "付款成功", FAILED: "付款失败" };
const FULFILLMENT_LABELS: Record<string, string> = { PROCESSING: "处理中", PACKED: "已打包", SHIPPED: "已发货", OUT_FOR_DELIVERY: "配送中", DELIVERED: "已送达" };
const REFUND_LABELS: Record<string, string> = { REQUESTED: "申请已受理", PROCESSING: "退款处理中", SUCCEEDED: "退款成功", FAILED: "退款失败" };

export function refundStateLabel(state: string): string { return REFUND_LABELS[state] ?? state; }
export function orderFactLabels(order: OrderFacts) {
  return {
    order: ORDER_LABELS[order.status] ?? order.status,
    payment: order.payment ? PAYMENT_LABELS[order.payment.state] ?? order.payment.state : "暂无付款记录",
    fulfillment: order.fulfillment ? FULFILLMENT_LABELS[order.fulfillment.stage] ?? order.fulfillment.stage : "暂无履约记录",
    refunds: order.refunds.byState.length ? order.refunds.byState.map(row => `${refundStateLabel(row.state)} ${row.count} 笔`).join("；") : "暂无退款记录",
  };
}
