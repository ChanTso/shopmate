"""Narrow HTTP contract for the authoritative Java merchant service."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, ValidationError

Minor = Annotated[StrictInt, Field(gt=0, le=9223372036854775807)]


class CommerceError(Exception):
    def __init__(self, status_code: int, category: str, detail: str):
        super().__init__(detail)
        self.status_code, self.category, self.detail = status_code, category, detail


class ProductView(BaseModel):
    model_config = ConfigDict(extra="ignore")
    productId: str
    name: str
    priceMinor: Minor
    currency: Literal["CNY", "USD"]
    publicationVersion: Annotated[StrictInt, Field(ge=1)]
    stockQuantity: Annotated[StrictInt, Field(ge=0)]
    available: StrictBool
    publicationState: Literal["DRAFT", "PUBLISHED", "UNPUBLISHED"]
    priceEditable: StrictBool


class DraftItem(BaseModel):
    productId: str
    name: str
    oldPriceMinor: Minor
    newPriceMinor: Minor
    currency: Literal["CNY", "USD"]
    expectedVersion: Annotated[StrictInt, Field(ge=1)]


class DraftView(BaseModel):
    draftId: str
    currency: Literal["CNY", "USD"]
    state: Literal["PREPARED", "APPLIED", "CANCELLED", "REJECTED"]
    items: Annotated[list[DraftItem], Field(min_length=1, max_length=3)]
    result: dict[str, Any] | None
    createdAt: datetime
    resolvedAt: datetime | None


class CurrencySummary(BaseModel):
    currency: Literal["CNY", "USD"]
    orderCount: Annotated[StrictInt, Field(ge=0)]
    units: Annotated[StrictInt, Field(ge=0)]
    amountMinor: Annotated[StrictInt, Field(ge=0)]


class SummaryView(BaseModel):
    start: datetime
    end: datetime
    basis: Literal["paid_gross_before_refunds"]
    currencies: list[CurrencySummary]


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
        method: str,
        path: str,
        token: str,
        *,
        session_id: str | None = None,
        key: str | None = None,
        body: dict | None = None,
        params: dict | None = None,
        business_receipt: bool = False,
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
        if response.status_code == 200 or (business_receipt and response.status_code == 409):
            try:
                return response.json()
            except ValueError:
                raise CommerceError(502, "INVALID_RESPONSE", "Invalid commerce response") from None
        category = "COMMERCE_ERROR"
        if response.status_code in (400, 404, 409):
            try:
                value = response.json().get("category")
                if value in {
                    "VALIDATION",
                    "NOT_FOUND",
                    "PRODUCT_NOT_EDITABLE",
                    "IDEMPOTENCY_CONFLICT",
                }:
                    category = value
            except (ValueError, AttributeError):
                pass
        descriptions = {
            400: "Merchant request is invalid",
            401: "Authentication required",
            403: "Merchant access denied",
            404: "Merchant resource not found",
            409: "Merchant proposal conflicts with current business state",
        }
        status = response.status_code if response.status_code in descriptions else 503
        raise CommerceError(
            status, category, descriptions.get(status, "Commerce service unavailable")
        )

    @staticmethod
    def _parse(model, value):
        try:
            return model.model_validate(value)
        except ValidationError:
            raise CommerceError(502, "INVALID_RESPONSE", "Invalid commerce response") from None

    async def products(self, token: str, session_id: str) -> list[ProductView]:
        value = await self._request(
            "GET", "/internal/merchant/products", token, session_id=session_id
        )
        if not isinstance(value, list) or len(value) > 100:
            raise CommerceError(502, "INVALID_RESPONSE", "Invalid catalog response")
        return [self._parse(ProductView, item) for item in value]

    async def product(self, product_id: str, token: str, session_id: str) -> ProductView | None:
        try:
            value = await self._request(
                "GET",
                "/internal/merchant/products/" + quote(product_id, safe=""),
                token,
                session_id=session_id,
            )
        except CommerceError as error:
            if error.status_code == 404:
                return None
            raise
        return self._parse(ProductView, value)

    async def summary(
        self, start: datetime, end: datetime, token: str, session_id: str
    ) -> SummaryView:
        value = await self._request(
            "GET",
            "/internal/merchant/summary",
            token,
            session_id=session_id,
            params={"start": start.isoformat(), "end": end.isoformat()},
        )
        return self._parse(SummaryView, value)

    async def prepare(self, body: dict, key: str, token: str, session_id: str) -> DraftView:
        value = await self._request(
            "POST",
            "/internal/merchant/price-drafts",
            token,
            session_id=session_id,
            key=key,
            body=body,
        )
        return self._parse(DraftView, value)

    async def draft(self, draft_id: str, token: str, session_id: str) -> DraftView:
        value = await self._request(
            "GET",
            "/internal/merchant/price-drafts/" + quote(draft_id, safe=""),
            token,
            session_id=session_id,
        )
        return self._parse(DraftView, value)

    async def cancel(self, draft_id: str, token: str, session_id: str) -> DraftView:
        value = await self._request(
            "POST",
            "/internal/merchant/price-drafts/" + quote(draft_id, safe="") + "/cancel",
            token,
            session_id=session_id,
        )
        return self._parse(DraftView, value)

    async def apply(self, draft_id: str, direct_token: str) -> DraftView:
        value = await self._request(
            "POST",
            "/api/merchant/price-drafts/" + quote(draft_id, safe="") + "/apply",
            direct_token,
            business_receipt=True,
        )
        return self._parse(DraftView, value)
