// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";
import { useState } from "react";
import { AttentionList, AttentionRow, Button, Notice, optionValuesLabel, PageHeader, Panel, Segmented, Skeleton, StatStrip, StatTile, ViewLink, formatMoney, formatNumber } from "web-shared";
import { attentionItems, metricQuestion, type AttentionFilter } from "@/lib/merchant-overview";
import { INVENTORY_KINDS } from "@/lib/kinds";
import { windowLabel } from "@/lib/retail-format";
import type { InventoryAlert, OverviewMetric, OverviewResponse } from "@/lib/types";
import IssueRow from "./IssueRow";
import MetricTrend from "./MetricTrend";
import RecentOrders from "./RecentOrders";

const ROW_CAP = 6;
const TREND_METRICS: { key: OverviewMetric; label: string }[] = [
  { key: "sales", label: "已支付成交额" },
  { key: "orders", label: "成交订单" },
  { key: "conversion", label: "转化率" },
  { key: "average_order_value", label: "客单价" },
];

function InventoryRow({ alert, onAskAssistant }: { alert: InventoryAlert; onAskAssistant: (text: string) => void }) {
  const style = INVENTORY_KINDS[alert.kind];
  const low = alert.kind === "low_stock";
  const chosen = optionValuesLabel(alert);
  const name = `${alert.title}${chosen ? ` · ${chosen}` : ""}`;
  return <AttentionRow icon={style.icon} tone={low && alert.stock === 0 ? "danger" : style.tone} title={name} meta={[style.label, `库存 ${alert.stock} 件`, alert.listing_id, alert.threshold != null && low ? `补货阈值 ${alert.threshold}` : null, alert.sales_last_30d != null ? `报告期近 30 日销量 ${alert.sales_last_30d}` : null].filter(Boolean).join(" · ")} note={<div className="space-y-1 text-xs text-(--ink-soft)">{alert.days_of_cover != null && <p>预计库存覆盖 {alert.days_of_cover} 天</p>}{alert.storefront_visible === false && <p>当前不可购买</p>}</div>} action={{ label: low ? "准备补货" : "分析滞销", onClick: () => onAskAssistant(low ? `读取 SKU ${alert.listing_id}（${name}）的实际库存和销量，准备合理补货草案，等我批准。` : `分析 SKU ${alert.listing_id}（${name}）的滞销情况，核对实际成本和价格后提出可审批的处理方案。`) }} />;
}

