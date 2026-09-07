"""Build explicit buyer confirmations from unchanged, preregistered HTTP/SSE facts."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any


def _object(value: Any, label: str) -> dict:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")  # noqa: TRY004 - Confirmation rejection API.
    return value


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _integer(value: Any, label: str, *, minimum: int = 1, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise ValueError(f"{label} must be an integer within the accepted range")
    return value


def _currency(value: Any, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Z]{3}", value) is None:
        raise ValueError(f"{label} must be a three-letter uppercase currency")
    return value


def _items(value: Any, label: str) -> dict[str, tuple[int, int]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 100:
        raise ValueError(f"{label} must contain 1 to 100 items")
    result = {}
    for raw in value:
        item = _object(raw, label + " item")
        product_id = _text(item.get("productId"), "productId")
        if product_id in result:
            raise ValueError(f"{label} contains a duplicate productId")
        result[product_id] = (
            _integer(item.get("quantity"), "quantity", maximum=24),
            _integer(item.get("unitPriceMinor"), "unitPriceMinor"),
        )
    return result


def checkout_body(quote: dict, expected: dict, request_key: str) -> dict:
    """Confirm exactly the registered basket using the versions in this one cart quote."""
    quote = _object(quote, "quote")
    expected = _object(expected, "expected")
    if not isinstance(request_key, str) or re.fullmatch(r"[\x21-\x7e]{1,128}", request_key) is None:
        raise ValueError("request_key must match the buyer checkout HTTP contract")
    if quote.get("checkoutReady") is not True:
        raise ValueError("The actual cart quote is not ready for checkout")
    version = _integer(quote.get("version"), "cart version", minimum=0)
    currency = _currency(expected.get("currency"), "expected currency")
    if _currency(quote.get("currency"), "quote currency") != currency:
        raise ValueError("Cart currency differs from the registered basket")
    actual_items = _items(quote.get("items"), "quote items")
    expected_items = _items(expected.get("items"), "expected items")
    if actual_items != expected_items:
        raise ValueError(
            "The complete cart differs from the registered products, quantities or prices"
        )
    items = []
    for item in quote["items"]:
        if _currency(item.get("currency"), "item currency") != currency:
            raise ValueError("A cart item has a different currency")
        items.append(
            {
                "productId": item["productId"],
                "quantity": item["quantity"],
                "expectedProductVersion": _integer(item.get("productVersion"), "product version"),
                "expectedUnitPriceMinor": item["unitPriceMinor"],
            }
        )
    return {
        "request_key": request_key,
        "expectedCartVersion": version,
        "currency": currency,
        "items": items,
    }


def select_refund_card(events: list[dict], expected: dict, owner: str, session_id: str) -> dict:
    """Select a single consistent final refund card; never infer one from partial tool output."""
    expected = _object(expected, "expected refund")
    order_id = _text(expected.get("orderId"), "expected orderId")
    amount = _integer(expected.get("amountMinor"), "expected amountMinor")
    currency = _currency(expected.get("currency"), "expected currency")
    _text(owner, "owner")
    _text(session_id, "session_id")
    selected = None
    selected_json = None
    for event in events:
        event = _object(event, "SSE event")
        if event.get("type") != "ui":
            continue
        data = _object(event.get("data"), "final UI data")
        if data.get("component") != "refund_confirmation":
            continue
        payload = _object(data.get("payload"), "refund confirmation payload")
        action = _object(payload.get("action"), "refund action")
        _text(action.get("pendingActionId"), "pendingActionId")
        if (
            action.get("actionType") != "REFUND_REQUEST"
            or action.get("state") != "PREPARED"
            or action.get("userSubject") != owner
            or action.get("supportSessionId") != session_id
            or action.get("orderId") != order_id
            or _integer(action.get("amountMinor"), "amountMinor") != amount
            or _currency(action.get("currency"), "currency") != currency
        ):
            raise ValueError(
                "A final refund card differs from the registered action or buyer session"
            )
        # Repeated delivery may repeat a card, but must not silently replace its target or metadata.
        try:
            action_json = json.dumps(action, sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("Refund card must contain JSON data") from exc
        if selected is not None and action_json != selected_json:
            raise ValueError("Final refund cards are ambiguous or inconsistent")
        selected = action
        selected_json = action_json
    if selected is None:
        raise ValueError("No final refund confirmation card was emitted")
    return deepcopy(selected)
