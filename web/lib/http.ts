export const UNREACHABLE = "暂时无法连接工作台，请稍后重试。";

export class ApiError extends Error {
  constructor(message: string, readonly status: number, readonly category: string | null) { super(message); this.name = "ApiError"; }
}

export async function checkedResponse(response: Response, unauthorized: () => void): Promise<Response> {
  if (response.ok) return response;
  if (response.status === 401) { unauthorized(); throw new ApiError("登录已过期，请重新登录。", 401, "unauthorized"); }
  let payload: Record<string, unknown> = {};
  try { payload = await response.json(); } catch { /* A non-JSON gateway error has no business category. */ }
  const detail = typeof payload?.detail === "string" ? payload.detail : typeof payload?.message === "string" ? payload.message : null;
  const category = typeof payload?.category === "string" ? payload.category : null;
  const busy = category?.toLowerCase() === "session_busy" || detail === "Session is busy";
  let message = detail?.slice(0, 600) ?? `请求未完成（${response.status}），请刷新状态后重试。`;
  if (response.status === 403) message = "当前账号没有执行此操作的权限。";
  if (response.status === 404) message = "未找到此记录，请刷新列表核对。";
  if (response.status === 409 && busy) message = "当前会话正在运行，请等待完成后重试。";
  if (category === "promotion_not_started") message = "尚未到促销开始时间，草案仍待批准。请在卡片所示开始时间之后再次批准，也可以取消此草案。";
  throw new ApiError(message, response.status, category);
}
