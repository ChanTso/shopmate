// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0
"use client";
import type { OrderFacts, OrderStatusPayload } from "@/lib/buyer-types";
import { buyerApi } from "@/lib/buyer-api";
import { useResource } from "@/lib/use-resource";
import OrderFactsCard from "../OrderFactsCard";
export default function OrderStatusCard({payload}:{payload:OrderStatusPayload}) {
  const {data,error}=useResource(()=>buyerApi.get<{order:OrderFacts}>(`/orders/${encodeURIComponent(payload.order_id)}`),[payload.order_id]);
  return <section className="space-y-2"><h3 className="font-semibold">订单进展</h3><p className="text-sm">{payload.summary}</p>{error?<p role="alert" className="text-(--danger)">{error}</p>:data?<OrderFactsCard order={data.order}/>:<p role="status">读取订单事实…</p>}{payload.next_step&&<p className="text-sm">{payload.next_step}</p>}</section>;
}
