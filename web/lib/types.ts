// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

import type { OrderFacts } from "./buyer-types";

/** Mirrors merchant_agent/types.py and tools/presentation.py; overview shapes are the vertical's api/. */

// --- Listings (the operator's view of the catalog) ---

export type ListingStatus = "active" | "paused" | "draft" | "out_of_stock";
export type ContentQuality = "good" | "needs_work" | "poor";

export interface Listing {
  listing_id: string;
  title: string;
  status: ListingStatus;
  price: number;
  currency?: string;
  stock: number;
  category?: string | null;
  content_quality?: ContentQuality | null;
  attributes?: Record<string, string>;
  image_url?: string | null;
  short_description?: string | null;
  /** Options a family listing is sold by; price and stock then live on its variants. */
  options?: Record<string, string[]>;
  /** A variant's value for each option, and its family's id. */
  option_values?: Record<string, string>;
  variant_of?: string | null;
  publication_version?: number | null;
  metadata_version?: number;
  family_metadata_version?: number | null;
  price_editable?: boolean;
  publication_state?: string;
}

export interface ListingDetails extends Listing {
  long_description?: string | null;
  content?: { brand?: string; specs?: Record<string, unknown>; [key: string]: unknown };
  /** Buyer-authored; render as a quotation. */
  review_snippets?: string[];
  sales_last_30d?: number | null;
  return_rate_pct?: number | null;
  missing_attributes?: string[];
  variants?: Listing[];
  operations?: { unitCostMinor: number | null; lowStockThreshold: number; contentQuality: string | null; missingAttributes: string[]; factsVersion: number; observedAt: string; sourceRef: string } | null;
  window?: ReportingWindow;
  refund_requested_order_pct?: number | null;
}

export interface PricingContext {
  listing_id: string;
  current_price: number;
  currency?: string;
  unit_cost?: number | null;
  margin_pct?: number | null;
  min_price?: number | null;
  max_price?: number | null;
  min_price_basis?: "cost" | "policy" | null;
  demand_signal?: "rising" | "steady" | "falling" | null;
  last_changed?: string | null;
  option_values?: Record<string, string>;
  /** One context per variant when the listing is a family. */
  variants?: PricingContext[];
}

// --- Business metrics ---

export interface AlertCounts {
  low_stock?: number;
  slow_movers?: number;
  order_issues?: number | null;
  pending_changes?: number;
}

export interface BusinessSnapshot {
  period: string;
  compare_to?: string | null;
  sales: number;
  orders: number;
  units?: number;
  traffic?: number | null;
  conversion_rate?: number | null;
  average_order_value?: number | null;
  sales_change_pct?: number | null;
  orders_change_pct?: number | null;
  traffic_change_pct?: number | null;
  conversion_change_pct?: number | null;
  currency?: string;
  alerts?: AlertCounts;
  note?: string | null;
}

export interface MetricPoint {
  date: string;
  value: number;
}

export interface MetricSeries {
  metric: string;
  unit?: string | null;
  granularity?: "day" | "week" | "month";
  period?: string | null;
  segment?: string | null;
  points: MetricPoint[];
  note?: string | null;
}

// --- Inventory and order health ---

export interface InventoryAlert {
  listing_id: string;
  title: string;
  kind: "low_stock" | "slow_mover";
  /** Set when the alert is for one variant: its option values and its family's id. */
  option_values?: Record<string, string>;
  variant_of?: string | null;
  stock: number;
  threshold?: number | null;
  days_of_cover?: number | null;
  sales_last_30d?: number | null;
  storefront_visible?: boolean | null;
}

export interface OrderIssue {
  issue_id: string;
  order_id: string;
  kind: "delayed" | "return_spike" | "buyer_message" | "damaged";
  summary: string;
  listing_id?: string | null;
  /** Buyer-authored; render as a quotation. */
  buyer_message_excerpt?: string | null;
  opened_at?: string | null;
  fulfillment?: { method: string; stage: string; promisedDeliveryAt: string | null; estimatedDeliveryAt: string | null; packedAt: string | null; shippedAt: string | null; deliveredAt: string | null; delayReason: string | null; sourceKind: string; sourceRef: string; observedAt: string } | null;
  refund_requested_order_count?: number | null;
  window_start?: string | null;
  window_end?: string | null;
  source_kind?: string;
  source_ref?: string;
}

// --- Staged changes (propose → preview → approve → apply) ---

export type ChangeKind =
  | "listing_update"
  | "price_update"
  | "inventory_action"
  | "promotion"
  | "campaign";

export type ChangeStatus = "staged" | "applied" | "discarded" | "rejected";

export interface ChangeItem {
  target: string;
  field: string;
  before?: unknown;
  after?: unknown;
}

export interface DraftReceipt {
  draftId: string;
  currency: string;
  state: "PREPARED" | "APPLIED" | "CANCELLED" | "REJECTED";
  items: { productId: string; name: string; oldPriceMinor: number; newPriceMinor: number; expectedVersion: number }[];
  result?: { status: string; reason?: string; productId?: string; changes?: { productId: string; oldVersion: number; newVersion: number; eventId: string }[] } | null;
  createdAt: string;
  resolvedAt?: string | null;
}

