import type { MetricEntry } from "./types.ts";

const numberFormat = new Intl.NumberFormat("en-US");

function money(value: number, currency: string, whole = false): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency,
    maximumFractionDigits: whole ? 0 : 2,
  }).format(value);
}

const CURRENCY_METRICS = new Set(["sales", "average_order_value", "revenue", "spend"]);
const RATE_METRICS = new Set(["conversion_rate", "return_rate", "click_through_rate"]);

export function metricValue(entry: MetricEntry, analysis = false): string | null {
  if (entry.value == null) return null;
  if (analysis || entry.unit !== undefined) {
    if (entry.currency) return money(entry.value, entry.currency);
    const unit = entry.unit?.trim();
    return `${numberFormat.format(entry.value)}${unit === "%" ? "%" : unit ? ` ${unit}` : ""}`;
  }
  if (CURRENCY_METRICS.has(entry.metric)) return money(entry.value, entry.currency ?? "CNY", entry.value >= 1000);
  if (RATE_METRICS.has(entry.metric)) return `${entry.value.toFixed(1)}%`;
  return numberFormat.format(entry.value);
}
