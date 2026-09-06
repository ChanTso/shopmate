// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

/** One entry per shopping presentation tool. */

import { type GenerativeBlockProps, UnknownBlock } from "web-shared";
import type {
  CheckoutPayload,
  ComparisonPayload,
  GuidePayload,
  OrderStatusPayload,
  PlanPayload,
  Product,
  ProductsPayload,
} from "@/lib/buyer-types";
import CheckoutSummary from "./CheckoutSummary";
import ComparisonGrid from "./ComparisonGrid";
import GuideCard from "./GuideCard";
import OrderStatusCard from "./OrderStatusCard";
import PlanChecklist from "./PlanChecklist";
import ProductCarousel from "./ProductCarousel";

export default function GenerativeBlock({
  block,
  status,
  onAdd,
  onCheckout,
  onRefundConfirm,
  disabled,
}: GenerativeBlockProps & {
  onAdd?: (product: Product) => boolean | void | Promise<boolean | void>;
  onCheckout?: () => void;
  onRefundConfirm?: (id:string) => void;
  disabled?: boolean;
}) {
  const partial = status !== "final";
  switch (block.component) {
    case "products":
      return <ProductCarousel payload={block.payload as ProductsPayload} onAdd={onAdd} partial={partial} />;
    case "comparison":
      return <ComparisonGrid payload={block.payload as ComparisonPayload} partial={partial} />;
    case "plan":
      return <PlanChecklist payload={block.payload as PlanPayload} onAdd={onAdd} partial={partial} />;
    case "guide":
      return <GuideCard payload={block.payload as GuidePayload} />;
    case "order_status":
      if (partial) return null;
      return <OrderStatusCard payload={block.payload as OrderStatusPayload} />;
    case "checkout":
      if (partial) return null;
      return <CheckoutSummary payload={block.payload as CheckoutPayload} onCheckout={onCheckout} disabled={disabled} />;
    case "refund_confirmation": {
      if (partial) return null;
      const action = (block.payload as {action:import("@/lib/buyer-types").PendingRefund}).action;
      return <section className="space-y-2 rounded-xl border-2 border-(--accent) p-4"><h3 className="font-semibold">退款申请待确认</h3><p className="break-all text-sm">订单 {action.orderId}</p><p>{action.amountMinor / 100} {action.currency} · {action.state}</p><p className="text-xs">确认前将读取服务端保存的申请；退款受理不代表资金到账。</p><button className="rounded-lg bg-(--ink) px-3 py-2 text-white disabled:opacity-50" disabled={disabled||!onRefundConfirm} onClick={()=>onRefundConfirm?.(action.pendingActionId)}>核对退款申请</button></section>;
    }
    default:
      return partial ? null : <UnknownBlock component={block.component} />;
  }
}
