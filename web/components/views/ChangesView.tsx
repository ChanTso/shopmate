"use client";
import { useState } from "react";
import { type ChangeAction, Notice, PageHeader, Skeleton } from "web-shared";
import { fetchChanges } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import ChangePreviewCard from "@/components/generative/ChangePreviewCard";
import PageControls from "@/components/PageControls";
import type { StagedChange } from "@/lib/types";
export default function ChangesView({ refreshKey, onAct }: { refreshKey: number; onAct?: (id: string, action: ChangeAction) => Promise<StagedChange | null> }) {
  const [offset, setOffset] = useState(0);
  const { data, error } = useResource(() => fetchChanges(offset), [offset, refreshKey]);
  return <div className="flex flex-col gap-4"><PageHeader title="草案与审批历史" subtitle="当前操作员的商品内容、调价、库存、促销与营销计划。商品操作展开后至多 25 个 SKU，核对每一项后批准。" />{error ? <Notice>{error}</Notice> : !data ? <Skeleton className="h-60" /> : <>{!data.changes.length ? <Notice>此页没有草案。可以让助手分析经营问题并准备方案。</Notice> : <div className="grid items-start gap-4 2xl:grid-cols-2">{data.changes.map(change => <ChangePreviewCard key={change.change_id} payload={{ change_id: change.change_id, change }} onAct={onAct} />)}</div>}<PageControls offset={offset} nextOffset={data.next_offset} pageSize={24} onPage={setOffset} /></>}</div>;
}
