// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

import type { AgentEvent, ChatItem, MemoryFact } from "web-shared";
import { AgentApi, readChatEventStream } from "web-shared/api.ts";
import type { Campaign, CampaignsResponse, ChangesResponse, InventoryResponse, ListingDetailResponse, ListingFilters, ListingsResponse, OrderIssuesResponse, OverviewResponse, Promotion, PromotionsResponse } from "./types";
import { checkedResponse, UNREACHABLE } from "./http.ts";
export { UNREACHABLE } from "./http.ts";

export interface SavedSession { session_id: string; title: string; updated_at: string; status: string; }
export interface SessionDetail { session_id: string; operator: string; items: ChatItem[]; status: string; }
export interface LoginResult { accessToken: string; tokenType: string; expiresIn: number; subject: string; }

export class ShopMateApi extends AgentApi {
  private token: string | null = null;
  private stream: AbortController | null = null;
  onUnauthorized: (() => void) | null = null;
  onReadError: ((message:string) => void) | null = null;

  setToken(token: string | null) { this.token = token; if (!token) { this.stopChat(); this.session = null; } }
  override headers(json = false) {
    return { ...super.headers(json), ...(this.token ? { Authorization: `Bearer ${this.token}` } : {}) };
  }

  private checked(response: Response): Promise<Response> {
    return checkedResponse(response, () => { this.setToken(null); this.onUnauthorized?.(); });
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
    return this.requestJson<T>(`${path}${query}`);
  }
  override async fetchMemory(): Promise<MemoryFact[] | null> {
    try { return (await this.requestJson<{facts:MemoryFact[]}>("/memory")).facts; }
    catch(error) { this.onReadError?.(error instanceof Error ? error.message : UNREACHABLE); return null; }
  }

  stopChat() { this.stream?.abort(); }

  override async *chatStream(message: string): AsyncGenerator<AgentEvent> {
    if (this.stream) throw new Error("当前会话正在运行，请等待完成后重试。");
    const controller = new AbortController();
    this.stream = controller;
    try {
      let response: Response;
      try {
        response = await fetch(`${this.base}/chat`, { method: "POST", headers: this.headers(true), body: JSON.stringify({ message }), signal: controller.signal });
      } catch (error) { if (controller.signal.aborted) throw error; throw new Error(UNREACHABLE); }
      await this.checked(response);
      if (!response.body) throw new Error(UNREACHABLE);
      yield* readChatEventStream(response.body);
    } catch (error) {
      if (controller.signal.aborted) throw new Error("已停止当前连接。已保存的业务结果不会撤销，请刷新会话核对草案与执行状态。");
      throw error;
    } finally {
      controller.abort();
      if (this.stream === controller) this.stream = null;
    }
  }
}

export const api = new ShopMateApi("", "/api/merchant");
export const fetchOverview = () => api.get<OverviewResponse>("/overview");
export const fetchListings = (query = "", offset = 0, filters: ListingFilters = {}) => api.get<ListingsResponse>("/listings", { query, limit: "24", offset: String(offset), ...filters });
export const fetchListingDetail = (id: string) => api.get<ListingDetailResponse>(`/listings/${encodeURIComponent(id)}`);

export const fetchInventory = (offset = 0) => api.get<InventoryResponse>("/inventory", { limit: "50", offset: String(offset) });
export const fetchOrderIssues = () => api.get<OrderIssuesResponse>("/order-issues", { limit: "100" });
export const fetchCampaigns = (offset = 0) => api.get<CampaignsResponse>("/campaigns", { limit: "24", offset: String(offset) });
export const fetchCampaign = (id: string) => api.get<{ campaign: Campaign }>(`/campaigns/${encodeURIComponent(id)}`);
export const fetchPromotions = (offset = 0) => api.get<PromotionsResponse>("/promotions", { limit: "24", offset: String(offset) });
export const fetchPromotion = (id: string) => api.get<{ promotion: Promotion }>(`/promotions/${encodeURIComponent(id)}`);
export const fetchChanges = (offset = 0) => api.get<ChangesResponse>("/changes", { limit: "24", offset: String(offset) });
