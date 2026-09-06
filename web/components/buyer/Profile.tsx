"use client";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { Button } from "web-shared";
import type { BuyerProfile, Policy } from "@/lib/buyer-types";
import { buyerApi } from "@/lib/buyer-api";
import { POLICY_TOPICS, policySearchQuery } from "@/lib/buyer-policy-search";

export default function Profile({ profile, disabled, onClearMemory }: { profile: BuyerProfile | null; disabled: boolean; onClearMemory: () => Promise<void> }) {
  const [confirm, setConfirm] = useState(false);
  const [query, setQuery] = useState("");
  const [searched, setSearched] = useState("");
  const [policies, setPolicies] = useState<Policy[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const request = useRef(0);
  useEffect(() => () => { request.current += 1; }, []);

  async function search(input: string) {
    if (disabled || searching) return;
    let keyword: string;
    try { keyword = policySearchQuery(input); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "请检查政策关键词。"); setPolicies(null); return; }
    const current = ++request.current;
    setQuery(keyword); setSearched(keyword); setSearching(true); setError(null); setPolicies(null);
    try {
      const result = await buyerApi.get<{ policies: Policy[] }>("/policies", { query: keyword });
      if (current === request.current) setPolicies(result.policies);
    } catch (reason) {
      if (current === request.current) setError(reason instanceof Error ? reason.message : "政策搜索暂时不可用，请重试。");
    } finally {
      if (current === request.current) setSearching(false);
    }
  }

  function submit(event: FormEvent) { event.preventDefault(); void search(query); }

  return <div className="space-y-4">
    <h1 className="text-2xl font-semibold">资料、记忆与政策</h1>
    {profile ? <section className="space-y-2 rounded-xl border border-(--line) bg-(--card) p-4"><h2 className="font-semibold">{profile.display_name ?? profile.user_id}</h2><p>会员：{profile.loyalty_tier ?? "无记录"}</p><p>常用地点：{profile.default_location ?? "未设置"}</p><dl className="text-sm">{Object.entries(profile.preferences).map(([key, value]) => <div key={key} className="flex gap-2"><dt>{key}</dt><dd>{value}</dd></div>)}</dl><p className="text-xs text-(--ink-soft)">以上来自账户资料，模型不能修改；对话记忆单独管理。</p></section> : <p>账户资料待读取。</p>}
    <section className="space-y-3 rounded-xl border border-(--line) p-4"><h2 className="font-semibold">对话记忆</h2><p className="text-sm">点击右上角账户头像查看、纠正或忘记单条记忆。记忆按买家身份隔离，保存在服务端。</p><label className="flex gap-2 text-sm"><input type="checkbox" checked={confirm} disabled={disabled} onChange={e => setConfirm(e.target.checked)} />我确认清除当前买家身份的全部对话记忆。</label><Button disabled={disabled || !confirm} variant="secondary" onClick={() => { setConfirm(false); void onClearMemory(); }}>清除全部对话记忆</Button></section>
    <section className="space-y-4 rounded-xl border border-(--line) bg-(--card) p-4">
      <div><h2 className="text-lg font-semibold">搜索本站政策与购买指南</h2><p id="policy-search-help" className="mt-1 text-sm text-(--ink-soft)">按关键词搜索已发布内容，每次最多返回 3 条匹配结果。这里不是全部政策目录。</p></div>
      <form onSubmit={submit} className="space-y-2"><label htmlFor="policy-query" className="text-sm font-medium">政策关键词</label><div className="flex flex-wrap gap-2"><input id="policy-query" name="query" value={query} onChange={e => setQuery(e.target.value)} required maxLength={200} disabled={disabled || searching} aria-describedby="policy-search-help" placeholder="例如：退款、配送、会员" className="min-w-0 flex-1 rounded-lg border border-(--line-strong) bg-(--ground) px-3 py-2 text-sm disabled:opacity-50" /><Button type="submit" disabled={disabled || searching}>{searching ? "搜索中…" : "搜索政策"}</Button></div></form>
      <div className="flex flex-wrap gap-2" aria-label="政策搜索主题">{POLICY_TOPICS.map(topic => <Button key={topic.query} type="button" size="sm" variant="secondary" disabled={disabled || searching} onClick={() => void search(topic.query)}>{topic.label}</Button>)}</div>
      {error ? <p role="alert" className="break-words text-sm text-(--danger)">{error}</p> : searching ? <p role="status" className="text-sm text-(--ink-soft)">正在搜索“{searched}”…</p> : policies === null ? <p className="text-sm text-(--ink-soft)">输入关键词或点选主题后读取匹配政策。</p> : <div className="space-y-3"><p role="status" className="break-words text-sm text-(--ink-soft)">{policies.length ? `“${searched}”匹配到 ${policies.length} 条政策或指南。` : `没有找到与“${searched}”匹配的已发布内容，请换一个关键词。`}</p>{policies.map(policy => <details key={policy.policy_id} className="rounded-xl border border-(--line) p-4"><summary className="cursor-pointer font-semibold">{policy.title}</summary><p className="mt-3 whitespace-pre-wrap text-sm leading-relaxed">{policy.content}</p></details>)}</div>}
    </section>
  </div>;
}
