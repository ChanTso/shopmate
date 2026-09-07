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


@pytest.mark.parametrize("category", ["home-kitchen", None])
async def test_catalog_category_reaches_actual_host_search_and_detail_tools(tmp_path, category):
    import json

    from shopping_agent.fencing import STOREFRONT_FENCE

    from shopmate.buyer_client import RetailProduct

    store = SessionStore(tmp_path / "category.sqlite3")
    try:
        client = Client()
        source = client.products_by_id["AR-1001"].model_dump()
        source["content"]["category"] = category
        client.products_by_id["AR-1001"] = RetailProduct.model_validate(source)
        backend = CityBuddyStorefrontBackend(Auth(), store, client, BuyerCommands(store))
        session = ShoppingSessionContext(session_id="category-session", user_id="buyer")
        state = ShoppingSessionState()
        executor = BuyerToolExecutor(
            backend=backend,
            config=ShoppingAgentConfig(),
            skills=SkillRegistry([]),
            session=session,
            state=state,
        )
        with bind_context(RequestIdentity("buyer", "token"), session.session_id, role="buyer"):
            search = await executor.execute("search_products", {"query": "coffee"})
            detail = await executor.execute("get_product_details", {"product_id": "AR-1001"})
        payloads = []
        for outcome in (search, detail):
            assert not outcome.is_error
            fenced = outcome.result_text.split(STOREFRONT_FENCE.open, 1)[1]
            payloads.append(json.loads(fenced.rsplit(STOREFRONT_FENCE.close, 1)[0]))
        for product in (payloads[0]["results"][0], payloads[1]):
            if category is None:
                assert "category" not in product
            else:
                assert product["category"] == source["content"]["category"]
        assert state.seen_products["AR-1001"].category == category
        assert len(client.reads) == 2 and not client.writes
    finally:
        store.close()


async def test_empty_category_search_explains_retry_without_hidden_filter_relaxation(tmp_path):
    class FilteredClient(Client):
        async def search_products(self, token, body):
            self.reads.append(("search", dict(body), token))
            return [] if body["category"] else list(self.products_by_id.values())

    store = SessionStore(tmp_path / "empty-category.sqlite3")
    try:
        client = FilteredClient()
        backend = CityBuddyStorefrontBackend(Auth(), store, client, BuyerCommands(store))
        session = ShoppingSessionContext(session_id="empty-category-session", user_id="buyer")
        state = ShoppingSessionState()
        executor = BuyerToolExecutor(
            backend=backend,
            config=ShoppingAgentConfig(),
            skills=SkillRegistry([]),
            session=session,
            state=state,
        )
        with bind_context(RequestIdentity("buyer", "token"), session.session_id, role="buyer"):
            empty = await executor.execute(
                "search_products",
                {
                    "query": "coffee",
                    "filters": {
                        "category": "unobserved-product-type",
                        "max_price": 80,
                        "min_rating": 4,
                    },
                },
            )
            assert not empty.is_error and not state.seen_products
            assert '"result_count": 0' in empty.result_text
            assert "whose catalog values you guessed" in empty.result_text
            assert "Keep the customer's budget and hard requirements" in empty.result_text
            assert len(client.reads) == 1
            retry = await executor.execute(
                "search_products",
                {"query": "coffee", "filters": {"max_price": 80, "min_rating": 4}},
            )
        assert not retry.is_error and '"result_count": 1' in retry.result_text
        assert [read[1]["category"] for read in client.reads] == ["unobserved-product-type", None]
        assert all(read[1]["maxPriceMinor"] == 8000 for read in client.reads)
        assert all(read[1]["minRating"] == 4 for read in client.reads)
        assert state.seen_products["AR-1001"].price == 79 and not client.writes
    finally:
        store.close()
