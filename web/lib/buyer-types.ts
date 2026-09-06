// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

/** Mirrors shopping_agent/types.py and tools/presentation.py; detail extras are the vertical's api/. */

export interface Product {
  product_id: string;
  title: string;
  brand?: string | null;
  price: number;
  currency?: string;
  rating?: number | null;
  review_count?: number | null;
  image_url?: string | null;
  category?: string | null;
  labels?: string[];
  attributes?: Record<string, string>;
  in_stock?: boolean;
  short_description?: string | null;
  /** Options still to choose on a family record; the cart takes one of its variants. */
  options?: Record<string, string[]>;
  /** A variant's value for each option. */
  option_values?: Record<string, string>;
  variant_of?: string | null;
}

/** Present only when the backend provides observed source data. */
export interface PriceIntelligence {
  days: number;
  series: number[];
  low: number;
  high: number;
  position: "low" | "typical" | "high";
  verdict: string;
}

/** Present only when the backend provides observed source data. */
export interface ReviewAspects {
  review_count: number;
  aspects: { name: string; positive_pct: number; mentions: number }[];
}

export interface ProductDetails extends Product {
  variants?: Product[];
  long_description?: string | null;
  specs?: Record<string, string>;
  review_highlights?: string[];
  price_intelligence?: PriceIntelligence | null;
  review_aspects?: ReviewAspects | null;
}

export interface CartItem {
  product_id: string;
  title: string;
  price: number;
  quantity: number;
  image_url?: string | null;
  option_values?: Record<string, string>;
  variant_of?: string | null;
  line_total: number | null;
  currency?: string;
}

export interface CartPayload {
  items: CartItem[];
  item_count: number;
  subtotal: number | null;
  currency: string | null;
}

// --- Presentation payloads, as streamed after server enrichment ---

export interface ProductsPayload {
  title?: string;
  layout?: "carousel" | "grid" | "list";
  items: { product: Product; reason?: string | null }[];
}

export interface ComparisonPayload {
  title?: string;
  entries: {
    product_id: string;
    product: Product;
    pros?: string[];
    cons?: string[];
    best_for?: string | null;
  }[];
  dimensions?: string[];
  recommended_product_id?: string | null;
  // Stamped by the server: the spread between the cheapest and dearest compared items.
  price_delta?: {
    amount: number;
    low_product_id: string;
    low_price: number;
    high_product_id: string;
    high_price: number;
  };
}

export interface PlanPayload {
  title: string;
  intro?: string;
  steps: { label: string; detail?: string | null; products: Product[] }[];
}

export interface GuidePayload {
  title: string;
  sections: { heading: string; body: string }[];
  related_products?: Product[];
  sources?: string[];
}

export interface OrderStatusPayload {
  order_id: string;
  summary: string;
  next_step?: string;
  order?: {
    order_id: string;
    status: string;
    placed_at: string;
    items: { product_id: string; title: string; quantity: number; price: number }[];
    total: number;
    currency?: string;
    estimated_delivery?: string;
    tracking_url?: string;
  };
}

export interface CheckoutHandoff {
  url: string;
  label?: string;
  seller?: string;
}

export interface CheckoutPayload {
  /** Where payment happens when it is not a route in this app; filled by the backend. */
  handoffs?: CheckoutHandoff[];
  note?: string;
  fulfillment_method?: "delivery" | "pickup" | "shipping";
  cart: CartPayload;
}


/** Authoritative Java facts; display prices above are never used to construct a quote. */
export interface JavaCartItem { productId: string; quantity: number; name: string; unitPriceMinor: number; currency: string; productVersion: number; stockQuantity: number; available: boolean; publicationState: string; lineTotalMinor: number | null; orderable: boolean; imageUrl: string | null; optionValues: Record<string,string>; familyId: string | null; }
export interface JavaCart { version: number; currency: string | null; subtotalMinor: number | null; checkoutReady: boolean; items: JavaCartItem[]; }
export interface CheckoutCommand { expectedCartVersion: number; currency: string; items: { productId: string; quantity: number; expectedProductVersion: number; expectedUnitPriceMinor: number; }[]; }
export interface FulfillmentFacts { method: string; stage: string; promisedDeliveryAt: string | null; estimatedDeliveryAt: string | null; packedAt: string | null; shippedAt: string | null; deliveredAt: string | null; delayReason: string | null; sourceKind: string; sourceRef: string; observedAt: string; }
export interface OrderFacts { orderKind: string; orderId: string; status: string; stateVersion: number; createdAt: string; unpaidDeadline: string | null; product: { productId: string; name: string; unitPriceMinor: number; currency: string; quantity: number; totalPriceMinor: number; productVersion: number | null; }; payment: { attemptId: string; state: string; amountMinor: number; refundedAmountMinor: number; currency: string; succeededAt: string | null; } | null; refunds: { reservedAmountMinor: number; byState: { state: string; count: number; requestedAmountMinor: number; refundedAmountMinor: number; }[]; }; fulfillment: FulfillmentFacts | null; }
export interface CheckoutFacts { checkoutId: string; sourceCartVersion: number; currency: string; totalMinor: number; createdAt: string; paymentStatus: string; orders: OrderFacts[]; replayed: boolean; }
export interface BuyerProfile { user_id: string; display_name: string | null; loyalty_tier: string | null; default_location: string | null; preferences: Record<string,string>; }
export interface DeliveryEstimate { quotedAt: string; configVersion: number; currency: string; timeZone: string; itemSubtotalMinor: number; estimateOnly: boolean; options: { code: string; method: string; feeMinor: number; earliestDate: string | null; latestDate: string | null; readyAt: string | null; location: string | null; }[]; }
export interface PendingRefund { pendingActionId: string; orderId: string; amountMinor: number; currency: string; state: string; expiresAt: string; }
export interface RefundReceipt { receiptId: string; pendingActionId: string; orderId: string; amountMinor: number; currency: string; status: string; committedAt: string; }
export interface ProductsPage { products: Product[]; next_offset: number | null; }

export interface BuyerCommand { request_key: string; session_id?: string; kind: "cart" | "checkout" | "refund"; operation: string; body: Record<string,unknown>; state: "unknown" | "confirmed" | "rejected"; result: Record<string,unknown> | null; rejection: string | null; created_at: string; }
export interface CartResponse { cart: CartPayload; quote: JavaCart; command?: BuyerCommand; }
export interface ActionRecord { action: PendingRefund; receipt: RefundReceipt | null; }
export interface BuyerSession { session_id: string; operator: string; status: string; run_status?: string; items: import("web-shared").ChatItem[]; commands: BuyerCommand[]; checkouts: CheckoutFacts[]; actions: ActionRecord[]; }
export interface FulfillmentOption { method: string; eta: string; fee: number; currency: string; code: string; estimate_only: boolean; location: string | null; }
export interface Policy { policy_id: string; title: string; content: string; category?: string; }
