import {
  type FormEvent,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import {
  AssistantRail,
  Notice,
  type Prefill,
  type ChangeAction,
  useMerchantChat,
} from "web-shared";
import {
  BarChart3,
  Boxes,
  CircleHelp,
  ClipboardCheck,
  History,
  LogOut,
  Megaphone,
  MessageSquare,
  Package,
  Plus,
  RefreshCw,
  ShoppingBag,
  Sparkles,
  Square,
  UserRound,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import MerchantMemory from "@/components/MerchantMemory";
import AssistantPanel from "@/components/AssistantPanel";
import HomeView from "@/components/views/HomeView";
import CatalogView from "@/components/views/CatalogView";
import ChangesView from "@/components/views/ChangesView";
import InventoryView from "@/components/views/InventoryView";
import OrdersView from "@/components/views/OrdersView";
import MarketingView from "@/components/views/MarketingView";
import { useResource } from "@/lib/use-resource";
import {
  api,
  fetchOverview,
  type LoginResult,
  type SavedSession,
  type SessionDetail,
  UNREACHABLE,
} from "@/lib/api";
import { applyKnownChanges } from "@/lib/change-state";
import type { StagedChange } from "@/lib/types";

const NAV = [
  { id: "home", label: "经营概览", icon: BarChart3 },
  { id: "changes", label: "提案与审批", icon: ClipboardCheck },
  { id: "catalog", label: "商品目录", icon: ShoppingBag },
  { id: "inventory", label: "库存健康", icon: Boxes },
  { id: "orders", label: "订单与售后", icon: Package },
  { id: "marketing", label: "营销活动", icon: Megaphone },
] as const;
type View = (typeof NAV)[number]["id"];
const message = (error: unknown) =>
  error instanceof Error ? error.message : UNREACHABLE;
function StoreMark() {
  return (
    <span aria-hidden className="store-mark">
      S
    </span>
  );
}

function Login({
  onLogin,
}: {
  onLogin: (identifier: string, password: string) => Promise<void>;
}) {
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await onLogin(identifier, password);
    } catch (error) {
      setError(message(error));
    } finally {
      setPassword("");
      setBusy(false);
    }
  }
  return (
    <main className="login-page">
      <section className="login-story">
        <div className="brand-lockup">
          <StoreMark />
          <span>ShopMate</span>
        </div>
        <p className="eyebrow">MERCHANT WORKSPACE</p>
        <h1>
          看清经营，
          <br />
          从容行动。
        </h1>
        <p className="login-description">
          让数据解释变化，让助手准备方案。
          <br />
          每一次经营决策，都由你掌握。
        </p>
        <div className="login-points">
          <span>01 / 经营分析</span>
          <span>02 / 商品与库存</span>
          <span>03 / 提案与审批</span>
        </div>
      </section>
      <section className="login-form-wrap">
        <form onSubmit={submit} className="login-form">
          <p className="eyebrow">欢迎回来</p>
          <h2>登录商家工作台</h2>
          <p className="text-(--ink-soft)">使用官方商店的操作员账号。</p>
          <label>
            登录账号
            <input
              name="username"
              autoComplete="username"
              required
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
              placeholder="请输入账号"
            />
          </label>
          <label>
            密码
            <input
              name="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="请输入密码"
            />
          </label>
          {error && (
            <p role="alert" className="text-(--danger)">
              {error}
            </p>
          )}
          <Button type="submit" disabled={busy} className="h-12 w-full">
            {busy ? "登录中…" : "进入工作台"}
          </Button>
          <p className="text-xs text-(--ink-soft)">
            刷新后需重新登录。已保存的对话、提案与操作结果会保留。
          </p>
        </form>
      </section>
    </main>
  );
}

