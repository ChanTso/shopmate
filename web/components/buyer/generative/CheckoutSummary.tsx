// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0
"use client";
import { Button,formatMoney } from "web-shared";
import type { CheckoutPayload } from "@/lib/buyer-types";
export default function CheckoutSummary({payload,onCheckout,disabled}:{payload:CheckoutPayload;onCheckout?:()=>void;disabled?:boolean}) {
  return <section data-checkout-card className="space-y-3 rounded-2xl border-2 border-(--accent) bg-(--card) p-4"><h3 className="font-semibold">核对商品后结账</h3>{payload.note&&<p className="text-sm">{payload.note}</p>}<ul className="space-y-1 text-sm">{(payload.cart?.items??[]).map(item=><li key={item.product_id} className="flex justify-between gap-2"><span>{item.title} × {item.quantity}</span><span>{item.line_total != null && (item.currency || payload.cart.currency) ? formatMoney(item.line_total,item.currency || payload.cart.currency!) : "金额不可用"}</span></li>)}</ul><p className="text-xs text-(--ink-soft)">这是会话中的购物车快照。继续后读取当前价格、库存与版本；只有你确认才创建订单。配送仅供估算，不计入商品付款。</p><Button disabled={disabled||!onCheckout} onClick={onCheckout}>读取当前报价并确认</Button></section>;
}
