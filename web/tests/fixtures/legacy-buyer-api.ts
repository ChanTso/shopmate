// Retired browser client retained only to preserve its recovery contract regression tests.
// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

import { AgentApi, readChatEventStream } from "web-shared/api.ts";
import type { AgentEvent, MemoryFact } from "web-shared";
import { ApiError, checkedResponse, UNREACHABLE } from "../../lib/http.ts";
import type { ProductDetails, ProductsPage } from "../../lib/buyer-types.ts";
export { UNREACHABLE } from "../../lib/http.ts";
export interface PendingBrowserWrite { key: string; path: string; body: Record<string,unknown>; session: string; }

export class BuyerApi extends AgentApi {
  private token: string | null = null;
  private stream: AbortController | null = null;
  private pending = new Map<string,PendingBrowserWrite>();
  onUnauthorized: (() => void) | null = null;
  onReadError: ((message: string) => void) | null = null;
  page: { page_type: string; product_id?: string; query?: string } = {page_type: "home"};
  setToken(token: string | null) { this.token = token; if (!token) { this.stopChat(); this.session = null; this.pending.clear(); } }
  override headers(json = false) { return {...super.headers(json), ...(this.token ? {Authorization: `Bearer ${this.token}`} : {})}; }
  private checked(response: Response) { return checkedResponse(response, () => { this.setToken(null); this.onUnauthorized?.(); }); }
  async requestJson<T>(path: string, body?: unknown, method = "GET"): Promise<T> {
    let response: Response;
    try { response = await fetch(`${this.base}${path}`, {method, headers:this.headers(body !== undefined), body:body === undefined ? undefined : JSON.stringify(body), cache:"no-store"}); }
    catch { throw new Error(UNREACHABLE); }
    if (path === "/login" && response.status === 401) throw new Error("登录账号或密码不正确。");
    return (await this.checked(response)).json() as Promise<T>;
  }
  override async get<T>(path: string, params?: Record<string,string>): Promise<T> { return this.requestJson<T>(path + (params ? `?${new URLSearchParams(params)}` : "")); }
  override async post<T>(path: string, body?: unknown): Promise<T> { return this.requestJson<T>(path,body,"POST"); }
  override async patch<T>(path: string, body: unknown): Promise<T> { return this.requestJson<T>(path,body,"PATCH"); }
  override async delete<T>(path: string, body?: unknown): Promise<T> { return this.requestJson<T>(path,body,"DELETE"); }
  override async fetchMemory(): Promise<MemoryFact[] | null> {
    try { return (await this.get<{facts:MemoryFact[]}>("/memory")).facts; }
    catch (error) { this.onReadError?.(error instanceof Error ? error.message : UNREACHABLE); return null; }
  }
  override async editMemoryFact(key: string, value: string): Promise<MemoryFact | null> {
    try { return (await this.patch<{fact:MemoryFact}>("/memory",{key,value})).fact; }
    catch(error) { this.onReadError?.(error instanceof Error ? error.message : UNREACHABLE); return null; }
  }
  override async forgetMemoryFact(key: string): Promise<boolean> {
    try { return (await this.delete<{deleted:boolean}>("/memory",{key})).deleted; }
    catch(error) { this.onReadError?.(error instanceof Error ? error.message : UNREACHABLE); return false; }
  }
  /** Retain the exact intent when the connection cannot tell us whether Java committed. */
  async write<T>(path: string, body: Record<string,unknown>, key: string = crypto.randomUUID()): Promise<T> {
    if (!this.session) throw new Error("请先选择买家会话。");
    const previous = this.pending.get(key);
    const request = previous ?? {key,path,body:structuredClone({...body,request_key:key}),session:this.session};
    if (request.session !== this.session) throw new Error("请切回原会话后重试同一操作。");
    this.pending.set(key,request);
    try {
      const result = await this.post<T>(request.path,request.body);
      this.pending.delete(key);
      return result;
    } catch (error) {
      if (error instanceof ApiError && error.status >= 400 && error.status < 500 && !/unknown|uncertain|unavailable/.test(error.category ?? "")) this.pending.delete(key);
      throw error;
    }
  }
  pendingWrites() { return [...this.pending.values()]; }
  acknowledge(key: string) { this.pending.delete(key); }
  retryWrite<T>(key: string) { const request = this.pending.get(key); if (!request) throw new Error("本地无此请求，请从服务端操作记录恢复。"); return this.write<T>(request.path,request.body,key); }
  stopChat() { this.stream?.abort(); }
  override async *chatStream(message: string): AsyncGenerator<AgentEvent> {
    if (this.stream) throw new Error("当前会话正在运行。");
    const controller = new AbortController(); this.stream = controller;
    try {
      let response: Response;
      try { response = await fetch(`${this.base}/chat`,{method:"POST",headers:this.headers(true),body:JSON.stringify({message,page:this.page}),signal:controller.signal}); }
      catch(error) { if (controller.signal.aborted) throw error; throw new Error(UNREACHABLE); }
      await this.checked(response); if (!response.body) throw new Error(UNREACHABLE);
      yield* readChatEventStream(response.body);
    } catch(error) { if (controller.signal.aborted) throw new Error("连接已停止。已保存的购物车、订单和退款申请不会撤销，请刷新会话核对。"); throw error; }
    finally { controller.abort(); if (this.stream === controller) this.stream = null; }
  }
}
export const buyerApi = new BuyerApi("","/api/buyer");
export function fetchProduct(id: string): Promise<ProductDetails> { return buyerApi.get<{product:ProductDetails}>(`/products/${encodeURIComponent(id)}`).then(value => value.product); }
export function fetchProductsPage(query = "", offset = 0) { return buyerApi.get<ProductsPage>("/products",{query,offset:String(offset),limit:"24"}); }
