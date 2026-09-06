import { dailySlots, trendRuns } from "@/lib/merchant-overview";
import type { MetricPoint, ReportingWindow } from "@/lib/types";

export default function MetricTrend({ label, points, prior, window, priorWindow, note, priorNote }: { label: string; points: MetricPoint[]; prior: MetricPoint[]; window: ReportingWindow; priorWindow: ReportingWindow; note: string; priorNote: string }) {
  const current = dailySlots(points, window);
  const previous = dailySlots(prior, priorWindow);
  const series = [trendRuns(current), trendRuns(previous)];
  const values = series.flat(2).map(point => point.value);
  const min = values.length ? Math.min(...values) : 0;
  const range = (values.length ? Math.max(...values) : 0) - min || 1;
  const dayCount = Math.max(current.length, previous.length, 2);
  const x = (day: number) => 6 + day * 288 / (dayCount - 1);
  const y = (value: number) => 76 - (value - min) * 64 / range;
  return <div className="min-w-0 space-y-2">
    {values.length ? <svg role="img" aria-label={`${label}每日趋势；实线为当前期间，虚线为前期，缺失日期留空`} viewBox="0 0 300 88" className="h-28 w-full overflow-visible">
      <line x1="6" x2="294" y1="83" y2="83" stroke="var(--line)" />
      {[1, 0].map(index => series[index].map((run, runIndex) => <g key={`${index}-${runIndex}`}>
        {run.length > 1 && <path d={run.map((point, position) => `${position ? "L" : "M"}${x(point.index).toFixed(2)},${y(point.value).toFixed(2)}`).join(" ")} fill="none" stroke={index ? "var(--ink-faint)" : "var(--ink)"} strokeWidth="1.8" strokeDasharray={index ? "4 3" : undefined} strokeLinecap="round" />}
        {run.map(point => <circle key={point.date} cx={x(point.index)} cy={y(point.value)} r={run.length === 1 ? 3 : 2} fill={index ? "var(--card)" : "var(--ink)"} stroke={index ? "var(--ink-faint)" : "var(--ink)"}><title>{index ? "前期" : "当前"} {point.date}：{point.value}</title></circle>)}
      </g>))}
    </svg> : <p className="flex h-28 items-center text-sm text-(--ink-soft)">当前和前期均未返回可绘制的日数值。</p>}
    <div className="space-y-1 text-[11px] text-(--ink-soft)"><p>当前：{current[0]?.date} — {current.at(-1)?.date}</p><p>前期：{previous[0]?.date} — {previous.at(-1)?.date}</p>{!series[0].length && !!series[1].length && <p>当前期间未返回数值，仅显示前期。</p>}{!!series[0].length && !series[1].length && <p>前期未返回数值，仅显示当前期间。</p>}</div>
    {(note || priorNote) && <details className="text-xs text-(--ink-soft)"><summary className="cursor-pointer">数据口径</summary><div className="mt-2 space-y-1">{note && <p>当前：{note}</p>}{priorNote && <p>前期：{priorNote}</p>}</div></details>}
  </div>;
}
