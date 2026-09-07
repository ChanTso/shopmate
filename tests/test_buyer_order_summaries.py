"""Order lists stay complete at the existing fence limit; details preserve Java facts."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from commerce_common.skills import SkillRegistry
from shopping_agent import ShoppingAgentConfig, ShoppingSessionContext, ShoppingSessionState
from shopping_agent.executor import ShoppingToolExecutor

from shopmate.buyer_backend import shopping_order
from shopmate.buyer_client import OrderView
from shopmate.buyer_executor import BuyerToolExecutor
from tests.test_buyer_client import order


def detailed_order(index):
    value = order()
    value["orderId"] = str(UUID(int=index + 1))
    value["product"]["productId"] = f"AR-{2000 + index}"
    value["product"]["name"] = (
        f"ACME historical product {index}: description with size and material"
    )
    value["payment"]["attemptId"] = str(UUID(int=index + 101))
    value["createdAt"] = "2026-08-30T11:05:00Z"
    value["payment"]["succeededAt"] = "2026-08-30T11:06:00Z"
    value["fulfillment"] = {
        "method": "shipping",
        "stage": "SHIPPED",
        "promisedDeliveryAt": "2026-09-04T10:00:00Z",
        "estimatedDeliveryAt": "2026-09-06T16:00:00Z",
        "packedAt": "2026-08-30T12:05:00Z",
        "shippedAt": "2026-08-30T15:05:00Z",
        "deliveredAt": None,
        "delayReason": "Carrier regional warehouse waiting for transfer",
        "sourceKind": "FIXTURE",
        "sourceRef": f"fulfillment-{index}",
        "observedAt": "2026-09-05T00:00:00Z",
    }
    return OrderView.model_validate(value)


def executor(kind, values):
    backend = SimpleNamespace(
        get_orders=AsyncMock(return_value=values),
        get_order=AsyncMock(
            side_effect=lambda _, identifier: next(
                (item for item in values if item.order_id == identifier), None
            )
        ),
    )
    state = ShoppingSessionState()
    result = kind(
        backend=backend,
        config=ShoppingAgentConfig(),
        skills=SkillRegistry([]),
        session=ShoppingSessionContext(session_id="buyer-session", user_id="buyer"),
        state=state,
    )
    return result, backend, state


def payload(outcome):
    assert not outcome.is_error
    assert outcome.result_text.startswith("<storefront_data>\n")
    assert outcome.result_text.endswith("\n</storefront_data>")
    return json.loads(outcome.result_text.split("\n", 1)[1].rsplit("\n", 1)[0])


async def test_nineteen_detailed_orders_truncate_old_list_but_all_recent_summaries_are_readable():
    values = [shopping_order(detailed_order(index)) for index in range(19)]
    old, _, _ = executor(ShoppingToolExecutor, values)
    previous = await old.execute("get_orders", {"limit": 20})
    with pytest.raises(json.JSONDecodeError):
        payload(previous)

    current, backend, state = executor(BuyerToolExecutor, values)
    listed = payload(await current.execute("get_orders", {"limit": 20}))
    backend.get_orders.assert_awaited_once_with(current._session, 20)
    assert [item["order_id"] for item in listed["orders"]] == [value.order_id for value in values]
    for index in (14, 15):
        target = listed["orders"][index]
        assert target["items"][0]["product_id"] == values[index].items[0].product_id
        assert target["estimated_delivery"] == values[index].estimated_delivery
        detail = payload(
            await current.execute("get_order_status", {"order_id": target["order_id"]})
        )
        assert detail["payment"]["amountMinor"] == 7500
        assert detail["refunds"]["reservedAmountMinor"] == 1000
        assert detail["fulfillment"]["delayReason"] == values[index].fulfillment["delayReason"]
        assert detail["product_snapshot"]["productId"] == target["items"][0]["product_id"]
    assert set(state.seen_products) == {value.items[0].product_id for value in values}
    assert state.seen_products[values[-1].items[0].product_id].title == values[-1].items[0].title


async def test_twenty_orders_keep_full_sku_ids_and_json_structure_with_long_escaped_titles():
    raw = [detailed_order(index) for index in range(20)]
    for index, value in enumerate(raw):
        value.product.name = '"\\' * 100
        value.product.productId = f"SKU{index:02d}-" + ('"\\' * 29)
    values = [shopping_order(value) for value in raw]
    current, _, state = executor(BuyerToolExecutor, values)
    listed = payload(await current.execute("get_orders", {"limit": 20}))
    assert len(listed["orders"]) == 20
    assert [row["items"][0]["product_id"] for row in listed["orders"]] == [
        value.product.productId for value in raw
    ]
    assert all(len(row["items"][0]["title"]) <= 60 for row in listed["orders"])
    assert all(value.title == ('"\\' * 100) for value in state.seen_products.values())


async def test_model_order_times_share_shanghai_offset_without_changing_web_java_contract():
    java = detailed_order(0)
    original_web = java.model_dump(mode="json")
    current, _, _ = executor(BuyerToolExecutor, [shopping_order(java)])
    detail = payload(await current.execute("get_order_status", {"order_id": java.orderId}))
    pairs = [
        (detail["placed_at"], java.createdAt),
        (detail["payment"]["succeededAt"], java.payment.succeededAt),
    ]
    for field in (
        "promisedDeliveryAt",
        "estimatedDeliveryAt",
        "packedAt",
        "shippedAt",
        "observedAt",
    ):
        pairs.append((detail["fulfillment"][field], getattr(java.fulfillment, field)))
    for text, source in pairs:
        parsed = datetime.fromisoformat(text)
        assert parsed.utcoffset() == timedelta(hours=8)
        assert parsed == source
    assert detail["estimated_delivery"] == detail["fulfillment"]["estimatedDeliveryAt"]
    assert detail["fulfillment"]["deliveredAt"] is None
    assert java.model_dump(mode="json") == original_web
    assert original_web["fulfillment"]["estimatedDeliveryAt"].endswith("Z")


async def test_empty_recent_orders_and_missing_detail_keep_existing_read_behavior():
    current, backend, _ = executor(BuyerToolExecutor, [])
    assert payload(await current.execute("get_orders", {}))["orders"] == []
    backend.get_orders.assert_awaited_once_with(current._session, 5)
    assert (await current.execute("get_order_status", {"order_id": "missing"})).is_error
