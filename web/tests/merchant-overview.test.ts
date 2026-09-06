import assert from "node:assert/strict";
import test from "node:test";
import { attentionItems, dailySlots, metricQuestion, orderFactLabels, trendRuns } from "../lib/merchant-overview.ts";
import { minorMoney } from "../lib/buyer-checkout.ts";
import type { OrderFacts } from "../lib/buyer-types.ts";
import type { OverviewResponse, ReportingWindow } from "../lib/types.ts";

const window: ReportingWindow = { start: "2026-09-01T16:00:00+00:00", end: "2026-09-04T16:00:00+00:00", timeZone: "Asia/Shanghai" };
const priorWindow = { ...window, start: "2026-08-29T16:00:00Z", end: window.start };

test("daily graphs use Shanghai dates and preserve unknown days without inferring zero", () => {
  const slots = dailySlots([{ date: "2026-09-02", value: 0 }, { date: "2026-09-04", value: 12 }, { date: "2026-09-05", value: 999 }], window);
  assert.deepEqual(slots, [{ date: "2026-09-02", value: 0 }, { date: "2026-09-03", value: null }, { date: "2026-09-04", value: 12 }]);
  assert.deepEqual(dailySlots([], window).map(point => point.value), [null, null, null]);
  assert.deepEqual(dailySlots([{ date: "2026-09-02", value: Number.NaN }], window).map(point => point.value), [null, null, null]);
});

test("line segments break at missing dates and keep each window's original relative day", () => {
  const current = trendRuns(dailySlots([{ date: "2026-09-02", value: 8 }, { date: "2026-09-04", value: 10 }], window));
  assert.deepEqual(current.map(run => run.map(point => point.index)), [[0], [2]]);
  const previous = trendRuns(dailySlots([{ date: "2026-08-31", value: 3 }, { date: "2026-09-01", value: 4 }], priorWindow));
  assert.deepEqual(previous.map(run => run.map(point => point.index)), [[1, 2]]);
  assert.deepEqual(trendRuns(dailySlots([], priorWindow)), []);
});

test("a partial end day stays in the graph while midnight remains exclusive", () => {
  const partial = { ...window, end: "2026-09-04T17:00:00Z" };
  assert.equal(dailySlots([], partial).at(-1)?.date, "2026-09-05");
  assert.equal(dailySlots([], window).at(-1)?.date, "2026-09-04");
});

test("all three attention groups remain available and sorting does not mutate the response", () => {
  const low = [{ listing_id: "stock", title: "库存", kind: "low_stock" as const, stock: 2, days_of_cover: 1 }, { listing_id: "empty", title: "缺货", kind: "low_stock" as const, stock: 0 }];
  const attention: OverviewResponse["needs_attention"] = { low_stock: low, slow_movers: [{ listing_id: "slow", title: "滞销", kind: "slow_mover", stock: 80 }], order_issues: [{ issue_id: "i1", order_id: "o1", kind: "buyer_message", summary: "买家留言" }], pending_changes: [], order_issues_limit: 100, order_issues_may_have_more: false };
  const rows = attentionItems(attention, "all");
  assert.equal(rows.length, 4);
  assert.deepEqual(rows.map(row => row.kind === "issue" ? row.issue.issue_id : row.alert.listing_id), ["empty", "i1", "stock", "slow"]);
  assert.deepEqual(low.map(row => row.listing_id), ["stock", "empty"]);
  assert.equal(attentionItems(attention, "orders")[0].kind, "issue");
  assert.equal(attentionItems(attention, "stock").length, 2);
  assert.equal(attentionItems(attention, "slow").length, 1);
});

const order: OrderFacts = { orderKind: "STANDARD", orderId: "order-1", status: "UNPAID", stateVersion: 1, createdAt: "2026-09-07T00:00:00Z", unpaidDeadline: null, product: { productId: "sku-1", name: "桌灯", unitPriceMinor: 1999, totalPriceMinor: 3998, quantity: 2, currency: "CNY", productVersion: 3 }, payment: null, refunds: { reservedAmountMinor: 0, byState: [] }, fulfillment: null };

test("order, payment, fulfillment and refund labels remain independent facts", () => {
  assert.deepEqual(orderFactLabels(order), { order: "未付款", payment: "暂无付款记录", fulfillment: "暂无履约记录", refunds: "暂无退款记录" });
  const failed = { attemptId: "pay-1", state: "FAILED", amountMinor: 3998, refundedAmountMinor: 0, currency: "CNY", succeededAt: null };
  assert.equal(orderFactLabels({ ...order, payment: failed }).payment, "付款失败");
  assert.equal(orderFactLabels({ ...order, payment: failed }).order, "未付款");
  const paid = { ...order, status: "PAID", payment: { ...failed, state: "SUCCEEDED", succeededAt: order.createdAt }, refunds: { reservedAmountMinor: 1000, byState: [{ state: "REQUESTED", count: 1, requestedAmountMinor: 1000, refundedAmountMinor: 0 }] } };
  assert.equal(orderFactLabels(paid).fulfillment, "暂无履约记录");
  assert.equal(orderFactLabels(paid).refunds, "申请已受理 1 笔");
  const delivered = { ...paid, fulfillment: { method: "delivery", stage: "DELIVERED", promisedDeliveryAt: null, estimatedDeliveryAt: null, packedAt: null, shippedAt: null, deliveredAt: order.createdAt, delayReason: null, sourceKind: "LOCAL_FIXTURE", sourceRef: "case1", observedAt: order.createdAt } };
  assert.equal(orderFactLabels(delivered).fulfillment, "已送达");
  assert.equal(orderFactLabels(delivered).refunds, "申请已受理 1 笔");
});

test("recent order amounts use the historical integer minor total and explicit currency", () => {
  assert.match(minorMoney(order.product.totalPriceMinor, order.product.currency), /[¥￥]39\.98/);
  assert.match(minorMoney(order.product.totalPriceMinor, "USD"), /\$39\.98/);
  assert.equal(minorMoney(39.98, "CNY"), "金额待确认");
  assert.equal(minorMoney(Number.MAX_SAFE_INTEGER + 1, "CNY"), "金额待确认");
});

test("named KPI prompts preserve both explicit reporting windows and missingness", () => {
  const prompt = metricQuestion("转化率", { window, prior_window: priorWindow, snapshot: { period: "ignored-relative", sales: 12, orders: 3, currency: "CNY" } });
  assert.match(prompt, /转化率/);
  assert.match(prompt, /2026年9月2日/);
  assert.match(prompt, /2026年8月30日/);
  assert.match(prompt, /缺失不能当零/);
  assert.match(prompt, /付款 SKU 子单/);
  assert.doesNotMatch(prompt, /ignored-relative/);
});
