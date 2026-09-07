"""Only the preregistered buyer action can become an explicit confirmation request."""

import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "retail_buyer_steps", Path(__file__).resolve().parents[1] / "scripts/retail_buyer_steps.py"
)
steps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(steps)


def basket():
    return {
        "currency": "CNY",
        "items": [
            {"productId": "tea", "quantity": 2, "unitPriceMinor": 1950},
            {"productId": "mug-blue", "quantity": 1, "unitPriceMinor": 2900},
        ],
    }


def cart_quote():
    items = [
        {
            **item,
            "name": item["productId"],
            "currency": "CNY",
            "productVersion": 17 + index,
            "stockQuantity": 20,
            "available": True,
            "publicationState": "PUBLISHED",
            "lineTotalMinor": item["quantity"] * item["unitPriceMinor"],
            "orderable": True,
            "imageUrl": None,
            "optionValues": {"color": "blue"} if index else {},
            "familyId": "mug" if index else None,
        }
        for index, item in enumerate(basket()["items"])
    ]
    return {
        "version": 9,
        "currency": "CNY",
        "subtotalMinor": 6800,
        "checkoutReady": True,
        "items": items,
    }


def test_checkout_uses_exact_basket_and_actual_versions_without_mutation():
    quote = cart_quote()
    expected = basket()
    expected["items"].reverse()
    original = deepcopy((quote, expected))
    result = steps.checkout_body(quote, expected, "checkout/registered:1")
    assert result == {
        "request_key": "checkout/registered:1",
        "expectedCartVersion": 9,
        "currency": "CNY",
        "items": [
            {
                "productId": "tea",
                "quantity": 2,
                "expectedProductVersion": 17,
                "expectedUnitPriceMinor": 1950,
            },
            {
                "productId": "mug-blue",
                "quantity": 1,
                "expectedProductVersion": 18,
                "expectedUnitPriceMinor": 2900,
            },
        ],
    }
    result["items"][0]["quantity"] = 24
    assert (quote, expected) == original


@pytest.mark.parametrize("ready", [False, None, 1, "true"])
def test_checkout_cannot_bypass_readiness(ready):
    quote = cart_quote()
    quote["checkoutReady"] = ready
    with pytest.raises(ValueError):
        steps.checkout_body(quote, basket(), "key")


@pytest.mark.parametrize("field,value", [("version", True), ("version", -1), ("version", 9.0)])
def test_checkout_cart_version_must_be_an_actual_nonnegative_integer(field, value):
    quote = cart_quote()
    quote[field] = value
    with pytest.raises(ValueError):
        steps.checkout_body(quote, basket(), "key")


@pytest.mark.parametrize(
    "field,value",
    [
        ("productId", "other"),
        ("quantity", 1),
        ("quantity", True),
        ("quantity", 2.0),
        ("quantity", 25),
        ("unitPriceMinor", 1951),
        ("unitPriceMinor", True),
        ("unitPriceMinor", 1950.0),
        ("unitPriceMinor", 0),
        ("currency", "USD"),
        ("productVersion", True),
        ("productVersion", 0),
        ("productVersion", 17.0),
    ],
)
def test_checkout_rejects_changed_or_malformed_line(field, value):
    quote = cart_quote()
    quote["items"][0][field] = value
    with pytest.raises(ValueError):
        steps.checkout_body(quote, basket(), "key")


@pytest.mark.parametrize("change", ["missing", "extra", "duplicate", "empty"])
def test_checkout_requires_the_whole_unambiguous_basket(change):
    quote = cart_quote()
    if change == "missing":
        quote["items"].pop()
    elif change == "extra":
        quote["items"].append({**quote["items"][0], "productId": "another-tea"})
    elif change == "duplicate":
        quote["items"].append(deepcopy(quote["items"][0]))
    else:
        quote["items"] = []
    with pytest.raises(ValueError):
        steps.checkout_body(quote, basket(), "key")


def test_checkout_rejects_duplicate_registered_targets_and_boolean_registered_amount():
    expected = basket()
    expected["items"].append(deepcopy(expected["items"][0]))
    with pytest.raises(ValueError):
        steps.checkout_body(cart_quote(), expected, "key")
    expected = basket()
    expected["items"][0]["unitPriceMinor"] = True
    with pytest.raises(ValueError):
        steps.checkout_body(cart_quote(), expected, "key")