function Conversation({
  selected,
  open,
  prefill,
  sessionBusy,
  knownChanges,
  onClose,
  onAsk,
  onRefresh,
  onBusy,
  onAct,
  onReload,
}: {
  selected: SessionDetail;
  open: boolean;
  prefill: Prefill | null;
  sessionBusy: boolean;
  knownChanges: Record<string, StagedChange>;
  onClose: () => void;
  onAsk: (text: string) => void;
  onRefresh: () => void;
  onBusy: (busy: boolean) => void;
  onAct: (id: string, action: ChangeAction) => Promise<StagedChange | null>;
  onReload: () => void;
}) {
  const chat = useMerchantChat<StagedChange>(api, {
    sessionId: selected.status === "running" ? null : selected.session_id,
    initialItems: selected.items,
    unreachable: UNREACHABLE,
    onPortalRefresh: onRefresh,
  });
  const [activityOpen, setActivityOpen] = useState(false);
  const [stopped, setStopped] = useState(false);
  const [memoryError, setMemoryError] = useState<string | null>(null);
  useEffect(() => {
    api.onReadError = setMemoryError;
    return () => {
      api.onReadError = null;
    };
  }, []);
  useEffect(() => () => api.stopChat(), []);
  useEffect(() => {
    onBusy(chat.busy);
    return () => onBusy(false);
  }, [chat.busy, onBusy]);
  const send = async (text: string) => {
    if (sessionBusy) return;
    setStopped(false);
    await chat.send(text);
  };
  return (
    <>
      <AssistantRail
        open={open}
        storageKey="shopmate-panel-width"
        onClose={onClose}
      >
        {(rail) => (
          <div className="flex h-full min-h-0 flex-col bg-(--card)">
            {(chat.busy ||
              stopped ||
              selected.status === "running" ||
              selected.status === "interrupted") && (
              <div className="space-y-2 border-b border-(--line) p-3 text-xs text-(--ink-soft)">
                {chat.busy ? (
                  <Button
                    variant="outline"
                    size="sm"
                    disabled={stopped}
                    onClick={() => {
                      setStopped(true);
                      api.stopChat();
                    }}
                  >
                    <Square />
                    {stopped ? "正在停止…" : "停止生成"}
                  </Button>
                ) : (
                  <Button variant="outline" size="sm" onClick={onReload}>
                    <RefreshCw />
                    恢复保存的对话
                  </Button>
                )}
                <p>
                  {selected.status === "running"
                    ? "此对话仍在运行，稍后恢复结果。其他经营操作可以继续。"
                    : "已保存的提案和操作结果不会因断开连接而撤销。"}
                </p>
              </div>
            )}
            {memoryError && (
              <p role="alert" className="px-3 pt-3 text-xs text-(--danger)">
                记忆读取失败：{memoryError}
              </p>
            )}
            <div className="min-h-0 flex-1">
              <AssistantPanel
                chat={{
                  ...chat,
                  items: applyKnownChanges(chat.items, knownChanges),
                  send,
                  actOnChange: onAct,
                  ready: chat.ready && !sessionBusy,
                }}
                actionsDisabled={sessionBusy}
                prefill={prefill}
                onPrefill={onAsk}
                newMemoryCount={chat.newMemoryKeys.size}
                onOpenActivity={() => setActivityOpen(true)}
                {...rail}
              />
            </div>
          </div>
        )}
      </AssistantRail>
      <Dialog open={activityOpen} onOpenChange={setActivityOpen}>
        <DialogContent className="max-h-[85dvh] overflow-auto sm:max-w-2xl">
          <DialogHeader>
            <DialogTitle>运行记录</DialogTitle>
            <DialogDescription>
              当前连接的工具调用与耗时；历史结果保存在对话中。
            </DialogDescription>
          </DialogHeader>
          {memoryError ? (
            <p role="alert" className="text-(--danger)">
              {memoryError}
            </p>
          ) : (
            <MerchantMemory facts={chat.memory} onChanged={chat.reloadMemory} />
          )}
          <h3 className="font-semibold">工具调用</h3>
          {chat.trace.length ? (
            chat.trace.map((entry, index) => (
              <details key={index} className="rounded-xl border p-3 text-xs">
                <summary className="cursor-pointer font-medium">
                  {entry.label}
                  {entry.elapsedMs != null
                    ? ` · ${(entry.elapsedMs / 1000).toFixed(1)} 秒`
                    : ""}
                </summary>
                <pre className="mt-2 whitespace-pre-wrap break-all text-(--ink-soft)">
                  {entry.detail}
                </pre>
              </details>
            ))
          ) : (
            <p>本次连接还没有工具调用。</p>
          )}
        </DialogContent>
      </Dialog>
    </>
  );
}

