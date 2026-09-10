// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";
import { useState } from "react";
import {
  AttentionList,
  AttentionRow,
  Button,
  Notice,
  optionValuesLabel,
  Panel,
  Segmented,
  Skeleton,
  ViewLink,
  formatMoney,
  formatNumber,
} from "web-shared";
import {
  attentionItems,
  metricQuestion,
  type AttentionFilter,
} from "@/lib/merchant-overview";
import { INVENTORY_KINDS } from "@/lib/kinds";
import { windowLabel } from "@/lib/retail-format";
import type {
  InventoryAlert,
  OverviewMetric,
  OverviewResponse,
} from "@/lib/types";
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

function InventoryRow({
  alert,
  onAskAssistant,
}: {
  alert: InventoryAlert;
  onAskAssistant: (text: string) => void;
}) {
  const style = INVENTORY_KINDS[alert.kind];
  const low = alert.kind === "low_stock";
  const chosen = optionValuesLabel(alert);
  const name = `${alert.title}${chosen ? ` · ${chosen}` : ""}`;
  return (
    <AttentionRow
      icon={style.icon}
      tone={low && alert.stock === 0 ? "danger" : style.tone}
      title={name}
      meta={[
        style.label,
        `库存 ${alert.stock} 件`,
        alert.listing_id,
        alert.threshold != null && low ? `补货阈值 ${alert.threshold}` : null,
        alert.sales_last_30d != null
          ? `报告期近 30 日销量 ${alert.sales_last_30d}`
          : null,
      ]
        .filter(Boolean)
        .join(" · ")}
      note={
        <div className="space-y-1 text-xs text-(--ink-soft)">
          {alert.days_of_cover != null && (
            <p>预计库存覆盖 {alert.days_of_cover} 天</p>
          )}
          {alert.storefront_visible === false && <p>当前不可购买</p>}
        </div>
      }
      action={{
        label: low ? "准备补货" : "分析滞销",
        onClick: () =>
          onAskAssistant(
            low
              ? `读取 SKU ${alert.listing_id}（${name}）的实际库存和销量，准备合理补货草案，等我批准。`
              : `分析 SKU ${alert.listing_id}（${name}）的滞销情况，核对实际成本和价格后提出可审批的处理方案。`,
          ),
      }}
    />
  );
}

