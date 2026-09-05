// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

import { AgentApi, type AgentEvent, type ChatItem } from "web-shared";
import { readChatEventStream } from "web-shared/api";
import type { ListingDetailResponse, ListingsResponse, OverviewResponse } from "./types";

export const UNREACHABLE = "暂时无法连接工作台，请稍后重试。";
export interface SavedSession { session_id: string; title: string; updated_at: string; status: string; }
export interface SessionDetail { session_id: string; operator: string; items: ChatItem[]; status: string; }
export interface LoginResult { accessToken: string; tokenType: string; expiresIn: number; subject: string; }

class ShopMateApi extends AgentApi {
  private token: string | null = null;
  onUnauthorized: (() => void) | null = null;

  setToken(token: string | null) { this.token = token; if (!token) this.session = null; }
  override headers(json = false) {
    return { ...super.headers(json), ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}) };
  }

  private async checked(response: Response): Promise<Response> {
    if (response.ok) return response;
    if (response.status === 401) {
      this.setToken(null);
      this.onUnauthorized?.();
      throw new Error("登录已过期，请重新登录。");
    }
    if (response.status === 409) throw new Error("当前会话正在运行，请等待完成后重试。");
    if (response.status === 403) throw new Error("当前账号没有执行此操作的权限。");
    if (response.status === 404) throw new Error("未找到此会话或草案，请刷新列表。");
    throw new Error(`请求未完成（${response.status}），请刷新状态后重试。`);
  }

  async requestJson<T>(path: string, body?: unknown, method = "GET"): Promise<T> {
    let response: Response;
    try {
      response = await fetch(`${this.base}${path}`, { method, headers: this.headers(body !== undefined), body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store" });
    } catch { throw new Error(UNREACHABLE); }
    if (path === "/login" && response.status === 401) throw new Error("登录账号或密码不正确。");
    return (await this.checked(response)).json() as Promise<T>;
  }

  override async post<T>(path: string, body?: unknown): Promise<T> { return this.requestJson<T>(path, body, "POST"); }
  override async get<T>(path: string, params?: Record<string, string>): Promise<T | null> {
    const query = params ? `?${new URLSearchParams(params)}` : "";
    try { return await this.requestJson<T>(`${path}${query}`); } catch { return null; }
  }
  override async fetchMemory() { return []; }

  override async *chatStream(message: string): AsyncGenerator<AgentEvent> {
    let response: Response;
    try {
      response = await fetch(`${this.base}/chat`, { method: "POST", headers: this.headers(true), body: JSON.stringify({ message }) });
    } catch { throw new Error(UNREACHABLE); }
    await this.checked(response);
    if (!response.body) throw new Error(UNREACHABLE);
    yield* readChatEventStream(response.body);
  }
}

export const api = new ShopMateApi("", "/api/merchant");
export const fetchOverview = () => api.get<OverviewResponse>("/overview");
export const fetchListings = () => api.get<ListingsResponse>("/listings");
export const fetchListingDetail = (id: string) => api.get<ListingDetailResponse>(`/listings/${encodeURIComponent(id)}`);
