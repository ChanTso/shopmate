// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";
import { useState } from "react";
import { Button, Fact, Facts, Notice, PageHeader, Panel, Pill, SearchField, Sheet, Skeleton, formatMoney, formatNumber, useResource } from "web-shared";
import { fetchListingDetail, fetchListings } from "@/lib/api";
import type { Listing } from "@/lib/types";

const statuses: Record<Listing["status"], string> = { active: "在售", paused: "已暂停", draft: "未发布", out_of_stock: "已售罄" };
function Detail({ id, onClose, onAsk }: { id: string; onClose: () => void; onAsk: (text: string) => void }) {
  const { data, failed } = useResource(() => fetchListingDetail(id), [id]);
  return <Sheet title="商品详情" detail={id} onClose={onClose} closeLabel="关闭商品详情">
    {failed ? <Notice>商品暂时无法读取。</Notice> : !data ? <Skeleton className="h-44" /> : <>
      <h2 className="text-xl font-semibold">{data.listing.title}</h2>
      <Facts><Fact label="当前价格" value={formatMoney(data.listing.price, data.listing.currency ?? "CNY")} /><Fact label="当前库存" value={formatNumber(data.listing.stock)} /><Fact label="状态" value={statuses[data.listing.status]} /><Fact label="调价" value={data.listing.attributes?.price_editable === "true" ? "可准备草案" : "当前不可调价"} /></Facts>
      <p className="text-xs text-(--ink-soft)">库存只读。调价草案冻结旧价和商品版本，批准时由交易服务核对。</p>
      <Button variant="primary" icon="spark" onClick={() => { onAsk(`分析商品 ${data.listing.title}（${id}）最近 7 个完整 UTC 日的成交表现。`); onClose(); }}>分析此商品</Button>
      {data.listing.attributes?.price_editable === "true" && <Button variant="secondary" onClick={() => { onAsk(`读取商品 ${data.listing.title}（${id}）当前价格，为它准备降价 5% 的草案，等待我通过按钮批准。`); onClose(); }}>准备降价 5% 草案</Button>}
    </>}
  </Sheet>;
}

export default function CatalogView({ refreshKey, onAskAssistant }: { refreshKey: number; onAskAssistant: (text: string) => void }) {
  const { data, failed } = useResource(fetchListings, [refreshKey]);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const rows = data?.listings.filter(p => `${p.title} ${p.listing_id}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="ac-reveal flex flex-col gap-4">
    <PageHeader title="商品" subtitle="查询当前商品信息，调价通过草案审批执行。" />
    <SearchField value={query} onChange={setQuery} label="搜索商品" placeholder="搜索商品名称或 ID" />
    {failed ? <Notice>商品暂时无法读取，请刷新重试。</Notice> : !rows ? <Skeleton className="h-72" /> : <Panel title="商品目录" subtitle={`${rows.length} 个 · 本次读取最多 100 个`}><div className="overflow-auto"><table className="w-full text-left text-sm"><thead className="bg-(--ground) text-xs text-(--ink-soft)"><tr>{["商品", "价格", "库存", "状态", "调价"].map(h => <th className="px-4 py-3" key={h}>{h}</th>)}</tr></thead><tbody>{rows.map(p => <tr key={p.listing_id} className="border-t border-(--line)"><td className="px-4 py-3"><button className="text-left hover:underline" onClick={() => setSelected(p.listing_id)}><span className="font-medium">{p.title}</span><span className="mt-1 block text-xs text-(--ink-soft)">{p.listing_id}</span></button></td><td className="whitespace-nowrap px-4 py-3 tabular-nums">{formatMoney(p.price, p.currency ?? "CNY")}</td><td className="px-4 py-3 tabular-nums">{formatNumber(p.stock)}</td><td className="whitespace-nowrap px-4 py-3">{statuses[p.status]}</td><td className="whitespace-nowrap px-4 py-3"><Pill tone={p.attributes?.price_editable === "true" ? "ok" : "muted"}>{p.attributes?.price_editable === "true" ? "可调价" : "不可调价"}</Pill></td></tr>)}</tbody></table>{!rows.length && <p className="p-5 text-(--ink-soft)">未找到匹配商品。</p>}</div></Panel>}
    {selected && <Detail id={selected} onClose={() => setSelected(null)} onAsk={onAskAssistant} />}
  </div>;
}
