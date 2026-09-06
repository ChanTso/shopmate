// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";
import { Button, type ChangeAction, ChangeStatusPill, GenCard, GenCardHeader, GuardrailNotes, isLongTextDiff, LongTextDiff, useChangeActions } from "web-shared";
import { changeValue, localDateTime } from "@/lib/retail-format";
import type { ChangeKind, ChangePreviewPayload, StagedChange } from "@/lib/types";
const labels: Record<ChangeKind, string> = { price_update: "商品调价", listing_update: "商品内容", inventory_action: "库存与上下架", promotion: "促销改价", campaign: "营销计划" };
const fields: Record<string, string> = { price: "价格", promotion_price: "促销价格", stock: "库存", available: "可售", budget: "预算", title: "标题", short_description: "摘要", long_description: "详细文案", category: "分类", name: "名称", audience: "目标受众", objective: "目标", copy_text: "营销文案", starts: "开始时间", ends: "结束时间" };
export default function ChangePreviewCard({ payload, onAct }: { payload: ChangePreviewPayload; onAct?: (id: string, action: ChangeAction) => Promise<StagedChange | null> }) {
  const { change, busy, error, act, canAct } = useChangeActions(payload.change, onAct);
  const receipt = change.receipt;
  const operation = receipt && "payload" in receipt ? receipt.payload : null;
  const receiptId = receipt && ("changeId" in receipt ? receipt.changeId : receipt.draftId);
  const reason = receipt?.result?.reason;
  return <GenCard><GenCardHeader title={payload.headline ?? `${labels[change.kind]}草案`} meta={<><ChangeStatusPill status={change.status} /><span>{localDateTime(change.created_at)}</span></>} />
    <p className="px-3.5 pt-2 text-sm">{change.summary}</p>{payload.note && <p className="px-3.5 pt-1 text-xs text-(--ink-soft)">{payload.note}</p>}
    <div className="mx-3.5 mt-3 divide-y divide-(--line) rounded-xl bg-(--ground)">{change.items.filter(item => !isLongTextDiff(item)).map((item, index) => <div key={`${item.target}-${item.field}-${index}`} className="flex flex-wrap items-baseline justify-between gap-2 p-3 text-sm"><span className="break-all text-(--ink-soft)">{item.target} · {fields[item.field] ?? item.field}</span><span className="min-w-0 break-words tabular-nums"><s className="text-(--ink-soft)">{changeValue(item, item.before, change.currency)}</s> → <b>{changeValue(item, item.after, change.currency)}</b></span></div>)}</div>
    {change.items.filter(isLongTextDiff).map((item, index) => <LongTextDiff key={`${item.target}-${item.field}-${index}`} item={item} />)}
    {change.kind === "promotion" && <div className="mx-3.5 mt-3 rounded-lg border border-(--line-strong) bg-(--ground) p-3 text-sm"><p className="font-semibold">批准后立即修改商品实际售价；到期不会自动恢复原价。</p>{operation && <p className="mt-1 break-words">允许批准窗口：{String(operation.starts ?? "见草案")} 至 {String(operation.ends ?? "见草案")} · Asia/Shanghai（仅日期的结束日包含全天）。</p>}<p className="mt-1 text-xs text-(--ink-soft)">开始前草案保留待批准状态，可到时再次批准或取消；窗口内仍需核对价格与版本。结束后未批准的草案将被拒绝。</p></div>}
    {change.kind === "campaign" && <p className="mx-3.5 mt-3 rounded-lg bg-(--ground) p-3 text-sm">批准后保存本站营销计划与预算，不会向外部广告平台投放，也不会修改已有归因观察。</p>}
    {typeof reason === "string" && <p role="status" className="mx-3.5 mt-3 rounded-lg bg-(--danger-soft) p-3 text-sm text-(--danger)">整批未执行：{reason}</p>}
    {receipt?.result && <details className="mx-3.5 mt-3 text-xs text-(--ink-soft)"><summary className="cursor-pointer">查看执行回执</summary><pre className="mt-2 whitespace-pre-wrap break-all">{JSON.stringify(receipt.result, null, 2)}</pre><p>回执金额字段以分为单位，版本和事件编号保持原值。</p></details>}
    {receiptId && <p className="mx-3.5 mt-2 break-all text-[11px] text-(--ink-soft)">草案 {receiptId}</p>}
    <GuardrailNotes notes={change.guardrail_notes} />
    <div className="p-3.5">{change.status === "staged" ? <div className="flex flex-wrap items-center gap-2"><Button variant="accent" size="sm" icon="check" disabled={busy !== null || !canAct} onClick={() => void act("apply")}>{busy === "apply" ? "执行中…" : "批准并执行"}</Button><Button variant="secondary" size="sm" disabled={busy !== null || !canAct} onClick={() => void act("discard")}>{busy === "discard" ? "取消中…" : "取消草案"}</Button><span className="text-xs text-(--ink-soft)">按以上差异整批执行或整批拒绝。</span></div> : <p className="text-sm text-(--ink-soft)">{change.status === "applied" ? `已执行${change.applied_at ? ` · ${localDateTime(change.applied_at)}` : ""}` : change.status === "rejected" ? "整批未执行，请核对拒绝原因后重新准备草案。" : "草案已取消，未执行本次变更。"}</p>}{error && <p role="alert" className="mt-2 text-sm text-(--danger)">{error}</p>}</div>
  </GenCard>;
}
