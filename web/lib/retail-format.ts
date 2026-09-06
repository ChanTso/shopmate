import type { Campaign, ChangeItem, ReportingWindow } from "./types.ts";
export const SHANGHAI = "Asia/Shanghai";
export function localDateTime(value: string | null | undefined, timeZone = SHANGHAI): string {
  if (!value) return "未设置";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("zh-CN", { timeZone, dateStyle: "medium", timeStyle: "short", hourCycle: "h23" }).format(date);
}
export function windowLabel(window?: ReportingWindow): string {
  return window ? `${localDateTime(window.start, window.timeZone)} 至 ${localDateTime(window.end, window.timeZone)}（结束不含） · ${window.timeZone}` : "";
}
export function money(value: number | null | undefined, currency = "CNY"): string {
  return value == null ? "未知" : new Intl.NumberFormat("zh-CN", { style: "currency", currency }).format(value);
}
export function changeValue(item: ChangeItem, value: unknown, currency: string | null | undefined): string {
  if (value === null || value === undefined) return "未设置";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return ["price", "promotion_price", "budget"].includes(item.field) ? money(value, currency ?? "CNY") : new Intl.NumberFormat("zh-CN").format(value);
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
export function campaignRoas(campaign: Campaign): string {
  if (campaign.revenueMinor == null || campaign.spendMinor == null || campaign.spendMinor <= 0 || !campaign.observationStart || !campaign.observationEnd) return "未知";
  return `${(campaign.revenueMinor / campaign.spendMinor).toFixed(2)}×`;
}
