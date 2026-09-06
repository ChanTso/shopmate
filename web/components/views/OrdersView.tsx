// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";
import { AttentionList, Notice, PageHeader, Panel, Skeleton } from "web-shared";
import type { OverviewResponse } from "@/lib/types";
import IssueRow from "./IssueRow";
import RecentOrders from "./RecentOrders";

export default function OrdersView({ data, failed, error, onAskAssistant }: { data: OverviewResponse | null; failed: boolean; error?: string | null; onAskAssistant: (text: string) => void }) {
  if (!data) return failed ? <Notice>{error ?? "订单数据暂时无法读取，请刷新重试。"}</Notice> : <Skeleton className="h-72" />;
  const attention = data.needs_attention;
  return <div className="ac-reveal flex flex-col gap-4">
    <PageHeader title="订单与售后" subtitle="查看当前近期订单，再核对未解决的履约与售后问题。" />
    <div className="grid items-start gap-4 2xl:grid-cols-2">
      <div className="space-y-4"><Panel title="待处理问题" subtitle={`本次读取 ${attention.order_issues.length} 条`}><AttentionList>{attention.order_issues.map(issue => <IssueRow key={issue.issue_id} issue={issue} onAskAssistant={onAskAssistant} />)}</AttentionList>{!attention.order_issues.length && <p className="p-4 text-sm text-(--ink-soft)">当前没有未解决的问题。</p>}</Panel>
        {attention.order_issues_may_have_more && <Notice>本次已达 {attention.order_issues_limit} 条读取上限，可能还有未列出的订单问题。</Notice>}
        <p className="text-xs text-(--ink-soft)">问题提示与付款、退款、履约状态分别核对；退款申请不表示退款成功。此页面不执行发货或发送买家消息。</p>
      </div>
      <Panel title="近期订单" subtitle="全店最近创建的至多 6 个 SKU 子单；不受历史报表截止时间限制。"><RecentOrders orders={data.recent_orders} /><p className="border-t border-(--line) p-4 text-xs text-(--ink-soft)">每行是实际交易子单，显示下单时的价格和数量；同一次结账的多个子单分别列出，不合并成虚拟订单。时间为上海时间。</p></Panel>
    </div>
  </div>;
}
