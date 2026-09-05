"use client";
import { type ChangeAction, Notice, PageHeader, Skeleton } from "web-shared";
import ChangePreviewCard from "@/components/generative/ChangePreviewCard";
import type { OverviewResponse, StagedChange } from "@/lib/types";
export default function ChangesView({ data, failed, onAct }: { data: OverviewResponse | null; failed: boolean; onAct?: (id: string, action: ChangeAction) => Promise<StagedChange | null> }) {
  const changes = data ? [...new Map([...data.needs_attention.pending_changes, ...data.recent_changes].map(c => [c.change_id, c])).values()] : null;
  return <div className="flex flex-col gap-4"><PageHeader title="草案与审批历史" subtitle="每份草案至多包含 3 个同币种商品；批准时整批执行或整批拒绝。" />{failed ? <Notice>草案状态暂时无法读取，请刷新重试。</Notice> : !changes ? <Skeleton className="h-60" /> : !changes.length ? <Notice>本会话暂无草案。可以让助手先分析商品，再准备调价方案。</Notice> : <div className="grid gap-4 2xl:grid-cols-2">{changes.map(change => <ChangePreviewCard key={change.change_id} payload={{ change_id: change.change_id, change }} onAct={onAct} />)}</div>}</div>;
}