export default function HomeView({
  data,
  failed,
  error,
  onAskAssistant,
  onNavigate,
}: {
  data: OverviewResponse | null;
  failed: boolean;
  error?: string | null;
  onAskAssistant: (text: string) => void;
  onNavigate: (view: "orders" | "inventory" | "changes") => void;
}) {
  const [metricKey, setMetricKey] = useState<OverviewMetric>("sales");
  const [filter, setFilter] = useState<AttentionFilter>("all");
  if (!data)
    return failed ? (
      <Notice>{error ?? "经营数据暂时无法读取，请刷新重试。"}</Notice>
    ) : (
      <Skeleton className="h-72" />
    );
  const s = data.snapshot;
  const attention = data.needs_attention;
  const queue = attentionItems(attention, filter);
  const pending = attention.pending_changes;
  const askMetric = (label: string) =>
    onAskAssistant(metricQuestion(label, data));
  const orderCount = attention.order_issues.length;
  const stockCount = attention.low_stock.length;
  const slowCount = attention.slow_movers.length;
  const hidden = queue.slice(ROW_CAP);
  const target =
    filter === "orders" ||
    (filter === "all" && hidden.some((row) => row.kind === "issue"))
      ? "orders"
      : "inventory";
  return (
    <div className="ac-reveal flex flex-col gap-5">
      <p className="text-xs leading-relaxed text-(--ink-soft)">
        {windowLabel(data.window)} · {s.currency ?? "CNY"}
        <br />
        退款前已支付成交，按付款成功时间及历史成交价统计。点击任一指标，向助手预填对应的分析问题。
      </p>
      <div className="kpi-grid">
        {[
          {
            label: "已支付成交额",
            value: formatMoney(s.sales, s.currency ?? "CNY"),
            change: s.sales_change_pct,
            note: "按历史成交价 · 退款前",
          },
          {
            label: "成交订单",
            value: formatNumber(s.orders),
            change: s.orders_change_pct,
            note: "付款成功的 SKU 子单",
          },
          {
            label: "客单价",
            value:
              s.average_order_value == null
                ? "—"
                : formatMoney(s.average_order_value, s.currency ?? "CNY"),
            change: null,
            note:
              s.units == null
                ? "报告期间的每单成交额"
                : `成交件数 ${formatNumber(s.units)} 件`,
          },
          {
            label: "转化率",
            value:
              s.conversion_rate == null
                ? "未知"
                : `${s.conversion_rate.toFixed(2)}%`,
            change: s.conversion_change_pct,
            note:
              s.traffic == null
                ? "访问量暂未提供"
                : `全店访问 ${formatNumber(s.traffic)} 次`,
          },
        ].map((metric) => (
          <button
            className="kpi-card"
            key={metric.label}
            onClick={() => askMetric(metric.label)}
            aria-label={`分析${metric.label}的变化`}
          >
            <p>{metric.label}</p>
            <div className="kpi-value">
              <strong>{metric.value}</strong>
              {metric.change != null && (
                <span
                  style={{
                    color: metric.change >= 0 ? "var(--ok)" : "var(--danger)",
                  }}
                >
                  {metric.change >= 0 ? "+" : ""}
                  {metric.change.toFixed(1)}%
                </span>
              )}
            </div>
            <small>{metric.note}</small>
          </button>
        ))}
      </div>
      {s.note && (
        <details className="text-xs text-(--ink-soft)">
          <summary>指标口径</summary>
          <p className="mt-2">{s.note}</p>
        </details>
      )}
      <div className="overview-feature">
        <section className="trend-card">
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2>经营趋势</h2>
            <select
              aria-label="趋势指标"
              value={metricKey}
              onChange={(e) => setMetricKey(e.target.value as OverviewMetric)}
              className="rounded-lg border bg-(--ground) px-3 py-2 text-xs"
            >
              {TREND_METRICS.map((metric) => (
                <option value={metric.key} key={metric.key}>
                  {metric.label}
                </option>
              ))}
            </select>
          </div>
          <p className="text-xs text-(--ink-soft)">
            实线为当前期间，虚线为前期 ·{" "}
            {metricKey === "conversion"
              ? "%"
              : metricKey === "orders"
                ? "SKU 子单"
                : (s.currency ?? "CNY")}
          </p>
          <MetricTrend
            label={
              TREND_METRICS.find((metric) => metric.key === metricKey)!.label
            }
            points={data.trends[metricKey]}
            prior={data.trends_prior[metricKey]}
            window={data.window}
            priorWindow={data.prior_window}
            note={data.trend_notes[metricKey]}
            priorNote={data.trend_notes_prior[metricKey]}
          />
          <div className="mt-4 border-t pt-4">
            <ViewLink
              label="让助手解读变化"
              onClick={() =>
                askMetric(
                  TREND_METRICS.find((metric) => metric.key === metricKey)!
                    .label,
                )
              }
            />
          </div>
        </section>
        <section className="opportunity-panel">
          <h2>让下一步更有依据</h2>
          <p>从当前业务事实出发，分析后再准备提案。</p>
          <button
            className="opportunity-item"
            onClick={() =>
              onAskAssistant(
                "读取当前库存告警和真实销量，优先分析缺货或低库存商品，为需要补货的商品准备合理提案，等我批准。 ",
              )
            }
          >
            <strong>库存健康 · {stockCount} 个低库存 SKU</strong>
            <span>
              {stockCount
                ? `${attention.low_stock[0].title} · 当前库存 ${attention.low_stock[0].stock} 件`
                : "当前读取范围内暂无低库存告警"}
            </span>
            <small>分析库存 →</small>
          </button>
          <button
            className="opportunity-item"
            onClick={() =>
              onAskAssistant(
                "分析当前滞销商品的销量、库存、价格和成本，提出有依据的商品或营销方案，等我批准。 ",
              )
            }
          >
            <strong>商品经营 · {slowCount} 个滞销 SKU</strong>
            <span>
              {slowCount
                ? `${attention.slow_movers[0].title} · 库存 ${attention.slow_movers[0].stock} 件`
                : "结合历史成交，寻找可改进的商品"}
            </span>
            <small>分析商品 →</small>
          </button>
          <button
            className="opportunity-item"
            onClick={() => onNavigate("orders")}
          >
            <strong>
              订单与售后 · {orderCount}
              {attention.order_issues_may_have_more ? "+" : ""} 项待关注
            </strong>
            <span>核对订单、付款、履约和退款的实际状态。</span>
            <small>查看异常 →</small>
          </button>
        </section>
      </div>
      <div className="grid items-start gap-5 2xl:grid-cols-[minmax(0,1fr)_360px]">
        <Panel
          title="需要处理的事项"
          subtitle="库存与订单问题来自当前业务读取；经营分析仍使用上方报告期间。"
        >
          <div className="overflow-x-auto px-4 pb-3">
            <Segmented<AttentionFilter>
              label="筛选待办事项"
              value={filter}
              onChange={setFilter}
              options={[
                {
                  id: "all",
                  label: attention.order_issues_may_have_more
                    ? "全部（本次读取）"
                    : "全部",
                  count: orderCount + stockCount + slowCount,
                },
                {
                  id: "orders",
                  label: attention.order_issues_may_have_more
                    ? "订单问题（达上限）"
                    : "订单问题",
                  count: orderCount,
                },
                { id: "stock", label: "低库存", count: stockCount },
                { id: "slow", label: "滞销", count: slowCount },
              ]}
            />
          </div>
          <AttentionList>
            {queue
              .slice(0, ROW_CAP)
              .map((row) =>
                row.kind === "issue" ? (
                  <IssueRow
                    key={`issue:${row.issue.issue_id}`}
                    issue={row.issue}
                    onAskAssistant={onAskAssistant}
                  />
                ) : (
                  <InventoryRow
                    key={`${row.alert.kind}:${row.alert.listing_id}`}
                    alert={row.alert}
                    onAskAssistant={onAskAssistant}
                  />
                ),
              )}
          </AttentionList>
          {!queue.length && (
            <p className="p-4 text-sm text-(--ink-soft)">
              当前读取结果中没有此类待办。
            </p>
          )}
          {hidden.length > 0 && (
            <div className="flex flex-wrap items-center justify-between gap-2 border-t border-(--line) px-4 py-3 text-xs text-(--ink-soft)">
              <span>当前还有 {hidden.length} 条未展开</span>
              <ViewLink
                label={target === "orders" ? "查看订单与售后" : "查看库存健康"}
                onClick={() => onNavigate(target)}
              />
            </div>
          )}
          {attention.order_issues_may_have_more && (
            <p className="border-t border-(--line) p-4 text-xs text-(--ink-soft)">
              订单问题已达 {attention.order_issues_limit}{" "}
              条读取上限，可能还有未列出的记录。
            </p>
          )}
        </Panel>
        <Panel
          title="近期订单"
          subtitle="当前全店最近创建的 SKU 子单，金额为下单时的历史价格。"
          action={
            <ViewLink
              label="查看近期订单与售后"
              onClick={() => onNavigate("orders")}
            />
          }
        >
          <RecentOrders orders={data.recent_orders.slice(0, 4)} />
        </Panel>
      </div>
      <section className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-(--line) bg-(--card) p-5">
        <div>
          <h2 className="font-semibold">当前操作员的经营草案</h2>
          <p className="mt-1 text-sm text-(--ink-soft)">
            {pending.length
              ? `${pending.length} 份草案等待批准`
              : "暂无待批准草案"}{" "}
            · {data.recent_changes.length} 份近期草案记录
          </p>
        </div>
        <Button variant="primary" onClick={() => onNavigate("changes")}>
          查看草案与历史
        </Button>
      </section>
      <Panel title="继续追问">
        <div className="flex flex-wrap gap-2 p-4">
          {[
            "哪些商品贡献了成交额的变化？",
            "查看库存预警，哪些商品需要补货或处理滞销？",
            "分析营销计划的同期支出与归因收入，有哪些改进建议？",
          ].map((text) => (
            <Button
              key={text}
              variant="secondary"
              size="sm"
              onClick={() => onAskAssistant(text)}
            >
              {text}
            </Button>
          ))}
        </div>
      </Panel>
    </div>
  );
}
