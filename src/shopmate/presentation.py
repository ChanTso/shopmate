"""Render Java facts without creating a second price-draft state machine."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation

from merchant_agent.changes import ChangeNotApplicable
from merchant_agent.types import ActorKind, ChangeItem, ChangeKind, ListingDetails, StagedChange

from .commerce_client import DraftView, ProductView


def price_minor(value: float) -> int:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount.as_tuple().exponent < -2:
            raise ValueError()
        minor = amount * 100
        if minor > 9223372036854775807:
            raise ValueError()
        return int(minor)
    except (ValueError, InvalidOperation):
        raise ChangeNotApplicable(
            "价格必须为正数，最多两位小数，且整数分金额不能超出服务支持范围。"
        ) from None


def listing(product: ProductView) -> ListingDetails:
    status = (
        "draft"
        if product.publicationState == "DRAFT"
        else "paused"
        if product.publicationState == "UNPUBLISHED" or not product.available
        else "out_of_stock"
        if product.stockQuantity == 0
        else "active"
    )
    return ListingDetails(
        listing_id=product.productId,
        title=product.name,
        status=status,
        price=product.priceMinor / 100,
        currency=product.currency,
        stock=product.stockQuantity,
        attributes={
            "publication_version": str(product.publicationVersion),
            "price_editable": str(product.priceEditable).lower(),
            "publication_state": product.publicationState,
        },
    )


def change(draft: DraftView, operator: str) -> StagedChange:
    status = {
        "PREPARED": "staged",
        "APPLIED": "applied",
        "CANCELLED": "discarded",
        "REJECTED": "rejected",
    }[draft.state]
    notes = [f"{item.name}：草案基于商品版本 {item.expectedVersion}" for item in draft.items]
    if draft.state == "PREPARED":
        notes.append("等待操作员点击批准按钮；批准后整批执行。")
    elif draft.state == "REJECTED":
        reason = (draft.result or {}).get("reason", "BUSINESS_CONFLICT")
        notes.append(f"整批未执行：{reason}；本草案的价格均未应用。")
    return StagedChange(
        change_id=draft.draftId,
        kind=ChangeKind.PRICE_UPDATE,
        status=status,
        summary=f"{draft.currency} 调价草案：" + ", ".join(item.name for item in draft.items)[:150],
        items=[
            ChangeItem(
                target=item.productId,
                field="price",
                before=item.oldPriceMinor / 100,
                after=item.newPriceMinor / 100,
            )
            for item in draft.items
        ],
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


def response(draft: DraftView, operator: str, expected_state: str) -> dict:
    return {
        "ok": draft.state == expected_state,
        "change": change(draft, operator).model_dump(mode="json"),
        "receipt": draft.model_dump(mode="json"),
    }
