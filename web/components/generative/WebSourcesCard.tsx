import { GenCard, GenCardHeader } from "web-shared";
import { sourceLinks, type SourceLink, type WebSourcesPayload } from "@/lib/web-sources";

function Sources({ links, numbered = false }: { links: SourceLink[]; numbered?: boolean }) {
  return <ul className="space-y-2">
    {links.map(link => <li key={`${link.number}-${link.href}`} className="text-sm">
      <a href={link.href} target="_blank" rel="noopener noreferrer" className="break-words font-medium underline decoration-(--line) underline-offset-4 hover:decoration-current">{numbered && `[${link.number}] `}{link.title}</a>
      <span className="ml-2 break-all text-xs text-(--ink-soft)">{link.hostname}</span>
    </li>)}
  </ul>;
}

export default function WebSourcesCard({ payload }: { payload: WebSourcesPayload }) {
  const citations = sourceLinks(payload.citations);
  const consulted = sourceLinks(payload.consulted_sources);
  const longSummary = payload.summary.length > 600 || payload.summary.split("\n").length > 8;
  return <GenCard>
    <GenCardHeader title="外部资料与来源" />
    <div className="space-y-4 p-4">
      <p className="break-words text-xs text-(--ink-soft)">搜索：{payload.query}</p>
      {longSummary ? <details className="rounded-lg border border-(--line) p-3"><summary className="cursor-pointer text-sm font-medium">展开搜索摘要</summary><p className="mt-3 whitespace-pre-wrap break-words text-sm leading-relaxed">{payload.summary}</p></details> : <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">{payload.summary}</p>}
      {payload.summary_truncated && <p className="text-xs text-(--ink-soft)">摘要已按显示上限截断，请打开来源核对原文。</p>}
      {citations.length ? <section aria-label="引用来源" className="space-y-2"><h3 className="text-sm font-semibold">引用来源</h3><Sources links={citations} numbered /></section> : <p role="status" className="rounded-lg bg-(--warn-soft) p-3 text-sm">本次没有可展示的引用来源，摘要仍需进一步核对。</p>}
      {consulted.length > 0 && <details className="rounded-lg border border-(--line) p-3"><summary className="cursor-pointer text-sm font-medium">搜索服务另行返回的查阅来源</summary><div className="mt-3 space-y-2"><Sources links={consulted} /><p className="text-xs text-(--ink-soft)">查阅来源与回答引用分开列示；此列表不代表完整查阅记录。</p></div></details>}
      {!payload.sources_available && !consulted.length && !citations.length && <p className="text-xs text-(--ink-soft)">搜索服务未提供可核对的来源元数据。</p>}
      <p className="text-xs leading-relaxed text-(--ink-soft)">这些是外部资料。本站商品价格、库存、政策及订单状态，以工作台实际读取为准。</p>
    </div>
  </GenCard>;
}
