"""Render authoritative retail facts and receipts without a second business ledger."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from merchant_agent.changes import ChangeNotApplicable
from merchant_agent.types import (
    ActorKind,
    Campaign,
    ChangeItem,
    ChangeKind,
    InventoryAlert,
    ListingDetails,
    OrderIssue,
    PricingContext,
    StagedChange,
)
from pydantic import Field

from .commerce_client import (
    CampaignView,
    ChangeView,
    DraftItem,
    DraftView,
    InventoryView,
    IssueView,
    ListingView,
    ProductView,
)
from .product_assets import image_url


def price_minor(value: float, *, allow_zero: bool = False) -> int:
    try:
        amount = Decimal(str(value))
        if (
            not amount.is_finite()
            or amount < 0
            or (amount == 0 and not allow_zero)
            or amount.as_tuple().exponent < -2
        ):
            raise ValueError()
        minor = amount * 100
        if minor > 9223372036854775807:
            raise ValueError()
        return int(minor)
    except (ValueError, InvalidOperation):
        raise ChangeNotApplicable(
            "金额须为有效非负数（商品价格大于零），最多两位小数且不能溢出。"
        ) from None


class RetailListingDetails(ListingDetails):
    publication_version: int | None = None
    metadata_version: int = 0
    family_metadata_version: int | None = None
    publication_state: str | None = None
    price_editable: bool = False
    content: dict[str, Any] = Field(default_factory=dict)
    operations: dict[str, Any] | None = None
    window: dict[str, Any] | None = None
    refund_requested_order_pct: float | None = None
    refund_requested_order_count: int | None = None
    variants: list[RetailListingDetails] = Field(default_factory=list)


class RetailCampaign(Campaign):
    observation_period: str | None = None
    roas: float | None = None
    observation_start: str | None = None
    observation_end: str | None = None
    observation_source_kind: str | None = None
    observation_source_ref: str | None = None
    note: str = "预算是计划；花费与归因收入是带期间的观察，不与全店成交额相加。"


class RetailOrderIssue(OrderIssue):
    fulfillment: dict[str, Any] | None = None
    refund_requested_order_count: int | None = None
    window_start: str | None = None
    window_end: str | None = None
    source_kind: str
    source_ref: str


def listing(product: ListingView | ProductView) -> RetailListingDetails:
    if isinstance(product, ProductView):
        status = (
            "draft"
            if product.publicationState == "DRAFT"
            else "paused"
            if product.publicationState == "UNPUBLISHED" or not product.available
            else "out_of_stock"
            if product.stockQuantity == 0
            else "active"
        )
        return RetailListingDetails(
            listing_id=product.productId,
            title=product.name,
            status=status,
            price=product.priceMinor / 100,
            currency=product.currency,
            stock=product.stockQuantity,
            publication_version=product.publicationVersion,
            publication_state=product.publicationState,
            price_editable=product.priceEditable,
            attributes={
                "publication_version": str(product.publicationVersion),
                "price_editable": str(product.priceEditable).lower(),
                "publication_state": product.publicationState,
            },
        )
    content = product.content
    attributes = dict(content.get("attributes", {}))
    attributes.update(
        price_editable=str(product.priceEditable).lower(),
        publication_state=product.publicationState,
    )
    if product.publicationVersion is not None:
        attributes["publication_version"] = str(product.publicationVersion)
    return RetailListingDetails(
        listing_id=product.id,
        title=product.title,
        status=product.status,
        price=product.priceMinor / 100,
        currency=product.currency,
        stock=product.stockQuantity,
        category=content.get("category"),
        content_quality=product.contentQuality,
        attributes=attributes,
        image_url=image_url(product.id, content.get("imageUrl")),
        short_description=product.shortDescription,
        long_description=content.get("longDescription"),
        review_snippets=content.get("reviewHighlights", []),
        options={option.name: option.values for option in product.options},
        option_values=product.optionValues,
        variant_of=product.variantOf,
        sales_last_30d=product.salesLast30d.units,
        return_rate_pct=None,
        missing_attributes=product.operations.missingAttributes if product.operations else [],
        variants=[listing(variant) for variant in product.variants],
        publication_version=product.publicationVersion,
        metadata_version=product.metadataVersion,
        family_metadata_version=product.familyMetadataVersion,
        publication_state=product.publicationState,
        price_editable=product.priceEditable,
        content=content,
        operations=product.operations.model_dump(mode="json") if product.operations else None,
        window=product.window.model_dump(mode="json"),
        refund_requested_order_pct=product.salesLast30d.refundRequestedOrderPct,
        refund_requested_order_count=product.salesLast30d.refundRequestedOrderCount,
    )


def pricing(product: ListingView) -> PricingContext:
    cost = product.operations.unitCostMinor if product.operations else None
    return PricingContext(
        listing_id=product.id,
        current_price=product.priceMinor / 100,
        currency=product.currency,
        unit_cost=cost / 100 if cost is not None else None,
        margin_pct=product.marginPct,
        max_price_delta_pct=20,
        max_promotion_discount_pct=50,
        option_values=product.optionValues,
        variants=[pricing(v) for v in product.variants],
    )


def inventory(row: InventoryView) -> InventoryAlert:
    return InventoryAlert(
        listing_id=row.listingId,
        title=row.title,
        kind=row.kind,
        variant_of=row.variantOf,
        option_values=row.optionValues,
        stock=row.stock,
        threshold=row.threshold,
        sales_last_30d=row.salesLast30d,
        days_of_cover=row.daysOfCover,
        storefront_visible=row.storefrontVisible,
    )


def issue(row: IssueView) -> RetailOrderIssue:
    return RetailOrderIssue(
        issue_id=row.issueId,
        order_id=row.orderId,
        kind=row.kind,
        summary=row.summary,
        listing_id=row.listingId,
        buyer_message_excerpt=row.buyerMessageExcerpt,
        opened_at=row.openedAt,
        fulfillment=row.fulfillment,
        refund_requested_order_count=row.refundRequestedOrderCount,
        window_start=row.windowStart.isoformat() if row.windowStart else None,
        window_end=row.windowEnd.isoformat() if row.windowEnd else None,
        source_kind=row.sourceKind,
        source_ref=row.sourceRef,
    )


def local_timestamp(value: datetime | None) -> str | None:
    return value.astimezone(ZoneInfo("Asia/Shanghai")).isoformat() if value else None


def campaign(row: CampaignView) -> RetailCampaign:
    return RetailCampaign(
        campaign_id=row.campaignId,
        name=row.name,
        status=row.state,
        objective=row.objective,
        channel=row.channel,
        budget=row.budgetMinor / 100 if row.budgetMinor is not None else None,
        spend=row.spendMinor / 100 if row.spendMinor is not None else None,
        revenue=row.revenueMinor / 100 if row.revenueMinor is not None else None,
        currency=row.currency,
        starts=local_timestamp(row.startsAt),
        ends=local_timestamp(row.endsAt),
        roas=row.revenueMinor / row.spendMinor
        if row.spendMinor and row.revenueMinor is not None
        else None,
        observation_start=local_timestamp(row.observationStart),
        observation_end=local_timestamp(row.observationEnd),
        observation_period=(
            f"上海时间：{local_timestamp(row.observationStart)}（含）至 "
            f"{local_timestamp(row.observationEnd)}（不含）"
            if row.observationStart and row.observationEnd
            else None
        ),
        observation_source_kind=row.observationSourceKind,
        observation_source_ref=row.observationSourceRef,
    )


def change(draft: ChangeView | DraftView, operator: str) -> StagedChange:
    legacy = isinstance(draft, DraftView)
    kind = "PRICE_UPDATE" if legacy else draft.kind
    items = []
    notes = []
    if kind == "PRICE_UPDATE":
        prices = draft.items if legacy else [DraftItem.model_validate(item) for item in draft.items]
        items = [
            ChangeItem(
                target=item.productId,
                field="price",
                before=item.oldPriceMinor / 100,
                after=item.newPriceMinor / 100,
            )
            for item in prices
        ]
        notes = [f"{item.name}：草案基于商品版本 {item.expectedVersion}" for item in prices]
        targets = ", ".join(item.name for item in prices)
    else:
        for item in draft.items:
            money = item["field"] in {"promotion_price", "budget"}
            sides = {
                side: item.get(side) / 100
                if money and item.get(side) is not None
                else item.get(side)
                for side in ("before", "after")
            }
            items.append(ChangeItem(target=item["target"], field=item["field"], **sides))
        targets = ", ".join(dict.fromkeys(item.target for item in items))
    if kind == "PROMOTION":
        payload = draft.payload or {}
        notes.append(
            f"活动窗口：{payload.get('starts', '见回执')} 至 {payload.get('ends', '见回执')}；批准时实际改价，结束后不自动恢复原价。"
        )
    if kind == "CAMPAIGN":
        notes.append("保存营销计划；不表示向广告平台投放，不改变已观测花费或归因收入。")
    if draft.state == "PREPARED":
        notes.append("等待操作员点击批准按钮；批准后整批执行。")
    elif draft.state == "REJECTED":
        notes.append(f"整批未执行：{(draft.result or {}).get('reason', 'BUSINESS_CONFLICT')}。")
    labels = {
        "PRICE_UPDATE": "调价",
        "LISTING_UPDATE": "商品内容",
        "INVENTORY_ACTION": "库存与销售状态",
        "PROMOTION": "促销",
        "CAMPAIGN": "营销计划",
    }
    return StagedChange(
        change_id=draft.draftId if legacy else draft.changeId,
        kind=ChangeKind(kind.lower()),
        status={
            "PREPARED": "staged",
            "APPLIED": "applied",
            "CANCELLED": "discarded",
            "REJECTED": "rejected",
        }[draft.state],
        summary=(f"{labels[kind]}草案：" + targets)[:200],
        items=items,
        created_at=draft.createdAt,
        created_by=operator,
        created_by_kind=ActorKind.AGENT,
        applied_at=draft.resolvedAt if draft.state == "APPLIED" else None,
        applied_by=operator if draft.state == "APPLIED" else None,
        discarded_at=draft.resolvedAt if draft.state == "CANCELLED" else None,
        discarded_by=operator if draft.state == "CANCELLED" else None,
        guardrail_notes=notes,
        currency=draft.currency,
        receipt=draft.model_dump(mode="json"),
    )


def response(draft: ChangeView | DraftView, operator: str, expected_state: str) -> dict:
    return {
        "ok": draft.state == expected_state,
        "change": change(draft, operator).model_dump(mode="json"),
        "receipt": draft.model_dump(mode="json"),
    }
