// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

"use client";
import { type FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { AssistantRail, Button, Notice, type PortalNavItem, PortalShell, type Prefill, Sheet, type ChangeAction, useMerchantChat } from "web-shared";
import AssistantPanel from "@/components/AssistantPanel";
import HomeView from "@/components/views/HomeView";
import CatalogView from "@/components/views/CatalogView";
import ChangesView from "@/components/views/ChangesView";
import InventoryView from "@/components/views/InventoryView";
import OrdersView from "@/components/views/OrdersView";
import MarketingView from "@/components/views/MarketingView";
import { useResource } from "@/lib/use-resource";
import { api, fetchOverview, type LoginResult, type SavedSession, type SessionDetail, UNREACHABLE } from "@/lib/api";
import type { StagedChange } from "@/lib/types";

type View = "home" | "catalog" | "inventory" | "orders" | "marketing" | "changes";
function StoreMark() { return <span aria-hidden className="grid h-[34px] w-[34px] shrink-0 place-items-center rounded-[10px] bg-(--ink) text-lg font-bold text-(--brand)">S</span>; }

function Login({ onLogin }: { onLogin: (identifier: string, password: string) => Promise<void> }) {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault(); if (busy) return;
    setBusy(true); setError(null);
    try { await onLogin(identifier, password); } catch (e) { setError(e instanceof Error ? e.message : UNREACHABLE); }
    finally { setPassword(""); setBusy(false); }
  }
  return <main className="grid min-h-dvh place-items-center bg-(--ground) px-5 py-12"><div className="w-full max-w-md"><div className="mb-8 flex items-center gap-3"><StoreMark /><div><h1 className="text-xl font-semibold">ShopMate</h1><p className="text-sm text-(--ink-soft)">商家经营工作台</p></div></div><form onSubmit={submit} className="space-y-5 rounded-2xl border border-(--line) bg-(--card) p-7 shadow-(--shadow)"><div><a href="/buyer" className="mb-3 inline-block text-sm font-semibold underline">进入买家购物工作台 →</a><h2 className="text-2xl font-semibold">登录工作台</h2><p className="mt-2 text-sm leading-relaxed text-(--ink-soft)">分析经营与商品事实，准备内容、价格、库存和营销方案，再由你批准。</p></div><label className="block text-sm font-medium">登录账号<input name="username" autoComplete="username" required value={identifier} onChange={e => setIdentifier(e.target.value)} className="mt-2 w-full rounded-lg border border-(--line-strong) px-3 py-2.5 outline-(--accent)" /></label><label className="block text-sm font-medium">密码<input name="password" type="password" autoComplete="current-password" required value={password} onChange={e => setPassword(e.target.value)} className="mt-2 w-full rounded-lg border border-(--line-strong) px-3 py-2.5 outline-(--accent)" /></label>{error && <p role="alert" className="text-sm text-(--danger)">{error}</p>}<button type="submit" disabled={busy} className="w-full rounded-lg bg-(--ink) px-4 py-3 font-semibold text-white disabled:opacity-50">{busy ? "登录中…" : "登录"}</button><p className="text-xs leading-relaxed text-(--ink-soft)">刷新页面后需重新登录，已有会话和草案会保留。</p></form></div></main>;
}

