// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

import { ChangeChip, formatPeriodLabel, GenCard, GenCardHeader, Sparkline, titleCase } from "web-shared";
import type { MetricsPayload } from "@/lib/types";
import { metricValue } from "@/lib/metric-value";

function metricLabel(metric: string): string {
  if (metric === "average_order_value") return "客单价";
  return ({ sales: "成交额", revenue: "成交额", orders: "成交订单", units: "成交件数" } as Record<string, string>)[metric] ?? titleCase(metric);
}

export default function MetricsCard({ payload }: { payload: MetricsPayload }) {
  const metrics = payload.metrics ?? [];
  const analysis = payload.analysis;
  return (
    <GenCard>
      <GenCardHeader title={analysis?.headline ?? payload.title ?? "经营指标"} aside={payload.period ? formatPeriodLabel(payload.period) : null} />
      {analysis?.findings.length ? (
        <ul className="mx-4 mb-3 list-disc space-y-1.5 pl-4 text-[13px] leading-relaxed text-(--ink)">
          {analysis.findings.map((finding, index) => <li key={index}>{finding}</li>)}
        </ul>
      ) : null}
      {metrics.length ? <div className="mt-2 grid grid-cols-2 border-t border-(--line) [&>*:nth-child(even)]:border-l [&>*:nth-child(n+3)]:border-t [&>*]:border-(--line)">
        {metrics.map((entry, index) => {
          const value = metricValue(entry, analysis != null);
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
      </div> : null}
      {analysis?.caveats.length || analysis?.method_note ? (
        <div className="space-y-3 border-t border-(--line) px-4 py-3 text-[12px] leading-relaxed text-(--ink-soft)">
          {analysis.caveats.length ? <div>
            <p className="font-medium text-(--ink)">说明与限制</p>
            <ul className="mt-1 list-disc space-y-1 pl-4">
              {analysis.caveats.map((caveat, index) => <li key={index}>{caveat}</li>)}
            </ul>
          </div> : null}
          {analysis.method_note ? <div>
            <p className="font-medium text-(--ink)">计算口径</p>
            <p className="mt-1">{analysis.method_note}</p>
          </div> : null}
        </div>
      ) : null}
    </GenCard>
  );
}
