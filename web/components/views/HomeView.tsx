// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";
import { Button, Notice, PageHeader, Panel, Skeleton, Sparkline, StatStrip, StatTile, formatMoney, formatNumber } from "web-shared";
import { windowLabel } from "@/lib/retail-format";
import type { OverviewResponse } from "@/lib/types";

export default function HomeView({ data, failed, error, onAskAssistant, onReview }: { data: OverviewResponse | null; failed: boolean; error?: string | null; onAskAssistant: (text: string) => void; onReview: () => void }) {
  if (!data) return failed ? <Notice>{error ?? "经营数据暂时无法读取，请刷新重试。"}</Notice> : <Skeleton className="h-72" />;
  const s = data.snapshot;
  const pending = data.needs_attention.pending_changes;
  const [start, end] = s.period.split("/");
  const period = end ? windowLabel({ start, end, timeZone: "Asia/Shanghai" }) : s.period;
  return <div className="ac-reveal flex flex-col gap-5">
    <PageHeader title="经营概览" subtitle="从成交事实出发，先分析，再行动。"><Button variant="secondary" icon="spark" onClick={() => onAskAssistant("分析当前报告期间的 CNY 成交、流量与转化，相比前一期间说明主要变化和贡献商品。")}>分析经营变化</Button></PageHeader>
    <p className="text-xs leading-relaxed text-(--ink-soft)">{period} · {s.currency ?? "CNY"}<br />退款前已支付成交，按付款成功时间及历史成交价统计。</p>
    <Panel><StatStrip>
      <StatTile label="已支付成交额" value={formatMoney(s.sales, s.currency ?? "CNY")} changePct={s.sales_change_pct} />
      <StatTile label="成交订单" value={formatNumber(s.orders)} changePct={s.orders_change_pct} />
      <StatTile label="成交件数" value={s.units == null ? "暂未提供" : formatNumber(s.units)} />
      <StatTile label="客单价" value={s.average_order_value == null ? "—" : formatMoney(s.average_order_value, s.currency ?? "CNY")} />
      <StatTile label="访问量" value={s.traffic == null ? "未知" : formatNumber(s.traffic)} changePct={s.traffic_change_pct} />
      <StatTile label="转化率" value={s.conversion_rate == null ? "未知" : `${s.conversion_rate.toFixed(2)}%`} changePct={s.conversion_change_pct} />
    </StatStrip></Panel>
    {s.note && <p className="text-xs text-(--ink-soft)">{s.note}</p>}
    {data.trends?.sales?.length ? <Panel title="成交额趋势" subtitle="实线：当前期间 · 虚线：前一期间"><div className="p-5"><Sparkline points={data.trends.sales.map(p => p.value)} prior={data.trends_prior?.sales?.map(p => p.value)} label="当前与前期每日成交额" height={130} /><div className="mt-3 flex justify-between text-xs text-(--ink-soft)"><span>{data.trends.sales[0]?.date}</span><span>{data.trends.sales.at(-1)?.date}</span></div></div></Panel> : null}
    <section className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-(--line) bg-(--card) p-5"><div><h2 className="font-semibold">本会话的经营草案</h2><p className="mt-1 text-sm text-(--ink-soft)">{pending.length ? `${pending.length} 份草案等待批准` : "暂无待批准草案"} · {data.recent_changes.length} 份草案记录</p></div><Button variant="primary" onClick={onReview}>查看草案与历史</Button></section>
    <Panel title="继续追问"><div className="flex flex-wrap gap-2 p-4">{["哪些商品贡献了成交额的变化？", "查看库存预警，哪些商品需要补货或处理滞销？", "分析营销计划的同期支出与归因收入，有哪些改进建议？"].map(text => <Button key={text} variant="secondary" size="sm" onClick={() => onAskAssistant(text)}>{text}</Button>)}</div></Panel>
  </div>;
}
