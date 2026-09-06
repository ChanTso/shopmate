// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";
import { useState } from "react";
import { Button, Fact, Facts, Notice, PageHeader, Panel, Pill, SearchField, Sheet, Skeleton, Thumb, formatNumber } from "web-shared";
import { api, fetchListingDetail, fetchListings } from "@/lib/api";
import { useResource } from "@/lib/use-resource";
import { money, windowLabel } from "@/lib/retail-format";
import type { Listing, ListingFilters, PricingContext } from "@/lib/types";
import PageControls from "@/components/PageControls";

const statuses: Record<Listing["status"], string> = { active: "在售", paused: "已暂停", draft: "未发布", out_of_stock: "已售罄" };
function Status({ listing }: { listing: Listing }) { return <Pill tone={listing.status === "active" ? "ok" : listing.status === "out_of_stock" ? "danger" : "muted"}>{statuses[listing.status]}</Pill>; }
function PriceFacts({ pricing }: { pricing: PricingContext }) {
  return <Facts><Fact label="单位成本观察" value={pricing.unit_cost == null ? "未知" : money(pricing.unit_cost, pricing.currency)} /><Fact label="毛利率" value={pricing.margin_pct == null ? "未知" : `${pricing.margin_pct.toFixed(1)}%`} /><Fact label="价格下限" value={pricing.min_price == null ? "未设置" : money(pricing.min_price, pricing.currency)} /><Fact label="价格上限" value={pricing.max_price == null ? "未设置" : money(pricing.max_price, pricing.currency)} /></Facts>;
}
function Detail({ id, onClose, onSelect, onAsk }: { id: string; onClose: () => void; onSelect: (id: string) => void; onAsk: (text: string) => void }) {
  const { data, error } = useResource(() => fetchListingDetail(id), [id]);
  const listing = data?.listing;
  const attributes = Object.entries(listing?.attributes ?? {}).filter(([key]) => !["price_editable", "publication_state", "publication_version"].includes(key));
  const ask = (prompt: string) => { onAsk(prompt); onClose(); };
  return <Sheet title="商品详情" detail={id} onClose={onClose} closeLabel="关闭商品详情">
    {error ? <Notice>{error}</Notice> : !listing ? <Skeleton className="h-44" /> : <>
      <div className="flex gap-4"><Thumb src={api.assetUrl(listing.image_url)} alt={listing.title} size={84} /><div><h2 className="text-xl font-semibold">{listing.title}</h2><p className="mt-2 text-sm text-(--ink-soft)">{listing.short_description}</p><div className="mt-2 flex flex-wrap gap-2"><Status listing={listing} />{listing.category && <Pill>{listing.category}</Pill>}{listing.content_quality && <Pill tone={listing.content_quality === "good" ? "ok" : "warn"}>内容：{listing.content_quality === "good" ? "完整" : listing.content_quality === "poor" ? "待完善" : "有待补充"}</Pill>}</div></div></div>
      <Facts><Fact label={listing.variants?.length ? "规格起价" : "当前价格"} value={money(listing.price, listing.currency)} /><Fact label="当前库存" value={formatNumber(listing.stock)} /><Fact label="报告期内近 30 日销量" value={listing.sales_last_30d == null ? "未知" : formatNumber(listing.sales_last_30d)} /><Fact label="有退款申请的订单比例" value={listing.refund_requested_order_pct == null ? "未知" : `${listing.refund_requested_order_pct.toFixed(1)}%`} /></Facts>
      {listing.window && <p className="text-xs text-(--ink-soft)">{windowLabel(listing.window)}。退款申请比例不代表已退款或实物退货率。</p>}
      {listing.variants?.length ? <section><h3 className="mb-2 font-semibold">可选规格</h3><div className="overflow-auto"><table className="w-full text-left text-sm"><thead><tr>{["规格 / SKU", "当前价格", "库存", "状态"].map(label => <th key={label} className="p-2">{label}</th>)}</tr></thead><tbody>{listing.variants.map(variant => <tr className="border-t border-(--line)" key={variant.listing_id}><td className="p-2"><button className="text-left hover:underline" onClick={() => onSelect(variant.listing_id)}>{Object.entries(variant.option_values ?? {}).map(([key, value]) => `${key}: ${value}`).join(" · ")}<span className="block text-xs text-(--ink-soft)">{variant.listing_id}</span></button></td><td className="p-2 whitespace-nowrap">{money(variant.price, variant.currency)}</td><td className="p-2">{variant.stock}</td><td className="p-2"><Status listing={variant} /></td></tr>)}</tbody></table></div></section> : data?.pricing && <PriceFacts pricing={data.pricing} />}
      {listing.variant_of && <Button variant="secondary" size="sm" onClick={() => onSelect(listing.variant_of!)}>查看所属系列 {listing.variant_of}</Button>}
      {listing.long_description && <section><h3 className="mb-2 font-semibold">商品文案</h3><p className="whitespace-pre-wrap break-words text-sm leading-relaxed text-(--ink-soft)">{listing.long_description}</p></section>}
      {attributes.length > 0 && <section><h3 className="mb-2 font-semibold">属性</h3><dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-x-3 gap-y-2 text-sm">{attributes.map(([key, value]) => <div key={key} className="contents"><dt className="break-words text-(--ink-soft)">{key}</dt><dd className="break-words">{value}</dd></div>)}</dl></section>}
      {listing.content?.brand && <p className="text-sm">品牌：{listing.content.brand}</p>}
      {listing.content?.specs && <section><h3 className="mb-2 font-semibold">技术规格</h3><dl className="space-y-2 text-sm">{Object.entries(listing.content.specs).map(([key, value]) => <div key={key} className="flex gap-3"><dt className="text-(--ink-soft)">{key}</dt><dd className="break-words">{typeof value === "object" ? JSON.stringify(value) : String(value)}</dd></div>)}</dl></section>}
      {listing.missing_attributes?.length ? <Notice>待补充属性：{listing.missing_attributes.join("、")}</Notice> : null}
      {listing.review_snippets?.length ? <section><h3 className="mb-2 font-semibold">买家评论摘录</h3>{listing.review_snippets.map((review, index) => <blockquote className="my-2 border-l-2 border-(--line) pl-3 text-sm" key={index}>{review}</blockquote>)}<p className="text-xs text-(--ink-soft)">买家提供的内容，作为分析资料展示。</p></section> : null}
      <div className="flex flex-wrap gap-2"><Button variant="primary" icon="spark" onClick={() => ask(`分析商品 ${listing.title}（${id}）在当前报告期间的表现，并结合真实规格、库存和成本给出建议。`)}>分析此商品</Button><Button variant="secondary" onClick={() => ask(`读取商品 ${listing.title}（${id}）完整内容，为它准备有依据的文案或属性修改草案，等我批准。`)}>完善商品内容</Button>{listing.price_editable && <Button variant="secondary" onClick={() => ask(`读取 ${id} 的实际价格和规格，为可调价的 SKU 准备降价 5% 草案，等我通过按钮批准。`)}>准备调价草案</Button>}<Button variant="secondary" onClick={() => ask(`检查商品 ${id} 的库存与近期销量，提出补货或上下架方案并准备草案，等我批准。`)}>准备库存方案</Button></div>
      <p className="text-xs text-(--ink-soft)">商品版本 {listing.publication_version ?? "系列按各 SKU 核对"} · 展示版本 {listing.metadata_version ?? "—"}。所有变更均需核对草案后批准。</p>
    </>}
  </Sheet>;
}

export default function CatalogView({ refreshKey, onAskAssistant }: { refreshKey: number; onAskAssistant: (text: string) => void }) {
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<ListingFilters>({});
  const filter = (key: keyof ListingFilters, value: string) => { setFilters(current => { const next = { ...current }; if (value) Object.assign(next, { [key]: value }); else delete next[key]; return next; }); setOffset(0); };
  const [offset, setOffset] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const { data, error } = useResource(() => fetchListings(query, offset, filters), [query, offset, filters, refreshKey]);
  return <div className="ac-reveal flex flex-col gap-4"><PageHeader title="商品目录" subtitle="浏览真实商品与规格，分析表现，再准备需要批准的经营方案。" /><SearchField value={query} onChange={value => { setQuery(value); setOffset(0); }} label="搜索商品" placeholder="搜索商品名称、属性或描述" />
    <div className="grid grid-cols-2 gap-3 text-xs lg:grid-cols-4"><label>状态<select aria-label="商品状态" value={filters.status ?? ""} onChange={event => filter("status", event.target.value)} className="mt-1 w-full rounded-lg border border-(--line) bg-(--card) p-2"><option value="">全部状态</option>{Object.entries(statuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label>内容质量<select aria-label="内容质量" value={filters.content_quality ?? ""} onChange={event => filter("content_quality", event.target.value)} className="mt-1 w-full rounded-lg border border-(--line) bg-(--card) p-2"><option value="">全部内容</option><option value="good">完整</option><option value="needs_work">有待补充</option><option value="poor">待完善</option></select></label><label>分类<input aria-label="商品分类" maxLength={100} value={filters.category ?? ""} onChange={event => filter("category", event.target.value)} placeholder="例如 home-kitchen" className="mt-1 w-full rounded-lg border border-(--line) bg-(--card) p-2" /></label><label>排序<select aria-label="目录排序" value={filters.sort ?? "relevance"} onChange={event => filter("sort", event.target.value)} className="mt-1 w-full rounded-lg border border-(--line) bg-(--card) p-2"><option value="relevance">相关度</option><option value="sales_desc">销量从高到低</option><option value="stock_asc">库存从低到高</option><option value="price_asc">CNY 价格从低到高</option><option value="price_desc">CNY 价格从高到低</option></select></label></div>
    {error ? <Notice>{error}</Notice> : !data ? <Skeleton className="h-72" /> : <><Panel title="商品目录" subtitle={`本页 ${data.listings.length} 个商品系列或单品`}><div className="overflow-auto"><table className="w-full text-left text-sm"><thead className="bg-(--ground) text-xs text-(--ink-soft)"><tr>{["商品", "价格", "库存", "状态", "内容"].map(label => <th key={label} className="px-4 py-3">{label}</th>)}</tr></thead><tbody>{data.listings.map(listing => <tr key={listing.listing_id} className="border-t border-(--line)"><td className="px-4 py-3"><button className="flex items-center gap-3 text-left hover:underline" onClick={() => setSelected(listing.listing_id)}><Thumb src={api.assetUrl(listing.image_url)} alt="" size={48} /><span><span className="font-medium">{listing.title}</span><span className="mt-1 block text-xs text-(--ink-soft)">{listing.listing_id}{Object.keys(listing.options ?? {}).length ? " · 多规格" : ""}</span></span></button></td><td className="whitespace-nowrap px-4 py-3 tabular-nums">{Object.keys(listing.options ?? {}).length ? "起 " : ""}{money(listing.price, listing.currency)}</td><td className="px-4 py-3">{formatNumber(listing.stock)}</td><td className="px-4 py-3 whitespace-nowrap"><Status listing={listing} /></td><td className="px-4 py-3 whitespace-nowrap">{listing.content_quality === "good" ? "完整" : listing.content_quality ? "待完善" : "未评定"}</td></tr>)}</tbody></table>{!data.listings.length && <p className="p-5 text-(--ink-soft)">未找到匹配商品。</p>}</div></Panel><PageControls offset={offset} nextOffset={data.next_offset} pageSize={24} onPage={setOffset} /><p className="text-xs text-(--ink-soft)">商品系列不拆页；价格与库存为当前值。经营统计窗口：{windowLabel(data.window)}</p></>}
    {selected && <Detail key={selected} id={selected} onClose={() => setSelected(null)} onSelect={setSelected} onAsk={onAskAssistant} />}
  </div>;
}
