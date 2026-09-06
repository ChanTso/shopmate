"""Buyer HTTP contracts; Java owns cart, order, payment and refund business truth."""

from __future__ import annotations

import hashlib
import hmac
from datetime import date, datetime
from typing import Annotated, Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError

from .commerce_client import CommerceError

Nonnegative = Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]
Positive = Annotated[StrictInt, Field(gt=0, le=9223372036854775807)]
Quantity = Annotated[StrictInt, Field(ge=1, le=24)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class RetailOption(BaseModel):
    name: str
    values: list[str]


class RetailProduct(BaseModel):
    id: str
    kind: Literal["plain", "family", "variant"]
    productId: str | None
    variantOf: str | None
    title: str
    shortDescription: str | None
    priceMinor: Nonnegative
    currency: Currency
    stockQuantity: Nonnegative
    available: StrictBool
    inStock: StrictBool
    publicationVersion: Positive | None
    metadataVersion: Nonnegative
    familyMetadataVersion: Positive | None
    content: dict[str, Any]
    options: list[RetailOption]
    optionValues: dict[str, str]
    variants: list[RetailProduct] = Field(default_factory=list)


class CartItem(BaseModel):
    productId: str
    quantity: Quantity
    name: str
    unitPriceMinor: Nonnegative
    currency: Currency
    productVersion: Positive
    stockQuantity: Nonnegative
    available: StrictBool
    publicationState: Literal["DRAFT", "PUBLISHED", "UNPUBLISHED"]
    lineTotalMinor: Nonnegative | None
    orderable: StrictBool
    imageUrl: str | None
    optionValues: dict[str, str]
    familyId: str | None


class CartView(BaseModel):
    version: Nonnegative
    currency: Currency | None
    subtotalMinor: Nonnegative | None
    checkoutReady: StrictBool
    items: list[CartItem]


class CartReceipt(BaseModel):
    key: str
    operation: Literal["ADD", "SET", "REMOVE"]
    productId: str
    beforeQuantity: Annotated[StrictInt, Field(ge=0, le=24)]
    afterQuantity: Annotated[StrictInt, Field(ge=0, le=24)]
    appliedVersion: Nonnegative


class CartResult(BaseModel):
    receipt: CartReceipt
    cart: CartView
    replayed: StrictBool


class Preferences(BaseModel):
    userId: str
    displayName: str | None
    loyaltyTier: Literal["NONE", "MEMBER"]
    defaultLocation: str | None
    preferences: dict[str, str]


class Policy(BaseModel):
    policyId: str
    title: str
    category: str | None
    content: str
    publicationVersion: Positive
    publishedAt: datetime


class QuotedDeliveryItem(BaseModel):
    productId: str
    quantity: Quantity
    unitPriceMinor: Nonnegative
    productVersion: Positive


class DeliveryOption(BaseModel):
    code: str
    method: str
    feeMinor: Nonnegative
    earliestDate: date | None
    latestDate: date | None
    readyAt: datetime | None
    location: str | None


class DeliveryEstimate(BaseModel):
    quotedAt: datetime
    configVersion: Positive
    currency: Currency
    timeZone: str
    itemSubtotalMinor: Nonnegative
    items: list[QuotedDeliveryItem]
    estimateOnly: StrictBool
    options: list[DeliveryOption]


class OrderProduct(BaseModel):
    productId: str
    name: str
    unitPriceMinor: Nonnegative
    currency: Currency
    quantity: Positive
    totalPriceMinor: Nonnegative
    productVersion: Positive | None


class PaymentFacts(BaseModel):
    attemptId: str
    state: Literal["PENDING", "SUCCEEDED", "FAILED"]
    stateVersion: Positive
    amountMinor: Nonnegative
    refundedAmountMinor: Nonnegative
    currency: Currency
    succeededAt: datetime | None


class RefundStateTotals(BaseModel):
    state: Literal["REQUESTED", "PROCESSING", "SUCCEEDED", "FAILED"]
    count: Nonnegative
    requestedAmountMinor: Nonnegative
    refundedAmountMinor: Nonnegative


class RefundFacts(BaseModel):
    reservedAmountMinor: Nonnegative
    byState: list[RefundStateTotals]


class FulfillmentFacts(BaseModel):
    method: str
    stage: Literal["PROCESSING", "PACKED", "SHIPPED", "OUT_FOR_DELIVERY", "DELIVERED"]
    promisedDeliveryAt: datetime | None
    estimatedDeliveryAt: datetime | None
    packedAt: datetime | None
    shippedAt: datetime | None
    deliveredAt: datetime | None
    delayReason: str | None
    sourceKind: str
    sourceRef: str
    observedAt: datetime


class OrderView(BaseModel):
    orderKind: Literal["STANDARD", "SECKILL"]
    orderId: str
    status: Literal["UNPAID", "PAID", "CANCELLED"]
    stateVersion: Positive
    createdAt: datetime
    unpaidDeadline: datetime | None
    product: OrderProduct
    payment: PaymentFacts | None
    refunds: RefundFacts
    fulfillment: FulfillmentFacts | None


class CheckoutView(BaseModel):
    checkoutId: str
    sourceCartVersion: Nonnegative
    currency: Currency
    totalMinor: Positive
    createdAt: datetime
    paymentStatus: Literal["UNPAID", "PARTIALLY_PAID", "PAID"]
    orders: list[OrderView]
    replayed: StrictBool


class PaymentAttempt(BaseModel):
    attemptId: str
    callbackCorrelationId: str
    orderId: str
    orderKind: Literal["STANDARD", "SECKILL"]
    amountMinor: Positive
    currency: Currency
    state: Literal["PENDING", "SUCCEEDED", "FAILED"]
    replayed: StrictBool


class PaymentCallbackResult(BaseModel):
    attemptId: str
    callbackCorrelationId: str
    orderId: str
    state: Literal["PENDING", "SUCCEEDED", "FAILED"]
    replayed: StrictBool


class PendingAction(BaseModel):
    pendingActionId: str
    actionType: Literal["REFUND_REQUEST"]
    userSubject: str
    supportSessionId: str
    traceId: str
    turnId: str
    requiredScope: Literal["refund:create"]
    sandboxId: str | None
    orderId: str
    targetVersion: Positive
    amountMinor: Positive
    currency: Currency
    state: Literal["PREPARED", "CONSUMED"]
    expiresAt: datetime
    replayed: StrictBool


class ActionReceipt(BaseModel):
    receiptId: str
    pendingActionId: str
    actionType: Literal["REFUND_REQUEST"]
    status: Literal["REQUESTED"]
    orderId: str
    refundId: str
    resourceVersion: Positive
    amountMinor: Positive
    currency: Currency
    committedAt: datetime
    replayed: StrictBool


class RequestModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductSearch(RequestModel):
    query: str | None = None
    category: str | None = None
    minPriceMinor: Nonnegative | None = None
    maxPriceMinor: Nonnegative | None = None
    minRating: Annotated[float, Field(ge=0, le=5)] | None = None
    currency: Currency | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    sort: Literal["relevance", "price_asc", "price_desc", "rating"] = "relevance"
    limit: Annotated[StrictInt, Field(ge=1, le=50)] = 20
    offset: Annotated[StrictInt, Field(ge=0, le=10000)] = 0


class DeliveryItem(RequestModel):
    productId: str
    quantity: Quantity


class DeliveryRequest(RequestModel):
    items: Annotated[list[DeliveryItem], Field(max_length=100)]


class CartAdd(RequestModel):
    productId: str
    quantity: Quantity


class CartVersion(RequestModel):
    expectedCartVersion: Nonnegative


class CartSet(CartVersion):
    quantity: Quantity


class CheckoutItem(RequestModel):
    productId: str
    quantity: Quantity
    expectedProductVersion: Positive
    expectedUnitPriceMinor: Positive


class CheckoutCommand(RequestModel):
    expectedCartVersion: Nonnegative
    currency: Currency
    items: Annotated[list[CheckoutItem], Field(min_length=1, max_length=100)]


class PaymentCommand(RequestModel):
    amountMinor: Positive
    currency: Currency


class CallbackCommand(RequestModel):
    callbackEventId: str
    callbackCorrelationId: str
    orderId: str
    amountMinor: Positive
    currency: Currency
    outcome: Literal["SUCCEEDED"]


class RefundArguments(RequestModel):
    orderId: str
    amountMinor: Positive
    currency: Currency


class RefundCommand(RequestModel):
    actionType: Literal["REFUND_REQUEST"]
    arguments: RefundArguments


ERROR_CATEGORIES = {
    "VALIDATION",
    "validation",
    "NOT_FOUND",
    "not_found",
    "AUTHENTICATION",
    "authentication",
    "AUTHORIZATION",
    "authorization",
    "IDENTITY_UNAVAILABLE",
    "identity_unavailable",
    "IDEMPOTENCY_CONFLICT",
    "idempotency_conflict",
    "VERSION_CONFLICT",
    "QUANTITY_LIMIT",
    "CART_LIMIT",
    "NOT_ORDERABLE",
    "CURRENCY_CONFLICT",
    "AMOUNT_LIMIT",
    "RETRYABLE_CONCURRENCY",
    "retryable_concurrency",
    "UNAVAILABLE",
    "unavailable",
    "DEPENDENCY_UNAVAILABLE",
    "INDETERMINATE",
    "CONFLICT",
    "INCONSISTENT_DURABLE_STATE",
    "stale_cart",
    "stale_quote",
    "insufficient_stock",
    "sku_unavailable",
    "duplicate_sku",
    "unsupported_currency",
    "amount_out_of_range",
}


class BuyerClient:
    def __init__(self, base_url: str, http_client: httpx.AsyncClient | None = None):
        self.base_url = base_url.rstrip("/")
        self.http = http_client or httpx.AsyncClient(
            timeout=15, follow_redirects=False, trust_env=False
        )
        self._owns_http = http_client is None

    async def close(self):
        if self._owns_http:
            await self.http.aclose()

    async def _request(
        self,
        method,
        path,
        token=None,
        *,
        session=None,
        key=None,
        body=None,
        params=None,
        headers=None,
    ):
        supplied = dict(headers or {})
        if token is not None:
            supplied["Authorization"] = "Bearer " + token
        if session is not None:
            supplied["X-Shopping-Session-Id"] = session
        if key is not None:
            supplied["Idempotency-Key"] = key
        request = self.http.build_request(method, self.base_url + path, json=body, params=params)
        # A shared transport must not carry another endpoint's identity or callback credential.
        for name in (
            "Authorization",
            "X-Shopping-Session-Id",
            "X-Merchant-Session-Id",
            "X-Support-Session-Id",
            "X-Eval-Sandbox-Id",
            "X-Agent-Trace-Id",
            "X-Agent-Turn-Id",
            "Idempotency-Key",
            "X-Mock-Payment-Key-Id",
            "X-Mock-Payment-Timestamp",
            "X-Mock-Payment-Signature",
        ):
            request.headers.pop(name, None)
        request.headers.update(supplied)
        try:
            response = await self.http.send(request, follow_redirects=False)
        except httpx.HTTPError:
            raise CommerceError(
                503, "COMMERCE_UNAVAILABLE", "Commerce result is unavailable"
            ) from None
        if response.status_code in (200, 201):
            try:
                return response.json()
            except ValueError:
                raise CommerceError(502, "INVALID_RESPONSE", "Invalid commerce response") from None
        category = "COMMERCE_ERROR"
        try:
            value = response.json()
        except ValueError:
            value = None
        candidate = value.get("category") if isinstance(value, dict) else None
        if isinstance(candidate, str) and candidate in ERROR_CATEGORIES:
            category = candidate
        descriptions = {
            400: "Shopping request is invalid",
            401: "Authentication required",
            403: "Shopping access denied",
            404: "Shopping resource not found",
            409: "Shopping request conflicts with current business state",
            413: "Shopping request is too large",
            422: "Shopping request cannot be fulfilled",
            429: "Shopping result is not yet confirmed",
        }
        status = response.status_code if response.status_code in descriptions else 503
        raise CommerceError(
            status, category, descriptions.get(status, "Commerce result is unavailable")
        )

    @staticmethod
    def _parse(model, value):
        try:
            return model.model_validate(value)
        except ValidationError:
            raise CommerceError(502, "INVALID_RESPONSE", "Invalid commerce response") from None

    @staticmethod
    def _body(model, value):
        try:
            return model.model_validate(value).model_dump(mode="json", exclude_none=True)
        except ValidationError:
            raise CommerceError(400, "VALIDATION", "Invalid shopping request") from None

    async def _optional(self, path, model, token, session=None, *, params=None):
        try:
            value = await self._request("GET", path, token, session=session, params=params)
        except CommerceError as error:
            if error.status_code == 404:
                return None
            raise
        return self._parse(model, value)

    def _list(self, model, value, limit=None):
        if not isinstance(value, list) or (limit is not None and len(value) > limit):
            raise CommerceError(502, "INVALID_RESPONSE", "Invalid commerce list")
        return [self._parse(model, item) for item in value]

    async def products(self, token, *, limit=20, offset=0):
        value = await self._request(
            "GET", "/api/retail/products", token, params={"limit": limit, "offset": offset}
        )
        return self._list(RetailProduct, value, limit)

    async def search_products(self, token, body):
        body = self._body(ProductSearch, body)
        value = await self._request("POST", "/api/retail/products/search", token, body=body)
        return self._list(RetailProduct, value, body["limit"])

    async def product(self, product_id, token):
        return await self._optional(
            "/api/retail/products/" + quote(product_id, safe=""), RetailProduct, token
        )

    async def cart(self, token, session):
        return self._parse(
            CartView, await self._request("GET", "/internal/shopping/cart", token, session=session)
        )

    async def cart_add(self, token, session, key, product_id, quantity):
        body = self._body(CartAdd, {"productId": product_id, "quantity": quantity})
        return self._parse(
            CartResult,
            await self._request(
                "POST", "/internal/shopping/cart/items", token, session=session, key=key, body=body
            ),
        )

    async def cart_set(self, token, session, key, product_id, quantity, expected_version):
        body = self._body(CartSet, {"quantity": quantity, "expectedCartVersion": expected_version})
        return self._parse(
            CartResult,
            await self._request(
                "PUT",
                "/internal/shopping/cart/items/" + quote(product_id, safe=""),
                token,
                session=session,
                key=key,
                body=body,
            ),
        )

    async def cart_remove(self, token, session, key, product_id, expected_version):
        version = self._body(CartVersion, {"expectedCartVersion": expected_version})[
            "expectedCartVersion"
        ]
        return self._parse(
            CartResult,
            await self._request(
                "DELETE",
                "/internal/shopping/cart/items/" + quote(product_id, safe=""),
                token,
                session=session,
                key=key,
                params={"expectedCartVersion": version},
            ),
        )

    async def cart_command(self, key, token, session):
        return await self._optional(
            "/internal/shopping/cart/commands", CartResult, token, session, params={"key": key}
        )

    async def preferences(self, token, session):
        return self._parse(
            Preferences,
            await self._request("GET", "/internal/shopping/preferences", token, session=session),
        )

    async def policies(self, query, token):
        return self._list(
            Policy,
            await self._request("GET", "/api/retail/policies", token, params={"query": query}),
        )

    async def delivery(self, items, token):
        body = self._body(DeliveryRequest, {"items": items})
        return self._parse(
            DeliveryEstimate,
            await self._request("POST", "/api/retail/fulfillment-options", token, body=body),
        )

    async def orders(self, token, session, *, limit=20):
        value = await self._request(
            "GET", "/internal/shopping/orders", token, session=session, params={"limit": limit}
        )
        return self._list(OrderView, value, limit)

    async def order(self, order_id, token, session):
        return await self._optional(
            "/internal/shopping/orders/" + quote(order_id, safe=""), OrderView, token, session
        )

    async def create_checkout(self, token, key, body, *, correlation_id=None):
        body = self._body(CheckoutCommand, body)
        headers = {"X-Correlation-Id": correlation_id} if correlation_id is not None else None
        return self._parse(
            CheckoutView,
            await self._request(
                "POST", "/api/shopping/checkouts", token, key=key, body=body, headers=headers
            ),
        )

    async def checkout(self, checkout_id, token, session):
        return await self._optional(
            "/internal/shopping/checkouts/" + quote(checkout_id, safe=""),
            CheckoutView,
            token,
            session,
        )

    async def start_payment(self, order_id, token, key, amount_minor, currency):
        body = self._body(PaymentCommand, {"amountMinor": amount_minor, "currency": currency})
        return self._parse(
            PaymentAttempt,
            await self._request(
                "POST",
                "/api/orders/" + quote(order_id, safe="") + "/mock-payment",
                token,
                key=key,
                body=body,
            ),
        )

    async def payment_callback(self, body, key, *, key_id, secret, timestamp):
        body = self._body(CallbackCommand, body)
        # This is the non-evaluation variant of Java's 13-line callback canonical string.
        canonical = "\n".join(
            [
                key_id,
                str(timestamp),
                key,
                body["callbackEventId"],
                body["callbackCorrelationId"],
                body["orderId"],
                str(body["amountMinor"]),
                body["currency"],
                body["outcome"],
                "",
                "",
                "",
                "",
            ]
        )
        signature = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        headers = {
            "X-Mock-Payment-Key-Id": key_id,
            "X-Mock-Payment-Timestamp": str(timestamp),
            "X-Mock-Payment-Signature": signature,
        }
        return self._parse(
            PaymentCallbackResult,
            await self._request(
                "POST", "/internal/mock-payments/callback", key=key, body=body, headers=headers
            ),
        )

    async def prepare_refund(self, token, session, trace_id, turn_id, body):
        body = self._body(RefundCommand, body)
        headers = {"X-Agent-Trace-Id": trace_id, "X-Agent-Turn-Id": turn_id}
        return self._parse(
            PendingAction,
            await self._request(
                "POST",
                "/internal/shopping/actions/prepare",
                token,
                session=session,
                body=body,
                headers=headers,
            ),
        )

    async def confirm_refund(self, pending_id, token, session, trace_id, turn_id):
        headers = {"X-Agent-Trace-Id": trace_id, "X-Agent-Turn-Id": turn_id}
        return self._parse(
            ActionReceipt,
            await self._request(
                "POST",
                "/internal/shopping/actions/" + quote(pending_id, safe="") + "/confirm",
                token,
                session=session,
                body={},
                headers=headers,
            ),
        )
