"""Authoritative Java order facts shared by buyer and merchant HTTP clients."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictInt

Nonnegative = Annotated[StrictInt, Field(ge=0, le=9223372036854775807)]
Positive = Annotated[StrictInt, Field(gt=0, le=9223372036854775807)]
Currency = Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


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