function Workbench({
  subject,
  onLogout,
}: {
  subject: string;
  onLogout: () => void;
}) {
  const [view, setView] = useState<View>("home");
  const [assistantOpen, setAssistantOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [sessions, setSessions] = useState<SavedSession[]>([]);
  const [selected, setSelected] = useState<SessionDetail | null>(null);
  const [revision, setRevision] = useState(0);
  const [sessionBusy, setSessionBusy] = useState(false);
  const [turnBusy, setTurnBusy] = useState(false);
  const [prefill, setPrefill] = useState<Prefill | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [knownChanges, setKnownChanges] = useState<
    Record<string, StagedChange>
  >({});
  const [actionBusy, setActionBusy] = useState(false);
  const actionLock = useRef(false);
  const sessionLock = useRef(false);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
      api.stopChat();
    };
  }, []);
  const refresh = useCallback(() => setRefreshKey((v) => v + 1), []);
  const {
    data: overview,
    failed,
    error: overviewError,
  } = useResource(fetchOverview, [refreshKey]);
  async function list() {
    const data = await api.requestJson<{ sessions: SavedSession[] }>(
      "/conversations",
    );
    if (alive.current) setSessions(data.sessions);
    return data.sessions;
  }
  async function load(id: string) {
    const data = await api.requestJson<SessionDetail>(
      `/conversations/${encodeURIComponent(id)}`,
    );
    if (!alive.current) return;
    api.session = id;
    setSelected(data);
    setRevision((n) => n + 1);
  }
  async function sessionAction(action: () => Promise<void>) {
    if (sessionLock.current || turnBusy) return;
    sessionLock.current = true;
    setSessionBusy(true);
    setError(null);
    try {
      await action();
    } catch (error) {
      if (alive.current) setError(message(error));
    } finally {
      sessionLock.current = false;
      if (alive.current) setSessionBusy(false);
    }
  }
  async function create() {
    const data = await api.post<{ session_id: string }>("/conversations");
    if (!alive.current) return;
    await load(data.session_id);
    await list();
  }
  function ask(text?: string) {
    setAssistantOpen(true);
    if (text) setPrefill({ text, nonce: Date.now() });
    if (!selected) void sessionAction(create);
  }
  async function actOnChange(id: string, action: ChangeAction) {
    if (actionLock.current) throw new Error("正在提交操作，请稍后重试。");
    actionLock.current = true;
    setActionBusy(true);
    try {
      const { change } = await api.post<{ change: StagedChange | null }>(
        `/changes/${encodeURIComponent(id)}/${action}`,
      );
      if (alive.current) {
        if (change)
          setKnownChanges((values) => ({
            ...values,
            [change.change_id]: change,
          }));
        refresh();
      }
      return change;
    } finally {
      actionLock.current = false;
      if (alive.current) setActionBusy(false);
    }
  }
  const title = NAV.find((item) => item.id === view)!.label;
  return (
    <div className="merchant-shell">
      <aside className="merchant-sidebar">
        <div className="brand-lockup">
          <StoreMark />
          <div>
            <span>ShopMate</span>
            <p>官方商店 · 经营工作台</p>
          </div>
        </div>
        <nav aria-label="经营导航">
          {NAV.map((item) => (
            <button
              key={item.id}
              aria-label={item.label}
              aria-current={view === item.id ? "page" : undefined}
              onClick={() => setView(item.id)}
            >
              <item.icon size={18} />
              <span>{item.label}</span>
              {item.id === "changes" &&
                !!overview?.needs_attention.pending_changes.length && (
                  <small>
                    {overview.needs_attention.pending_changes.length}
                  </small>
                )}
            </button>
          ))}
        </nav>
        <div className="sidebar-note">
          <Sparkles size={19} />
          <h2>经营有据，行动有度</h2>
          <p>助手负责分析和准备提案，业务变更由你核对后批准。</p>
        </div>
        <button className="sidebar-help" onClick={() => setHelpOpen(true)}>
          <CircleHelp size={16} /> 工作台说明
        </button>
      </aside>
      <div className="merchant-body">
        <header className="merchant-header">
          <div>
            <h1>{title}</h1>
            <p>ShopMate 官方商店</p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="ghost"
              size="icon"
              aria-label="刷新经营数据"
              onClick={refresh}
            >
              <RefreshCw />
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label="历史对话"
              onClick={() => {
                setHistoryOpen(true);
                void sessionAction(async () => {
                  await list();
                });
              }}
            >
              <History />
            </Button>
            <Button aria-label="经营助手" onClick={() => ask()}>
              <Sparkles />
              <span className="hidden sm:inline">
                {turnBusy ? "助手正在工作" : "经营助手"}
              </span>
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" aria-label="操作员菜单">
                  <UserRound />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <p className="max-w-60 break-all px-2 py-2 text-xs text-(--ink-soft)">
                  {subject}
                </p>
                <DropdownMenuItem onClick={onLogout}>
                  <LogOut />
                  退出登录
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
        <div className="merchant-content-row">
          <main className="merchant-content">
            {error && <Notice>{error}</Notice>}
            {view === "home" && (
              <HomeView
                data={overview}
                failed={failed}
                error={overviewError}
                onAskAssistant={ask}
                onNavigate={setView}
              />
            )}
            {view === "catalog" && (
              <CatalogView refreshKey={refreshKey} onAskAssistant={ask} />
            )}
            {view === "inventory" && (
              <InventoryView refreshKey={refreshKey} onAskAssistant={ask} />
            )}
            {view === "orders" && (
              <OrdersView
                data={overview}
                failed={failed}
                error={overviewError}
                onAskAssistant={ask}
              />
            )}
            {view === "marketing" && (
              <MarketingView refreshKey={refreshKey} onAskAssistant={ask} />
            )}
            {view === "changes" && (
              <ChangesView
                refreshKey={refreshKey}
                onAct={actionBusy ? undefined : actOnChange}
              />
            )}
          </main>
          {selected && (
            <Conversation
              key={`${selected.session_id}-${revision}`}
              selected={selected}
              open={assistantOpen}
              prefill={prefill}
              sessionBusy={sessionBusy || actionBusy}
              knownChanges={knownChanges}
              onClose={() => setAssistantOpen(false)}
              onAsk={ask}
              onRefresh={refresh}
              onBusy={setTurnBusy}
              onAct={actOnChange}
              onReload={() =>
                void sessionAction(() => load(selected.session_id))
              }
            />
          )}
          {assistantOpen && !selected && (
            <aside className="conversation-start">
              <MessageSquare />
              <h2>{sessionBusy ? "正在打开助手…" : "暂时无法打开助手"}</h2>
              {!sessionBusy && (
                <Button aria-label="经营助手" onClick={() => ask()}>
                  重试
                </Button>
              )}
              <Button variant="ghost" onClick={() => setAssistantOpen(false)}>
                返回工作台
              </Button>
            </aside>
          )}
        </div>
      </div>
      <Dialog open={historyOpen} onOpenChange={setHistoryOpen}>
        <DialogContent className="max-h-[85dvh] overflow-auto">
          <DialogHeader>
            <DialogTitle>经营对话</DialogTitle>
            <DialogDescription>
              历史对话按操作员隔离，切换对话不会改变业务数据。
            </DialogDescription>
          </DialogHeader>
          <Button
            disabled={sessionBusy || turnBusy}
            onClick={() =>
              void sessionAction(async () => {
                await create();
                setPrefill(null);
                setAssistantOpen(true);
                setHistoryOpen(false);
              })
            }
          >
            <Plus />
            新建对话
          </Button>
          {error && (
            <p role="alert" className="text-sm text-(--danger)">
              {error}
            </p>
          )}
          {sessionBusy && <p>正在读取…</p>}
          {sessions.map((session) => (
            <button
              className="history-row"
              key={session.session_id}
              disabled={sessionBusy || turnBusy}
              onClick={() =>
                void sessionAction(async () => {
                  await load(session.session_id);
                  setPrefill(null);
                  setAssistantOpen(true);
                  setHistoryOpen(false);
                })
              }
            >
              <span>
                {session.title && session.title !== "New conversation"
                  ? session.title
                  : "新对话"}
              </span>
              <small>
                {new Date(session.updated_at).toLocaleString("zh-CN")}
              </small>
            </button>
          ))}
          {!sessionBusy && !sessions.length && (
            <p className="text-sm text-(--ink-soft)">还没有保存的经营对话。</p>
          )}
          {turnBusy && (
            <p className="text-sm text-(--ink-soft)">
              当前对话正在生成，完成或停止后可以切换。
            </p>
          )}
        </DialogContent>
      </Dialog>
      <Dialog open={helpOpen} onOpenChange={setHelpOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>官方商店的经营工作台</DialogTitle>
            <DialogDescription>
              一个商品目录、一个运营团队，多位顾客。
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 text-sm leading-relaxed">
            <p>
              在商品、库存和订单页面查看实时业务事实，使用经营助手分析变化、比较方案并准备提案。
            </p>
            <p>
              核对每项变更后再批准；版本冲突时重新读取，不会覆盖其他操作员的更新。已执行变更需要通过新的提案调整。
            </p>
            <p>
              顾客使用 ShopMate Android App
              购物与咨询。工作台普通操作不依赖聊天；对话停止不会撤销已提交的业务结果。
            </p>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export default function PortalPage() {
  const [subject, setSubject] = useState<string | null>(null);
  const logout = useCallback(() => {
    api.setToken(null);
    setSubject(null);
  }, []);
  useEffect(() => {
    api.onUnauthorized = logout;
    return () => {
      api.onUnauthorized = null;
    };
  }, [logout]);
  async function login(identifier: string, password: string) {
    const data = await api.post<LoginResult>("/login", {
      loginIdentifier: identifier,
      password,
    });
    api.setToken(data.accessToken);
    setSubject(data.subject);
  }
  return subject ? (
    <Workbench key={subject} subject={subject} onLogout={logout} />
  ) : (
    <Login onLogin={login} />
  );
}