export default function HomeView({ data, failed, error, onAskAssistant, onNavigate }: { data: OverviewResponse | null; failed: boolean; error?: string | null; onAskAssistant: (text: string) => void; onNavigate: (view: "orders" | "inventory" | "changes") => void }) {
  const [filter, setFilter] = useState<AttentionFilter>("all");
  if (!data) return failed ? <Notice>{error ?? "经营数据暂时无法读取，请刷新重试。"}</Notice> : <Skeleton className="h-72" />;
  const s = data.snapshot;
  const attention = data.needs_attention;
  const queue = attentionItems(attention, filter);
  const pending = attention.pending_changes;
  const askMetric = (label: string) => onAskAssistant(metricQuestion(label, data));
  const orderCount = attention.order_issues.length;
  const stockCount = attention.low_stock.length;
  const slowCount = attention.slow_movers.length;
  const hidden = queue.slice(ROW_CAP);
  const target = filter === "orders" || (filter === "all" && hidden.some(row => row.kind === "issue")) ? "orders" : "inventory";
  return <div className="ac-reveal flex flex-col gap-5">
    <PageHeader title="经营概览" subtitle="从成交事实出发，先分析，再行动。"><Button variant="secondary" icon="spark" onClick={() => askMetric("成交额、流量与转化的经营变化")}>分析经营变化</Button></PageHeader>
    <p className="text-xs leading-relaxed text-(--ink-soft)">{windowLabel(data.window)} · {s.currency ?? "CNY"}<br />退款前已支付成交，按付款成功时间及历史成交价统计。点击任一指标，向助手预填对应的分析问题。</p>
    <Panel><StatStrip>
      <StatTile label="已支付成交额" value={formatMoney(s.sales, s.currency ?? "CNY")} changePct={s.sales_change_pct} onClick={() => askMetric("已支付成交额")} ariaLabel="分析已支付成交额的变化" />
      <StatTile label="成交订单" value={formatNumber(s.orders)} changePct={s.orders_change_pct} onClick={() => askMetric("成交订单（付款 SKU 子单数）")} ariaLabel="分析成交订单的变化" />
      <StatTile label="成交件数" value={s.units == null ? "暂未提供" : formatNumber(s.units)} onClick={() => askMetric("成交件数")} ariaLabel="分析成交件数的变化" />
      <StatTile label="客单价" value={s.average_order_value == null ? "—" : formatMoney(s.average_order_value, s.currency ?? "CNY")} onClick={() => askMetric("客单价")} ariaLabel="分析客单价的变化" />
      <StatTile label="访问量" value={s.traffic == null ? "未知" : formatNumber(s.traffic)} changePct={s.traffic_change_pct} onClick={() => askMetric("访问量")} ariaLabel="分析访问量的变化" />
      <StatTile label="转化率" value={s.conversion_rate == null ? "未知" : `${s.conversion_rate.toFixed(2)}%`} changePct={s.conversion_change_pct} onClick={() => askMetric("转化率（付款子单数 / 全店访问次数）")} ariaLabel="分析转化率的变化" />
    </StatStrip></Panel>
    {s.note && <p className="text-xs text-(--ink-soft)">{s.note}</p>}
    <Panel title="每日经营趋势" subtitle="实线：当前期间 · 虚线：前一期间；按各自窗口的第几日对齐，未返回数值的日期留空。"><div className="grid gap-5 p-5 md:grid-cols-2">{TREND_METRICS.map(metric => <section key={metric.key} className="min-w-0"><div className="mb-2 flex items-center justify-between gap-2"><h2 className="text-sm font-semibold">{metric.label}{["sales", "average_order_value"].includes(metric.key) ? `（${s.currency ?? "CNY"}）` : metric.key === "conversion" ? "（%）" : "（子单）"}</h2><ViewLink label="分析变化" onClick={() => askMetric(metric.label)} /></div><MetricTrend label={metric.label} points={data.trends[metric.key]} prior={data.trends_prior[metric.key]} window={data.window} priorWindow={data.prior_window} note={data.trend_notes[metric.key]} priorNote={data.trend_notes_prior[metric.key]} /></section>)}</div></Panel>
    <div className="grid items-start gap-5 2xl:grid-cols-[minmax(0,1fr)_360px]">
      <Panel title="需要处理的事项" subtitle="库存与订单问题来自当前业务读取；经营分析仍使用上方报告期间。">
        <div className="overflow-x-auto px-4 pb-3"><Segmented<AttentionFilter> label="筛选待办事项" value={filter} onChange={setFilter} options={[
          { id: "all", label: attention.order_issues_may_have_more ? "全部（本次读取）" : "全部", count: orderCount + stockCount + slowCount },
          { id: "orders", label: attention.order_issues_may_have_more ? "订单问题（达上限）" : "订单问题", count: orderCount },
          { id: "stock", label: "低库存", count: stockCount },
          { id: "slow", label: "滞销", count: slowCount },
        ]} /></div>
        <AttentionList>{queue.slice(0, ROW_CAP).map(row => row.kind === "issue" ? <IssueRow key={`issue:${row.issue.issue_id}`} issue={row.issue} onAskAssistant={onAskAssistant} /> : <InventoryRow key={`${row.alert.kind}:${row.alert.listing_id}`} alert={row.alert} onAskAssistant={onAskAssistant} />)}</AttentionList>
        {!queue.length && <p className="p-4 text-sm text-(--ink-soft)">当前读取结果中没有此类待办。</p>}
        {hidden.length > 0 && <div className="flex flex-wrap items-center justify-between gap-2 border-t border-(--line) px-4 py-3 text-xs text-(--ink-soft)"><span>当前还有 {hidden.length} 条未展开</span><ViewLink label={target === "orders" ? "查看订单与售后" : "查看库存健康"} onClick={() => onNavigate(target)} /></div>}
        {attention.order_issues_may_have_more && <p className="border-t border-(--line) p-4 text-xs text-(--ink-soft)">订单问题已达 {attention.order_issues_limit} 条读取上限，可能还有未列出的记录。</p>}
      </Panel>
      <Panel title="近期订单" subtitle="当前全店最近创建的 SKU 子单，金额为下单时的历史价格。" action={<ViewLink label="查看近期订单与售后" onClick={() => onNavigate("orders")} />}><RecentOrders orders={data.recent_orders.slice(0, 4)} /></Panel>
    </div>
    <section className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-(--line) bg-(--card) p-5"><div><h2 className="font-semibold">本会话的经营草案</h2><p className="mt-1 text-sm text-(--ink-soft)">{pending.length ? `${pending.length} 份草案等待批准` : "暂无待批准草案"} · {data.recent_changes.length} 份近期草案记录</p></div><Button variant="primary" onClick={() => onNavigate("changes")}>查看草案与历史</Button></section>
    <Panel title="继续追问"><div className="flex flex-wrap gap-2 p-4">{["哪些商品贡献了成交额的变化？", "查看库存预警，哪些商品需要补货或处理滞销？", "分析营销计划的同期支出与归因收入，有哪些改进建议？"].map(text => <Button key={text} variant="secondary" size="sm" onClick={() => onAskAssistant(text)}>{text}</Button>)}</div></Panel>
  </div>;
}