export interface StagedChange {
  receipt?: DraftReceipt | ChangeReceipt | null;
  change_id: string;
  kind: ChangeKind;
  status: ChangeStatus;
  summary: string;
  items: ChangeItem[];
  created_at: string;
  created_by: string;
  created_by_kind?: "operator" | "agent";
  applied_at?: string | null;
  applied_by?: string | null;
  discarded_at?: string | null;
  discarded_by?: string | null;
  discarded_by_kind?: "operator" | "agent" | null;
  guardrail_notes?: string[];
  currency?: string | null;
  margin_impact?: number | null;
  /** Set only on single-listing price moves. */
  margin_before_pct?: number | null;
  margin_after_pct?: number | null;
}

// --- Portal data-plane responses ---

export interface HomeInsight {
  insight_id: string;
  kind: string;
  headline: string;
  detail?: string | null;
  prompt: string;
}

export type OverviewMetric = "sales" | "orders" | "conversion" | "average_order_value";

export interface OverviewResponse {
  snapshot: BusinessSnapshot;
  window: ReportingWindow;
  prior_window: ReportingWindow;
  needs_attention: {
    pending_changes: StagedChange[];
    low_stock: InventoryAlert[];
    slow_movers: InventoryAlert[];
    order_issues: OrderIssue[];
    order_issues_limit: number;
    order_issues_may_have_more: boolean;
  };
  /** Newest SKU orders across the store, independent of the reporting cutoff. */
  recent_orders: OrderFacts[];
  recent_changes: StagedChange[];
  trends: Record<OverviewMetric, MetricPoint[]>;
  trends_prior: Record<OverviewMetric, MetricPoint[]>;
  trend_notes: Record<OverviewMetric, string>;
  trend_notes_prior: Record<OverviewMetric, string>;
  insights?: HomeInsight[];
}

export interface ListingsResponse {
  /** Count before paging. */
  total?: number;
  listings: Listing[];
  next_offset: number | null;
  window: ReportingWindow;
}

export interface ListingDetailResponse {
  listing: ListingDetails;
  pricing: PricingContext | null;
}

export interface AlertsResponse {
  inventory: InventoryAlert[];
  order_issues: OrderIssue[];
}

// --- Presentation payloads, as streamed after server enrichment ---

export interface MetricEntry {
  metric: string;
  value?: number | null;
  unit?: string | null;
  change_pct?: number | null;
  currency?: string | null;
  note?: string | null;
  series?: MetricSeries | null;
}

export interface MetricsPayload {
  title?: string | null;
  period?: string | null;
  metrics: MetricEntry[];
  analysis?: {
    headline: string;
    findings: string[];
    caveats: string[];
    method_note?: string | null;
    table?: {
      columns: string[];
      rows: unknown[][];
      row_count: number;
      truncated: boolean;
      note?: string | null;
    };
  };
}

export interface DigestEntry {
  kind: "low_stock" | "slow_mover" | "order_issue" | "metric" | "pending_change" | "note";
  ref_id?: string | null;
  headline: string;
  why_it_matters?: string | null;
  listing?: Listing | null;
  change?: StagedChange | null;
}

export interface DigestPayload {
  title?: string | null;
  items: DigestEntry[];
}

export interface ChangePreviewPayload {
  change_id: string;
  headline?: string | null;
  note?: string | null;
  change: StagedChange;
}


export interface ReportingWindow { start: string; end: string; timeZone: string; }
export interface InventoryResponse { inventory: InventoryAlert[]; next_offset: number | null; window: ReportingWindow; }
export interface OrderIssuesResponse { order_issues: OrderIssue[]; limit: number; truncated: boolean; }
export interface ChangesResponse { changes: StagedChange[]; next_offset: number | null; }
export interface ChangeReceipt {
  changeId: string;
  kind: string;
  state: DraftReceipt["state"];
  currency: string | null;
  items: unknown[];
  payload: Record<string, unknown> | null;
  result: Record<string, unknown> | null;
  createdAt: string;
  resolvedAt?: string | null;
}
export interface Campaign {
  campaignId: string; name: string; objective: string | null; audience: string | null;
  copyText: string | null; channel: string | null; currency: string; budgetMinor: number | null;
  startsAt: string | null; endsAt: string | null; state: string; version: number;
  createdAt: string; updatedAt: string; sourceChangeId: string | null;
  spendMinor: number | null; revenueMinor: number | null;
  observationSourceKind: string | null; observationSourceRef: string | null;
  observedAt: string | null; observationStart: string | null; observationEnd: string | null;
  fixtureVersion: string | null;
}
export interface PromotionTarget {
  productId: string; approvedBasePriceMinor: number; promotionPriceMinor: number;
  beforeVersion: number; afterVersion: number; eventId: string;
  currentPriceMinor: number; currentCurrency: string; currentVersion: number; overridden: boolean;
}
export interface Promotion {
  promotionId: string; name: string; currency: string; discountBasisPoints: number;
  startsAt: string; endsAt: string; state: string; version: number;
  createdAt: string; updatedAt: string; appliedAt: string; sourceChangeId: string;
  targets: PromotionTarget[];
}
export interface CampaignsResponse { campaigns: Campaign[]; next_offset: number | null; }
export interface PromotionsResponse { promotions: Promotion[]; next_offset: number | null; }

export interface ListingFilters {
  status?: ListingStatus;
  category?: string;
  max_stock?: string;
  content_quality?: ContentQuality;
  sort?: "relevance" | "sales_desc" | "stock_asc" | "price_desc" | "price_asc";
}
