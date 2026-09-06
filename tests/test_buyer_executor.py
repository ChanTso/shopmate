from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from commerce_common.skills import SkillRegistry
from commerce_common.turn import EagerDispatcher
from shopping_agent import (
    Product,
    ShoppingAgentConfig,
    ShoppingSessionContext,
    ShoppingSessionState,
)

from shopmate.auth import RequestIdentity, bind_context
from shopmate.buyer_backend import CityBuddyStorefrontBackend
from shopmate.buyer_client import CartView
from shopmate.buyer_commands import BuyerCommands
from shopmate.buyer_executor import BuyerToolExecutor
from shopmate.memory import RetailMemoryStore
from shopmate.provider import build_buyer_agent
from shopmate.sessions import SessionStore
from shopmate.settings import Settings
from tests.test_buyer_backend import Auth, Client
from tests.test_buyer_client import cart


async def test_recovered_add_at_quantity_cap_bypasses_gate_without_second_write(tmp_path):
    store = SessionStore(tmp_path / "buyer.sqlite3")
    record = store.create("buyer", role="buyer")
    turn = store.begin_turn(record)
    commands = BuyerCommands(store)
    args = {"product_id": "AR-1001", "quantity": 20}
    command = commands.register(
        session_id=record.session_id,
        owner="buyer",
        turn_id=turn,
        call_id="original",
        kind="cart",
        operation="ADD",
        arguments=args,
        body={"productId": "AR-1001", "quantity": 16},
    )
    commands.complete(command, {"receipt": {"key": command.key, "afterQuantity": 24}})
    client = Client()
    quote = cart()
    quote["items"][0]["quantity"] = 24
    quote["items"][0]["lineTotalMinor"] = 24 * quote["items"][0]["unitPriceMinor"]
    quote["subtotalMinor"] = quote["items"][0]["lineTotalMinor"]
    client.quote = CartView.model_validate(quote)
    backend = CityBuddyStorefrontBackend(Auth(), store, client, commands)
    context = ShoppingSessionContext(
        session_id=record.session_id, user_id="buyer", now=datetime.now(UTC)
    )
    state = ShoppingSessionState()
    state.remember_products([Product(product_id="AR-1001", title="Cup", price=24, currency="CNY")])
    executor = BuyerToolExecutor(
        backend=backend,
        config=ShoppingAgentConfig(),
        skills=SkillRegistry([]),
        session=context,
        state=state,
    )
    with bind_context(RequestIdentity("buyer", "token"), record.session_id, turn, role="buyer"):
        dispatcher = EagerDispatcher(executor.execute, False)
        outcomes = await dispatcher.collect(
            [SimpleNamespace(id="original", name="add_to_cart", input=args)]
        )
    assert not outcomes[0].refused and "recovered_command" in outcomes[0].result_text
    assert outcomes[0].events[0].data["cart"]["items"][0]["quantity"] == 24
    assert client.writes == []
    store.close()


def test_buyer_uses_enabled_core_and_only_refund_preparation_extension(tmp_path):
    store = SessionStore(tmp_path / "buyer.sqlite3")
    memory = RetailMemoryStore(store)
    agent = build_buyer_agent(
        Settings(), object(), SimpleNamespace(client=object()), memory_store=memory
    )
    names = {tool["name"] for tool in agent._tools}
    assert {
        "search_products",
        "get_product_details",
        "add_to_cart",
        "checkout",
        "prepare_refund",
        "save_memory",
        "recall_memories",
    } <= names
    assert not {"confirm_refund", "pay", "create_checkout"} & names
    assert agent.memory.enabled and agent.config.enable_orders and agent.config.enable_fulfillment
    assert len(agent.skills.names) == 5
    refund = next(tool for tool in agent._tools if tool["name"] == "prepare_refund")
    amount = refund["input_schema"]["properties"]["amount_minor"]
    assert amount["type"] == "integer" and amount["minimum"] == 1
    store.close()


@pytest.mark.parametrize("amount_minor", [100, 10000])
async def test_refund_tool_preserves_integer_minor_amount_through_confirmation_card(amount_minor):
    action = {
        "pendingActionId": "pending-1",
        "orderId": "order-1",
        "amountMinor": amount_minor,
        "currency": "CNY",
        "state": "PREPARED",
    }
    prepare = AsyncMock(return_value={"action": action})
    session = ShoppingSessionContext(
        session_id="buyer-session", user_id="buyer", now=datetime.now(UTC)
    )
    executor = BuyerToolExecutor(
        backend=SimpleNamespace(transactions=SimpleNamespace(prepare_refund=prepare)),
        config=ShoppingAgentConfig(),
        skills=SkillRegistry([]),
        session=session,
        state=ShoppingSessionState(),
    )
    arguments = {"order_id": "order-1", "amount_minor": amount_minor, "currency": "CNY"}
    outcomes = await EagerDispatcher(executor.execute, False).collect(
        [SimpleNamespace(id="refund-call", name="prepare_refund", input=arguments)]
    )
    prepare.assert_awaited_once_with(
        session,
        {"orderId": "order-1", "amountMinor": amount_minor, "currency": "CNY"},
        call_id="refund-call",
    )
    assert not outcomes[0].is_error
    assert outcomes[0].events[0].data == {
        "component": "refund_confirmation",
        "payload": {"action": action},
    }
    assert '"requires_user_confirmation": true' in outcomes[0].result_text


@pytest.mark.parametrize("amount_minor", [100.0, "100", True])
async def test_refund_tool_does_not_coerce_noninteger_model_amounts(amount_minor):
    prepare = AsyncMock()
    executor = BuyerToolExecutor(
        backend=SimpleNamespace(transactions=SimpleNamespace(prepare_refund=prepare)),
        config=ShoppingAgentConfig(),
        skills=SkillRegistry([]),
        session=ShoppingSessionContext(
            session_id="buyer-session", user_id="buyer", now=datetime.now(UTC)
        ),
        state=ShoppingSessionState(),
    )
    outcome = await executor.execute(
        "prepare_refund", {"order_id": "order-1", "amount_minor": amount_minor, "currency": "CNY"}
    )
    assert outcome.is_error and not outcome.events
    prepare.assert_not_awaited()
