import pytest
from merchant_agent.changes import ChangeNotApplicable

from shopmate.commerce_client import DraftView, ProductView
from shopmate.presentation import change, listing, price_minor, response


def test_decimal_money_does_not_truncate_a_fractional_cent():
    assert price_minor(0.29) == 29
    assert price_minor(40.95) == 4095
    for value in (1.001, float("inf"), float("nan"), 0, -1, 1e20):
        with pytest.raises(ChangeNotApplicable):
            price_minor(value)


def test_listing_keeps_real_stock_and_editability_without_fabricated_metrics():
    product = ProductView(
        productId="limited",
        name="Limited coffee",
        priceMinor=5900,
        currency="CNY",
        publicationVersion=3,
        stockQuantity=20,
        available=True,
        publicationState="PUBLISHED",
        priceEditable=False,
    )
    value = listing(product)
    assert value.status == "active" and value.stock == 20
    assert value.attributes["price_editable"] == "false"
    assert value.attributes["publication_version"] == "3"
    assert value.sales_last_30d is None and value.return_rate_pct is None


def test_rejected_receipt_is_not_discarded_or_presented_as_applied():
    draft = DraftView.model_validate(
        {
            "draftId": "d",
            "currency": "CNY",
            "state": "REJECTED",
            "items": [
                {
                    "productId": "coffee",
                    "name": "咖啡",
                    "oldPriceMinor": 2400,
                    "newPriceMinor": 2520,
                    "currency": "CNY",
                    "expectedVersion": 3,
                }
            ],
            "result": {"status": "REJECTED", "reason": "VERSION_CONFLICT", "productId": "coffee"},
            "createdAt": "2026-09-05T00:00:00Z",
            "resolvedAt": "2026-09-05T00:01:00Z",
        }
    )
    card = change(draft, "operator")
    assert card.status == "rejected" and card.applied_at is None and card.discarded_at is None
    assert card.receipt == draft.model_dump(mode="json")
    assert card.items[0].after == 25.2 and card.margin_impact is None
    assert any("整批未执行" in note for note in card.guardrail_notes)
    assert response(draft, "operator", "APPLIED")["ok"] is False