function Workbench({ selected, subject, sessions, sessionBusy, error, onSelect, onCreate, onReload, onLogout, onBusy }: { selected: SessionDetail; subject: string; sessions: SavedSession[]; sessionBusy: boolean; error: string | null; onSelect: (id: string) => void; onCreate: () => void; onReload: () => void; onLogout: () => void; onBusy: (busy: boolean) => void }) {
  const [view, setView] = useState<View>("home");
  const [assistantOpen, setAssistantOpen] = useState(true);
  const [activityOpen, setActivityOpen] = useState(false);
  const [prefill, setPrefill] = useState<Prefill | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const refresh = useCallback(() => setRefreshKey(v => v + 1), []);
  const chat = useMerchantChat<StagedChange>(api, { sessionId: selected.status === "running" ? null : selected.session_id, initialItems: selected.items, unreachable: UNREACHABLE, onPortalRefresh: refresh });
  const [stopped, setStopped] = useState(false);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  useEffect(() => { api.onReadError = setMemoryError; return () => { api.onReadError = null; }; }, []);
  useEffect(() => () => api.stopChat(), []);
  const [actionBusy, setActionBusy] = useState(false);
  const actionLock = useRef(false);
  const busy = chat.busy || selected.status === "running" || actionBusy;
  const send = async (text: string) => {
    if (actionLock.current || chat.busy || selected.status === "running" || sessionBusy) return;
    setStopped(false);
    await chat.send(text);
  };
  const actOnChange = async (id: string, action: ChangeAction) => {
    if (actionLock.current || chat.busy || selected.status === "running" || sessionBusy) throw new Error("当前会话正在处理请求，请等待完成。");
    actionLock.current = true; setActionBusy(true);
    try { return await chat.actOnChange(id, action); }
    finally { actionLock.current = false; setActionBusy(false); }
  };
  useEffect(() => { onBusy(busy); return () => onBusy(false); }, [busy, onBusy]);
  useEffect(() => { setAssistantOpen(window.innerWidth >= 1024); }, []);
  const { data: overview, failed, error: overviewError } = useResource(fetchOverview, [refreshKey]);
  const ask = useCallback((text: string) => { setAssistantOpen(true); setPrefill({ text, nonce: Date.now() }); }, []);
  const nav: PortalNavItem<View>[] = [{ id: "home", label: "经营概览", icon: "home" }, { id: "catalog", label: "商品", icon: "tag" }, { id: "inventory", label: "库存健康", icon: "box" }, { id: "orders", label: "订单问题", icon: "inbox" }, { id: "marketing", label: "营销与促销", icon: "chart" }, { id: "changes", label: "草案与审批历史", icon: "edit", count: overview?.needs_attention.pending_changes.length }];
  return <><PortalShell brand={{ mark: <StoreMark />, name: "ShopMate", detail: "商家经营工作台" }} nav={nav} view={view} onViewChange={setView} operator={{ name: subject, role: "商家操作员" }} assistantOpen={assistantOpen} assistantBusy={busy} onToggleAssistant={() => setAssistantOpen(x => !x)} rail={<AssistantRail open={assistantOpen} storageKey="shopmate-panel-width" onClose={() => setAssistantOpen(false)}>{rail => <AssistantPanel chat={{ ...chat, send, actOnChange, ready: chat.ready && !busy && !sessionBusy }} actionsDisabled={busy || sessionBusy} prefill={prefill} onPrefill={ask} newMemoryCount={chat.newMemoryKeys.size} onOpenActivity={() => setActivityOpen(true)} {...rail} />}</AssistantRail>}>
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-(--line) bg-(--card) p-3"><a href="/buyer" className="text-xs font-semibold underline">买家入口 ↗</a><label htmlFor="session" className="text-xs text-(--ink-soft)">会话</label><select id="session" value={selected.session_id} onChange={e => onSelect(e.target.value)} disabled={busy || sessionBusy} className="min-w-0 max-w-xs flex-1 rounded-md bg-(--ground) px-2 py-2 text-sm disabled:opacity-50">{sessions.map(s => <option key={s.session_id} value={s.session_id}>{!s.title || s.title === "New conversation" ? "新会话" : s.title} · {new Date(s.updated_at).toLocaleDateString("zh-CN")}</option>)}</select><Button variant="secondary" size="sm" disabled={busy || sessionBusy} onClick={onCreate}>新会话</Button><Button variant="secondary" size="sm" disabled={chat.busy || actionBusy || sessionBusy} onClick={onReload}>刷新会话</Button><Button variant="secondary" size="sm" disabled={busy || sessionBusy} onClick={onLogout}>退出</Button></div>
    {chat.busy && <div className="flex items-center gap-3"><Button variant="secondary" size="sm" disabled={stopped} onClick={() => { setStopped(true); api.stopChat(); }}>{stopped ? "正在停止…" : "停止生成"}</Button><p className="text-xs text-(--ink-soft)">停止当前请求，不会撤销已保存的草案或已执行的变更。</p></div>}
    {stopped && !chat.busy && <Notice>当前连接已停止。请点击“刷新会话”核对服务端保存的状态；确认业务结果后再继续。</Notice>}
    {error && <p role="alert" className="text-sm text-(--danger)">{error}</p>}
    {memoryError && <p role="alert" className="text-sm text-(--danger)">记忆读取失败：{memoryError}</p>}
    {selected.status === "running" ? <Notice>此会话正在运行。完成后点击“刷新会话”恢复结果；当前暂不能发起新任务或审批。</Notice> : selected.status === "interrupted" ? <Notice>上次任务已中断。已保存的草案和执行状态已恢复，可以核对后继续提问。</Notice> : null}
    {view === "home" && <HomeView data={overview} failed={failed} error={overviewError} onAskAssistant={ask} onReview={() => setView("changes")} />}
    {view === "catalog" && <CatalogView refreshKey={refreshKey} onAskAssistant={ask} />}
    {view === "inventory" && <InventoryView refreshKey={refreshKey} onAskAssistant={ask} />}
    {view === "orders" && <OrdersView refreshKey={refreshKey} onAskAssistant={ask} />}
    {view === "marketing" && <MarketingView refreshKey={refreshKey} onAskAssistant={ask} />}
    {view === "changes" && <ChangesView refreshKey={refreshKey} onAct={busy || sessionBusy ? undefined : actOnChange} />}
  </PortalShell>{activityOpen && <Sheet title="本次连接的运行记录" onClose={() => setActivityOpen(false)} closeLabel="关闭运行记录"><p className="text-xs text-(--ink-soft)">显示当前连接内的工具调用和耗时；历史会话从聊天区恢复。</p>{chat.memory.length > 0 && <section><h3 className="font-semibold">当前身份的经营记忆</h3>{chat.memory.map(fact => <p key={fact.key} className="mt-2 text-sm">{fact.key}：{fact.value}</p>)}</section>}{chat.trace.length ? chat.trace.map((entry, i) => <details key={i} className="rounded-xl border border-(--line) p-3 text-xs"><summary className="cursor-pointer font-medium">{entry.label}{entry.elapsedMs != null ? ` · ${(entry.elapsedMs / 1000).toFixed(1)} 秒` : ""}</summary><pre className="mt-2 whitespace-pre-wrap break-all text-(--ink-soft)">{entry.detail}</pre></details>) : <p className="text-sm text-(--ink-soft)">本次连接还没有工具调用。</p>}</Sheet>}</>;
}

