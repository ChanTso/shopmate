// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";
import { ApproveBar, type ChangeAction, ChangeStatusPill, formatDate, formatMoney, GenCard, GenCardHeader, GuardrailNotes, useChangeActions } from "web-shared";
import type { ChangePreviewPayload, StagedChange } from "@/lib/types";

export default function ChangePreviewCard({ payload, onAct }: { payload: ChangePreviewPayload; onAct?: (id: string, action: ChangeAction) => Promise<StagedChange | null> }) {
  const { change, busy, error, act, canAct } = useChangeActions(payload.change, onAct);
  const receipt = change.receipt;
  return <GenCard>
    <GenCardHeader title={payload.headline ?? "商品调价草案"} meta={<><ChangeStatusPill status={change.status} /><span>{formatDate(change.created_at)}</span></>} />
    <p className="px-3.5 pt-2 text-sm">{change.summary}</p>
    {payload.note && <p className="px-3.5 pt-1 text-xs text-(--ink-soft)">{payload.note}</p>}
    <div className="mx-3.5 mt-3 divide-y divide-(--line) rounded-xl bg-(--ground)">
      {receipt?.items ? receipt.items.map(item => <div key={item.productId} className="p-3">
        <div className="flex flex-wrap justify-between gap-2"><span className="font-medium">{item.name}</span><span className="tabular-nums"><s className="text-(--ink-soft)">{formatMoney(item.oldPriceMinor / 100, receipt.currency)}</s> → <b>{formatMoney(item.newPriceMinor / 100, receipt.currency)}</b></span></div>
        <p className="mt-1 break-all text-xs text-(--ink-soft)">{item.productId} · 待核对版本 {item.expectedVersion}</p>
      </div>) : change.items.map((item, i) => <div key={i} className="p-3 text-sm"><span>{item.target}</span><span className="float-right">{typeof item.before === "number" ? formatMoney(item.before, change.currency ?? "CNY") : String(item.before ?? "—")} → {typeof item.after === "number" ? formatMoney(item.after, change.currency ?? "CNY") : String(item.after ?? "—")}</span></div>)}
    </div>
    {receipt?.result?.reason && <p role="status" className="mx-3.5 mt-3 rounded-lg bg-(--danger-soft) p-3 text-sm text-(--danger)">整批未执行：{receipt.result.reason}{receipt.result.productId ? `（${receipt.result.productId}）` : ""}</p>}
    {receipt?.result?.changes?.length ? <details className="mx-3.5 mt-3 text-xs text-(--ink-soft)"><summary className="cursor-pointer">查看执行回执</summary>{receipt.result.changes.map(row => <div key={row.productId} className="mt-2 break-all">{row.productId} · 版本 {row.oldVersion} → {row.newVersion}<br />事件 {row.eventId}</div>)}</details> : null}
    {receipt && <p className="mx-3.5 mt-2 break-all text-[11px] text-(--ink-soft)">草案 {receipt.draftId}</p>}
    <GuardrailNotes notes={change.guardrail_notes} />
    <ApproveBar change={change} busy={busy} error={error} canAct={canAct} onAct={action => void act(action)} />
  </GenCard>;
}