@pytest.mark.parametrize("currency", [None, "USD", "cny", 1])
def test_checkout_never_translates_currency(currency):
    quote = cart_quote()
    quote["currency"] = currency
    with pytest.raises(ValueError):
        steps.checkout_body(quote, basket(), "key")


@pytest.mark.parametrize("key", ["", " ", "with space", "with\nnewline", "中文", "x" * 129, True])
def test_checkout_key_matches_the_real_http_contract(key):
    with pytest.raises(ValueError):
        steps.checkout_body(cart_quote(), basket(), key)


def refund_expected():
    return {"orderId": "order-1", "amountMinor": 100, "currency": "CNY"}


def refund_action():
    return {
        "pendingActionId": "action-1",
        "actionType": "REFUND_REQUEST",
        "userSubject": "buyer-1",
        "supportSessionId": "session-1",
        "traceId": "trace-1",
        "turnId": "turn-1",
        "requiredScope": "refund:create",
        "sandboxId": None,
        "orderId": "order-1",
        "targetVersion": 7,
        "amountMinor": 100,
        "currency": "CNY",
        "state": "PREPARED",
        "expiresAt": "2026-09-07T12:00:00Z",
        "replayed": False,
    }


def ui(action=None, *, event_type="ui"):
    return {
        "type": event_type,
        "data": {
            "component": "refund_confirmation",
            "payload": {"action": refund_action() if action is None else action},
        },
    }


def select(events, expected=None):
    return steps.select_refund_card(
        events, refund_expected() if expected is None else expected, "buyer-1", "session-1"
    )


def test_refund_selects_only_final_ui_and_accepts_identical_repeat():
    action = refund_action()
    partial_wrong = {**action, "amountMinor": 10000, "pendingActionId": "partial"}
    events = [
        ui(partial_wrong, event_type="ui_partial"),
        {"type": "tool_result", "data": {"action": partial_wrong}},
        {"type": "ui", "data": {"component": "cart", "payload": {}}},
        ui(action),
        ui(dict(reversed(list(action.items())))),
        {"type": "turn_complete", "data": {"stop_reason": "end_turn"}},
    ]
    result = select(events)
    assert result == action
    result["amountMinor"] = 200
    assert action["amountMinor"] == 100


@pytest.mark.parametrize(
    "events",
    [
        [],
        [ui(event_type="ui_partial")],
        [{"type": "tool_result", "data": {"action": refund_action()}}],
    ],
)
def test_refund_without_a_final_card_cannot_be_confirmed(events):
    with pytest.raises(ValueError):
        select(events)


@pytest.mark.parametrize(
    "field,value",
    [
        ("pendingActionId", ""),
        ("actionType", "PRICE_UPDATE"),
        ("state", "CONSUMED"),
        ("userSubject", "buyer-2"),
        ("supportSessionId", "session-2"),
        ("orderId", "order-2"),
        ("amountMinor", 10000),
        ("amountMinor", 100.0),
        ("amountMinor", True),
        ("amountMinor", 0),
        ("currency", "USD"),
        ("currency", "cny"),
    ],
)
def test_refund_rejects_wrong_or_malformed_final_card_even_with_a_valid_card(field, value):
    wrong = {**refund_action(), field: value}
    with pytest.raises(ValueError):
        select([ui(), ui(wrong)])


@pytest.mark.parametrize(
    "field,value",
    [
        ("pendingActionId", "action-2"),
        ("targetVersion", 8),
        ("expiresAt", "2026-09-07T12:01:00Z"),
        ("traceId", "trace-2"),
        ("replayed", True),
        ("targetVersion", 7.0),
    ],
)
def test_refund_rejects_multiple_ids_or_inconsistent_repeated_contents(field, value):
    with pytest.raises(ValueError):
        select([ui(), ui({**refund_action(), field: value})])


@pytest.mark.parametrize("payload", [None, {}, {"action": None}, {"action": []}])
def test_refund_malformed_final_payload_cannot_be_skipped(payload):
    event = ui()
    event["data"]["payload"] = payload
    with pytest.raises(ValueError):
        select([event, ui()])


def test_refund_registered_amount_is_not_coerced_from_boolean():
    expected = {**refund_expected(), "amountMinor": True}
    with pytest.raises(ValueError):
        select([ui({**refund_action(), "amountMinor": 1})], expected)