export default function PortalPage() {
  const [subject, setSubject] = useState<string | null>(null);
  const [sessions, setSessions] = useState<SavedSession[]>([]);
  const [selected, setSelected] = useState<SessionDetail | null>(null);
  const [revision, setRevision] = useState(0);
  const [busy, setBusy] = useState(false);
  const [turnBusy, setTurnBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const logout = useCallback(() => { api.setToken(null); setSubject(null); setSelected(null); setSessions([]); setError(null); }, []);
  useEffect(() => { api.onUnauthorized = logout; return () => { api.onUnauthorized = null; }; }, [logout]);
  async function loadSession(id: string) {
    const previous = api.session; api.session = id;
    try { const data = await api.requestJson<SessionDetail>("/session"); setSelected(data); setRevision(n => n + 1); }
    catch (e) { api.session = previous; throw e; }
  }
  async function loadSessions() { const data = await api.requestJson<{ sessions: SavedSession[] }>("/sessions"); setSessions(data.sessions); return data.sessions; }
  async function create() { const data = await api.post<{ session_id: string }>("/session"); await loadSessions(); await loadSession(data.session_id); }
  async function login(identifier: string, password: string) {
    const data = await api.post<LoginResult>("/login", { loginIdentifier: identifier, password });
    api.setToken(data.accessToken); setSubject(data.subject);
    try { const existing = await loadSessions(); if (existing.length) await loadSession(existing[0].session_id); else await create(); }
    catch (e) { setError(e instanceof Error ? e.message : UNREACHABLE); }
  }
  async function action(fn: () => Promise<void>, allowRunningRefresh = false) { if (busy || (turnBusy && !allowRunningRefresh)) return; setBusy(true); setError(null); try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : UNREACHABLE); } finally { setBusy(false); } }
  if (!subject) return <Login onLogin={login} />;
  if (!selected) return <main className="mx-auto max-w-xl space-y-4 p-8">
    <h1 className="text-xl font-semibold">{error ? "会话暂时无法恢复" : "正在打开工作台"}</h1>
    {error && <>
      <p role="alert" className="text-(--danger)">{error}</p>
      <p className="text-sm text-(--ink-soft)">旧会话引用的业务记录可能已不可用。演示数据重置后，请新建会话继续使用工作台。</p>
      <div className="flex flex-wrap gap-2">
        <Button disabled={busy} onClick={() => void action(create)}>新建会话</Button>
        <Button variant="secondary" disabled={busy} onClick={() => void action(async () => { const list = await loadSessions(); if (list.length) await loadSession(list[0].session_id); else await create(); })}>重试加载会话</Button>
        <Button variant="secondary" disabled={busy} onClick={logout}>退出</Button>
      </div>
    </>}
  </main>;
  return <Workbench key={`${selected.session_id}-${revision}`} selected={selected} subject={subject} sessions={sessions} sessionBusy={busy} error={error} onBusy={setTurnBusy} onSelect={id => void action(() => loadSession(id))} onCreate={() => void action(create)} onReload={() => void action(async () => { await loadSessions(); await loadSession(selected.session_id); }, true)} onLogout={logout} />;
}
