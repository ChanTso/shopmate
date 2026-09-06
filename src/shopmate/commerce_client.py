"""HTTP contracts for authoritative Java merchant reads and durable changes."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Generic, Literal, TypeVar
from urllib.parse import quote

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    ValidationError,
    model_validator,
)

Minor = Annotated[StrictInt, Field(gt=0, le=9223372036854775807)]
Nonnegative = Annotated[StrictInt, Field(ge=0)]
State = Literal["PREPARED", "APPLIED", "CANCELLED", "REJECTED"]
Kind = Literal["PRICE_UPDATE", "LISTING_UPDATE", "INVENTORY_ACTION", "PROMOTION", "CAMPAIGN"]
T = TypeVar("T")


class CommerceError(Exception):
    def __init__(self, status_code: int, category: str, detail: str):
        super().__init__(detail)
        self.status_code, self.category, self.detail = status_code, category, detail


class ProductView(BaseModel):
    model_config = ConfigDict(extra="ignore")
    productId: str
    name: str
    priceMinor: Nonnegative
    currency: str
    publicationVersion: Annotated[StrictInt, Field(ge=1)]
    stockQuantity: Nonnegative
    available: StrictBool
    publicationState: Literal["DRAFT", "PUBLISHED", "UNPUBLISHED"]
    priceEditable: StrictBool


class DraftItem(BaseModel):
    productId: str
    name: str
    oldPriceMinor: Nonnegative
    newPriceMinor: Minor
    currency: str
    expectedVersion: Annotated[StrictInt, Field(ge=1)]


class DraftView(BaseModel):
    """Historical SQLite receipts remain readable; new calls use ChangeView."""

    draftId: str
    currency: str
    state: State
    items: Annotated[list[DraftItem], Field(min_length=1, max_length=25)]
    result: dict[str, Any] | None
    createdAt: datetime
    resolvedAt: datetime | None


class DifferenceView(BaseModel):
    target: str
    field: str
    before: Any = None
    after: Any = None


class ChangeView(BaseModel):
    changeId: str
    kind: Kind
    state: State
    currency: str | None
    items: list[dict[str, Any]]
    payload: dict[str, Any] | None
    result: dict[str, Any] | None
    createdAt: datetime
    resolvedAt: datetime | None

    @model_validator(mode="after")
    def validate_items(self):
        if self.kind == "PRICE_UPDATE":
            if not 1 <= len(self.items) <= 25:
                raise ValueError("A price receipt requires 1..25 items")
            for item in self.items:
                DraftItem.model_validate(item)
        else:
            for item in self.items:
                DifferenceView.model_validate(item)
                if item["field"] in {"promotion_price", "budget"}:
                    for side in ("before", "after"):
                        value = item.get(side)
                        if value is not None and (type(value) is not int or value < 0):
                            raise ValueError("Money must be integer minor units")
        return self


class WindowView(BaseModel):
    start: datetime
    end: datetime
    timeZone: str


class PageView(BaseModel, Generic[T]):
    items: list[T]
    nextOffset: int | None
    window: WindowView


class OptionView(BaseModel):
    name: str
    values: list[str]


class OperationsView(BaseModel):
    unitCostMinor: Nonnegative | None
    lowStockThreshold: Nonnegative
    contentQuality: str | None
    missingAttributes: list[str]
    factsVersion: Annotated[StrictInt, Field(ge=1)]
    observedAt: datetime
    sourceRef: str


class SalesView(BaseModel):
    orderCount: Nonnegative
    units: Nonnegative
    refundRequestedOrderCount: Nonnegative
    refundRequestedOrderPct: float | None


class ListingView(BaseModel):
    id: str
    kind: Literal["plain", "family", "variant"]
    variantOf: str | None
    title: str
    shortDescription: str | None
    priceMinor: Nonnegative
    currency: str
    stockQuantity: Nonnegative
    available: StrictBool
    publicationState: str
    status: Literal["active", "paused", "draft", "out_of_stock"]
    publicationVersion: int | None
    metadataVersion: Nonnegative
    familyMetadataVersion: int | None
    content: dict[str, Any]
    options: list[OptionView]
    optionValues: dict[str, str]
    contentQuality: str | None
    operations: OperationsView | None
    salesLast30d: SalesView
    marginPct: float | None
    priceEditable: StrictBool
    window: WindowView
    variants: list[ListingView]


class InventoryView(BaseModel):
    listingId: str
    title: str
    kind: Literal["low_stock", "slow_mover"]
    variantOf: str | None
    optionValues: dict[str, str]
    stock: Nonnegative
    threshold: Nonnegative
    salesLast30d: Nonnegative
    daysOfCover: float | None
    storefrontVisible: StrictBool


class IssueView(BaseModel):
    issueId: str
    orderId: str
    kind: Literal["delayed", "return_spike", "buyer_message", "damaged"]
    summary: str
    listingId: str
    buyerMessageExcerpt: str | None
    openedAt: datetime
    fulfillment: dict[str, Any] | None
    refundRequestedOrderCount: int | None
    windowStart: datetime | None
    windowEnd: datetime | None
    sourceKind: str
    sourceRef: str


class CampaignView(BaseModel):
    campaignId: str
    name: str
    objective: str | None
    audience: str | None
    copyText: str | None
    channel: str | None
    currency: str
    budgetMinor: Nonnegative | None
    startsAt: datetime | None
    endsAt: datetime | None
    state: Literal["draft", "active", "paused", "ended"]
    version: Annotated[StrictInt, Field(ge=1)]
    createdAt: datetime
    updatedAt: datetime
    sourceChangeId: str | None
    spendMinor: Nonnegative | None
    revenueMinor: Nonnegative | None
    observationSourceKind: str | None
    observationSourceRef: str | None
    observedAt: datetime | None
    observationStart: datetime | None
    observationEnd: datetime | None
    fixtureVersion: str | None


class PromotionTargetView(BaseModel):
    productId: str
    approvedBasePriceMinor: Minor
    promotionPriceMinor: Minor
    beforeVersion: int
    afterVersion: int
    eventId: str
    currentPriceMinor: Nonnegative
    currentCurrency: str
    currentVersion: int
    overridden: StrictBool


class PromotionView(BaseModel):
    promotionId: str
    name: str
    currency: str
    discountBasisPoints: Annotated[StrictInt, Field(ge=1, le=5000)]
    startsAt: datetime
    endsAt: datetime
    state: Literal["active", "ended"]
    version: int
    createdAt: datetime
    updatedAt: datetime
    appliedAt: datetime
    sourceChangeId: str
    targets: list[PromotionTargetView]


class CurrencySummary(BaseModel):
    currency: str
    orderCount: Nonnegative
    units: Nonnegative
    amountMinor: Nonnegative


class SummaryView(BaseModel):
    start: datetime
    end: datetime
    basis: Literal["paid_gross_before_refunds"]
    currencies: list[CurrencySummary]


# Only documented business categories are persisted as definite prepare rejections.
PREPARE_REJECTIONS = frozenset(
    {
        "VALIDATION",
        "NOT_FOUND",
        "PRODUCT_NOT_EDITABLE",
        "IDEMPOTENCY_CONFLICT",
        "validation",
        "not_found",
        "not_published",
        "seckill_product",
        "shared_family_content",
        "currency_mismatch",
        "product_not_editable",
    }
)


class CommerceClient:
    def __init__(self, base_url: str, http_client: httpx.AsyncClient | None = None):
        self.base_url = base_url.rstrip("/")
        self.http = http_client or httpx.AsyncClient(timeout=15, follow_redirects=False)
        self._owns_http = http_client is None

    async def close(self):
        if self._owns_http:
            await self.http.aclose()

    async def _request(
        self,
        method,
        path,
        token,
        *,
        session_id=None,
        key=None,
        body=None,
        params=None,
        business_receipt=False,
    ):
        headers = {"Authorization": f"Bearer {token}"}
        if session_id is not None:
            headers["X-Merchant-Session-Id"] = session_id
        if key is not None:
            headers["Idempotency-Key"] = key
        try:
            response = await self.http.request(
                method, self.base_url + path, headers=headers, json=body, params=params
            )
        except httpx.HTTPError:
            raise CommerceError(
                503, "COMMERCE_UNAVAILABLE", "Commerce service unavailable"
            ) from None
        value = None
        try:
            value = response.json()
        except ValueError:
            if response.status_code == 200:
                raise CommerceError(502, "INVALID_RESPONSE", "Invalid commerce response") from None
        if response.status_code == 200:
            return value
        if (
            business_receipt
            and response.status_code == 409
            and isinstance(value, dict)
            and "changeId" in value
            and "state" in value
        ):
            return value
        category = "COMMERCE_ERROR"
        if response.status_code in (400, 404, 409) and isinstance(value, dict):
            candidate = value.get("category")
            if candidate in PREPARE_REJECTIONS | {"promotion_not_started"}:
                category = candidate
        descriptions = {
            400: "Merchant request is invalid",
            401: "Authentication required",
            403: "Merchant access denied",
            404: "Merchant resource not found",
            409: "Merchant proposal conflicts with current business state",
        }
        status = response.status_code if response.status_code in descriptions else 503
        detail = (
            "Promotion has not started; proposal remains PREPARED"
            if category == "promotion_not_started"
            else descriptions.get(status, "Commerce service unavailable")
        )
        raise CommerceError(status, category, detail)

    @staticmethod
    def _parse(model, value):
        try:
            return model.model_validate(value)
        except ValidationError:
            raise CommerceError(502, "INVALID_RESPONSE", "Invalid commerce response") from None

    async def _list(self, path, model, token, session_id, *, limit=50, offset=0, **params):
        value = await self._request(
            "GET",
            path,
            token,
            session_id=session_id,
            params={"limit": limit, "offset": offset, **params},
        )
        if not isinstance(value, list) or len(value) > limit:
            raise CommerceError(502, "INVALID_RESPONSE", "Invalid commerce page")
        return [self._parse(model, row) for row in value]

    async def _detail(self, path, model, token, session_id, *, params=None):
        try:
            value = await self._request("GET", path, token, session_id=session_id, params=params)
        except CommerceError as error:
            if error.status_code == 404:
                return None
            raise
        return self._parse(model, value)

    async def products(self, token, session_id):
        value = await self._request(
            "GET", "/internal/merchant/products", token, session_id=session_id
        )
        if not isinstance(value, list) or len(value) > 100:
            raise CommerceError(502, "INVALID_RESPONSE", "Invalid catalog response")
        return [self._parse(ProductView, row) for row in value]

    async def product(self, product_id, token, session_id):
        return await self._detail(
            "/internal/merchant/products/" + quote(product_id, safe=""),
            ProductView,
            token,
            session_id,
        )

    async def listings(self, token, session_id, **params):
        value = await self._request(
            "GET", "/internal/merchant/listings", token, session_id=session_id, params=params
        )
        return self._parse(PageView[ListingView], value)

    async def listing(self, listing_id, token, session_id, *, as_of=None):
        return await self._detail(
            "/internal/merchant/listings/" + quote(listing_id, safe=""),
            ListingView,
            token,
            session_id,
            params={"asOf": as_of.isoformat()} if as_of else None,
        )

    async def inventory(self, token, session_id, **params):
        value = await self._request(
            "GET",
            "/internal/merchant/inventory-alerts",
            token,
            session_id=session_id,
            params=params,
        )
        return self._parse(PageView[InventoryView], value)

    async def issues(self, token, session_id, *, limit=100):
        value = await self._request(
            "GET",
            "/internal/merchant/order-issues",
            token,
            session_id=session_id,
            params={"limit": limit},
        )
        if not isinstance(value, list) or len(value) > limit:
            raise CommerceError(502, "INVALID_RESPONSE", "Invalid issue response")
        return [self._parse(IssueView, row) for row in value]

    async def campaigns(self, token, session_id, *, limit=50, offset=0):
        return await self._list(
            "/internal/merchant/campaigns",
            CampaignView,
            token,
            session_id,
            limit=limit,
            offset=offset,
        )

    async def campaign(self, campaign_id, token, session_id):
        return await self._detail(
            "/internal/merchant/campaigns/" + quote(campaign_id, safe=""),
            CampaignView,
            token,
            session_id,
        )

    async def promotions(self, token, session_id, *, limit=50, offset=0):
        return await self._list(
            "/internal/merchant/promotions",
            PromotionView,
            token,
            session_id,
            limit=limit,
            offset=offset,
        )

    async def promotion(self, promotion_id, token, session_id):
        return await self._detail(
            "/internal/merchant/promotions/" + quote(promotion_id, safe=""),
            PromotionView,
            token,
            session_id,
        )

    async def summary(self, start, end, token, session_id):
        value = await self._request(
            "GET",
            "/internal/merchant/summary",
            token,
            session_id=session_id,
            params={"start": start.isoformat(), "end": end.isoformat()},
        )
        return self._parse(SummaryView, value)

    async def prepare(self, body, key, token, session_id):
        # Old persisted price intents keep the exact payload and idempotency key.
        command = body if "kind" in body else {"kind": "PRICE_UPDATE", "payload": body}
        value = await self._request(
            "POST",
            "/internal/merchant/changes",
            token,
            session_id=session_id,
            key=key,
            body=command,
        )
        return self._parse(ChangeView, value)

    async def changes(self, token, session_id, *, limit=100, offset=0, state=None):
        params = {"state": state} if state else {}
        return await self._list(
            "/internal/merchant/changes",
            ChangeView,
            token,
            session_id,
            limit=limit,
            offset=offset,
            **params,
        )

    async def draft(self, draft_id, token, session_id):
        value = await self._request(
            "GET",
            "/internal/merchant/changes/" + quote(draft_id, safe=""),
            token,
            session_id=session_id,
        )
        return self._parse(ChangeView, value)

    async def cancel(self, draft_id, token, session_id):
        value = await self._request(
            "POST",
            "/internal/merchant/changes/" + quote(draft_id, safe="") + "/cancel",
            token,
            session_id=session_id,
        )
        return self._parse(ChangeView, value)

    async def apply(self, draft_id, direct_token):
        value = await self._request(
            "POST",
            "/api/merchant/changes/" + quote(draft_id, safe="") + "/apply",
            direct_token,
            business_receipt=True,
        )
        return self._parse(ChangeView, value)
