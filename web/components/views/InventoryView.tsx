// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";
import { useState } from "react";
import { AskButton, coverLabel, formatNumber, KindIcon, MiniBar, Notice, optionValuesLabel, PageHeader, Panel, Pill, Skeleton } from "web-shared";
import { fetchInventory } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { windowLabel } from "@/lib/retail-format";
import { INVENTORY_KINDS } from "@/lib/kinds";
import type { InventoryAlert } from "@/lib/types";
import PageControls from "@/components/PageControls";

function AlertRow({ alert, onAskAssistant }: { alert: InventoryAlert; onAskAssistant: (text: string) => void }) {
  const style = INVENTORY_KINDS[alert.kind];
  const low = alert.kind === "low_stock";
  const chosen = optionValuesLabel(alert);
  return <li className="flex flex-wrap items-center gap-3 px-4 py-3"><KindIcon icon={style.icon} tone={alert.stock === 0 ? "danger" : style.tone} /><div className="min-w-0 flex-1"><div className="text-sm font-medium">{alert.title}{chosen && <span className="font-normal text-(--ink-soft)"> · {chosen}</span>}</div><div className="mt-1 text-xs text-(--ink-soft)">{alert.listing_id}{alert.sales_last_30d != null && ` · 报告期近 30 日销量 ${formatNumber(alert.sales_last_30d)}`}{low && alert.threshold != null && ` · 补货阈值 ${alert.threshold}`}</div>{alert.storefront_visible === false && <Pill tone="muted">当前不可购买</Pill>}</div><div className="text-right tabular-nums"><strong>{formatNumber(alert.stock)}</strong><span className="ml-1 text-xs">件库存</span><div className="mt-1 flex items-center justify-end gap-2 text-xs text-(--ink-soft)">{low && !!alert.threshold && <MiniBar value={alert.stock / (alert.threshold * 2)} tone="warn" />}{alert.days_of_cover != null ? coverLabel(alert.days_of_cover) : "无覆盖天数估算"}</div></div><AskButton label={low ? "准备补货" : "分析滞销"} onClick={() => onAskAssistant(low ? `依据 ${alert.listing_id}（${alert.title} ${chosen}）实际库存与销量，准备合理补货草案，等我批准。` : `分析 ${alert.listing_id}（${alert.title} ${chosen}）的滞销原因，读取实际成本和价格后给出处理方案。`)} /></li>;
}
export default function InventoryView({ refreshKey, onAskAssistant }: { refreshKey: number; onAskAssistant: (text: string) => void }) {
  const [offset, setOffset] = useState(0);
  const { data, error } = useResource(() => fetchInventory(offset), [offset, refreshKey]);
  const low = data?.inventory.filter(a => a.kind === "low_stock") ?? [];
  const slow = data?.inventory.filter(a => a.kind === "slow_mover") ?? [];
  return <div className="ac-reveal flex flex-col gap-4"><PageHeader title="库存健康" subtitle="按真实 SKU 查看缺货、补货阈值与滞销；变更先预览、再批准。" />{error ? <Notice>{error}</Notice> : !data ? <Skeleton className="h-72" /> : <><p className="text-xs text-(--ink-soft)">{windowLabel(data.window)} · 以下分类仅统计本页</p><div className="grid items-start gap-4 2xl:grid-cols-2">{[["低库存 / 缺货", low], ["滞销", slow]].map(([title, rows]) => <Panel key={String(title)} title={String(title)}><ul className="divide-y divide-(--line)">{(rows as InventoryAlert[]).map(alert => <AlertRow key={`${alert.kind}-${alert.listing_id}`} alert={alert} onAskAssistant={onAskAssistant} />)}</ul>{!(rows as InventoryAlert[]).length && <p className="p-4 text-sm text-(--ink-soft)">本页暂无此类提醒。</p>}</Panel>)}</div><PageControls offset={offset} nextOffset={data.next_offset} pageSize={50} onPage={setOffset} /></>}</div>;
}
