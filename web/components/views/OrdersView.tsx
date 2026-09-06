// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";
import { AttentionList, AttentionRow, Notice, PageHeader, Panel, Skeleton } from "web-shared";
import { fetchOrderIssues } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { localDateTime } from "@/lib/retail-format";
import { ISSUE_KINDS } from "@/lib/kinds";
import type { OrderIssue } from "@/lib/types";
function IssueRow({ issue, onAskAssistant }: { issue: OrderIssue; onAskAssistant: (text: string) => void }) {
  const style = ISSUE_KINDS[issue.kind];
  return <AttentionRow icon={style.icon} tone={style.tone} title={issue.summary} meta={[style.label, `订单 ${issue.order_id}`, issue.listing_id, issue.opened_at && localDateTime(issue.opened_at)].filter(Boolean).join(" · ")} note={<div className="space-y-2">{issue.fulfillment && <div className="text-xs text-(--ink-soft)"><p>履约观察：{issue.fulfillment.stage} · {issue.fulfillment.method}</p><p>承诺送达 {localDateTime(issue.fulfillment.promisedDeliveryAt)} · 当前预计 {localDateTime(issue.fulfillment.estimatedDeliveryAt)}</p>{issue.fulfillment.deliveredAt && <p>实际送达 {localDateTime(issue.fulfillment.deliveredAt)}</p>}{issue.fulfillment.delayReason && <p>{issue.fulfillment.delayReason}</p>}</div>}{issue.refund_requested_order_count != null && <p className="text-xs text-(--ink-soft)">报告期间有退款申请的订单 {issue.refund_requested_order_count} 个；{localDateTime(issue.window_start)} 至 {localDateTime(issue.window_end)}（结束不含）。</p>}{issue.buyer_message_excerpt ? <div className="mt-1 rounded-lg bg-(--ground) p-3"><blockquote className="text-sm">“{issue.buyer_message_excerpt}”</blockquote><p className="mt-1 text-xs text-(--ink-soft)">买家提供的内容，仅作为待核对的资料。</p></div> : null}{issue.source_ref && <p className="break-all text-xs text-(--ink-soft)">来源：{issue.source_kind} · {issue.source_ref}</p>}</div>} action={{ label: issue.kind === "buyer_message" ? "拟定回复" : "分析问题", onClick: () => onAskAssistant(`读取订单问题 ${issue.issue_id}（订单 ${issue.order_id}）的权威事实，分析 ${issue.summary}，提出我可采取的措施；不要声称已发货、已退款或已联系买家。`) }} />;
}
export default function OrdersView({ refreshKey, onAskAssistant }: { refreshKey: number; onAskAssistant: (text: string) => void }) {
  const { data, error } = useResource(fetchOrderIssues, [refreshKey]);
  return <div className="ac-reveal flex flex-col gap-4"><PageHeader title="订单问题" subtitle="核对未解决的履约与售后问题，再让助手分析处理方案。" />{error ? <Notice>{error}</Notice> : !data ? <Skeleton className="h-72" /> : <><Panel title="待处理问题" subtitle={`本次读取 ${data.order_issues.length} 条`}><AttentionList>{data.order_issues.map(issue => <IssueRow key={issue.issue_id} issue={issue} onAskAssistant={onAskAssistant} />)}</AttentionList>{!data.order_issues.length && <p className="p-4 text-sm text-(--ink-soft)">当前没有未解决的问题。</p>}</Panel>{data.truncated && <Notice>本次最多显示 {data.limit} 条问题，仍有更多记录。请先处理当前问题后刷新。</Notice>}<p className="text-xs text-(--ink-soft)">问题提示与付款、退款、履约状态分别核对；退款申请不表示退款成功。此页面不执行发货或发送买家消息。</p></>}</div>;
}
