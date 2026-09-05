// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

import { ChangeChip, formatMoney, formatNumber, formatPeriodLabel, formatRate, GenCard, GenCardHeader, Sparkline, titleCase } from "web-shared";
import type { MetricEntry, MetricsPayload } from "@/lib/types";

const CURRENCY_METRICS = new Set(["sales", "average_order_value", "revenue", "spend"]);
const RATE_METRICS = new Set(["conversion_rate", "return_rate", "click_through_rate"]);

function metricLabel(metric: string): string {
  if (metric === "average_order_value") return "客单价";
  return ({ sales: "成交额", revenue: "成交额", orders: "成交订单", units: "成交件数" } as Record<string, string>)[metric] ?? titleCase(metric);
}

function metricValue(entry: MetricEntry): string | null {
  if (entry.value == null) return null;
  if (CURRENCY_METRICS.has(entry.metric)) return formatMoney(entry.value, entry.currency ?? "CNY", { whole: entry.value >= 1000 });
  if (RATE_METRICS.has(entry.metric)) return formatRate(entry.value);
  return formatNumber(entry.value);
}

export default function MetricsCard({ payload }: { payload: MetricsPayload }) {
  const metrics = payload.metrics ?? [];
  return (
    <GenCard>
      <GenCardHeader title={payload.title ?? "经营指标"} aside={payload.period ? formatPeriodLabel(payload.period) : null} />
      <div className="mt-2 grid grid-cols-2 border-t border-(--line) [&>*:nth-child(even)]:border-l [&>*:nth-child(n+3)]:border-t [&>*]:border-(--line)">
        {metrics.map((entry, index) => {
          const value = metricValue(entry);
          const points = entry.series?.points?.map((point) => point.value);
          return (
            <div key={`${entry.metric}-${index}`} className="min-w-0 px-3.5 py-3">
              <div className="text-[12px] font-medium text-(--ink-soft)">{metricLabel(entry.metric)}</div>
              <div className="mt-1 flex min-w-0 flex-wrap items-baseline gap-x-2 gap-y-1.5">
                {value != null ? <span className="min-w-0 max-w-full text-[20px] font-semibold leading-tight tracking-[-0.02em] tabular-nums text-(--ink) [overflow-wrap:anywhere]">{value}</span> : null}
                <ChangeChip changePct={entry.change_pct} />
              </div>
              {points && points.length > 1 ? <Sparkline points={points} height={34} label={`${metricLabel(entry.metric)} trend`} className="mt-2" /> : null}
              {entry.note ? <div className="mt-1.5 text-[11.5px] leading-snug text-(--ink-soft)">{entry.note}</div> : null}
            </div>
          );
        })}
      </div>
    </GenCard>
  );
}
