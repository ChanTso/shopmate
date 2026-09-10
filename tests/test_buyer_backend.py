import asyncio
import sqlite3
from contextlib import contextmanager
from types import SimpleNamespace

import pytest
from commerce_common.turn import ToolCallContext, current_tool_call
from fastapi import HTTPException
from shopping_agent.backend import NotOffered
from shopping_agent.gates import remember_order_items
from shopping_agent.serialization import cart_payload, cart_summary, order_payload
from shopping_agent.types import (
    Cart,
    CartItem,
    Order,
    OrderStatus,
    SearchFilters,
    ShoppingSessionContext,
    ShoppingSessionState,
)

from shopmate.auth import RequestIdentity, bind_context
from shopmate.buyer_backend import (
    CityBuddyStorefrontBackend,
    price_bound,
    shopping_cart,
    shopping_order,
)
from shopmate.buyer_client import (
    CartResult,
    CartView,
    DeliveryEstimate,
    OrderView,
    Policy,
    Preferences,
    RetailProduct,
)
from shopmate.buyer_commands import BuyerCommands
from shopmate.commerce_client import CommerceError
from shopmate.sessions import SessionStore
from tests.test_buyer_client import cart, cart_result, order, product


class Auth:
    def __init__(self):
        self.scopes = []

    async def exchange_shopping(self, identity, session, scope):
        self.scopes.append((identity.subject, session, scope))
        return "obo:" + scope


class Client:
    def __init__(self):
        self.quote = CartView.model_validate(cart())
        self.products_by_id = {"AR-1001": RetailProduct.model_validate(product())}
        self.reads = []
        self.writes = []
        self.receipts = {}
        self.failure = None
        self.on_write = None

    async def product(self, identifier, token):
        self.reads.append(("product", identifier, token))
        return self.products_by_id.get(identifier)

    async def products(self, token, limit=20, offset=0):
        self.reads.append(("products", limit, offset, token))
        return list(self.products_by_id.values())[offset : offset + limit]

    async def search_products(self, token, body):
        self.reads.append(("search", body, token))
        return list(self.products_by_id.values())[: body["limit"]]

    async def cart(self, token, session):
        self.reads.append(("cart", token, session))
        return self.quote

    async def cart_command(self, key, token, session):
        self.reads.append(("receipt", key, token, session))
        return self.receipts.get(key)

    async def _write(self, operation, key, body):
        self.writes.append((operation, key, body))
        if self.on_write:
            self.on_write(key, body)
        if self.failure is not None:
            raise self.failure
        value = CartResult.model_validate(cart_result(key, operation))
        self.receipts[key] = value
        self.quote = value.cart
        return value

    async def cart_add(self, token, session, key, product_id, quantity):
        return await self._write("ADD", key, {"productId": product_id, "quantity": quantity})

    async def cart_set(self, token, session, key, product_id, quantity, expected_version):
        return await self._write(
            "SET",
            key,
            {
                "productId": product_id,
                "quantity": quantity,
                "expectedCartVersion": expected_version,
            },
        )

    async def cart_remove(self, token, session, key, product_id, expected_version):
        return await self._write(
            "REMOVE", key, {"productId": product_id, "expectedCartVersion": expected_version}
        )

    async def preferences(self, token, session):
        return Preferences(
            userId="buyer",
            displayName=None,
            loyaltyTier="NONE",
            defaultLocation=None,
            preferences={},
        )

    async def orders(self, token, session, limit=5):
        return [OrderView.model_validate(order())]

    async def order(self, identifier, token, session):
        return OrderView.model_validate(order()) if identifier == "order-1" else None

    async def policies(self, query, token):
        return [
            Policy(
                policyId="returns",
                title="Returns",
                category="general",
                content="Published only",
                publicationVersion=3,
                publishedAt="2026-09-07T01:02:03Z",
            )
        ]

    async def delivery(self, items, token):
        self.reads.append(("delivery", items, token))
        return DeliveryEstimate(
            quotedAt="2026-09-07T01:02:03Z",
            configVersion=1,
            currency="CNY",
            timeZone="Asia/Shanghai",
            itemSubtotalMinor=7900,
            items=[],
            estimateOnly=True,
            options=[
                {
                    "code": "PICKUP",
                    "method": "pickup",
                    "feeMinor": 0,
                    "earliestDate": None,
                    "latestDate": None,
                    "readyAt": "2026-09-07T03:00:00Z",
                    "location": "Shanghai store",
                }
            ],
        )


@pytest.fixture
def environment(tmp_path):
    path = tmp_path / "sessions.sqlite3"
    store = SessionStore(path)
    record = store.create("buyer", role="buyer")
    session = ShoppingSessionContext(session_id=record.session_id, user_id="buyer")
    auth, client = Auth(), Client()
    commands = BuyerCommands(store)
    backend = CityBuddyStorefrontBackend(auth, store, client, commands)
    yield SimpleNamespace(
        path=path,
        store=store,
        session=session,
        auth=auth,
        client=client,
        commands=commands,
        backend=backend,
    )
    store.close()


@contextmanager
def bound(
    environment,
    name=None,
    arguments=None,
    call_id="call-1",
    turn="turn-1",
    role="buyer",
    subject="buyer",
):
    with bind_context(
        RequestIdentity(subject, "direct-token"), environment.session.session_id, turn, role=role
    ):
        handle = (
            current_tool_call.set(ToolCallContext(call_id, name, arguments or {})) if name else None
        )
        try:
            yield
        finally:
            if handle is not None:
                current_tool_call.reset(handle)


async def test_catalog_reads_have_complete_variant_details_and_stable_pages(environment):
    env = environment
    family = product("family") | {
        "kind": "family",
        "productId": None,
        "publicationVersion": None,
        "options": [{"name": "size", "values": ["M"]}],
        "content": {
            "brand": "Actual brand",
            "attributes": {"material": "cotton"},
            "specs": {"care": "hand wash"},
        },
        "variants": [
            product("variant")
            | {"kind": "variant", "variantOf": "family", "optionValues": {"size": "M"}}
        ],
    }
    env.client.products_by_id["family"] = RetailProduct.model_validate(family)
    with bound(env):
        first = await env.backend.products_page(env.session, limit=1)
        second = await env.backend.products_page(env.session, limit=1, offset=1)
        end = await env.backend.products_page(env.session, limit=1, offset=2)
        details = await env.backend.get_product_details(env.session, "family")
        values = await env.backend.search_products(
            env.session,
            "cotton",
            SearchFilters(min_price=1.001, max_price=99.999, sort="price_asc"),
        )
    assert first["next_offset"] == 1 and second["next_offset"] == 2 and end["next_offset"] is None
    assert details.options == {"size": ["M"]} and details.variants[0].variant_of == "family"
    assert details.attributes == {"material": "cotton"} and details.specs == {"care": "hand wash"}
    body = env.client.reads[-1][1]
    assert (
        body["minPriceMinor"] == 101 and body["maxPriceMinor"] == 9999 and body["currency"] == "CNY"
    )
    assert values[0].currency == "CNY" and not env.auth.scopes


def test_cart_unknown_total_is_not_rounded_or_given_a_fake_currency():
    value = cart()
    value.update(currency=None, subtotalMinor=None, checkoutReady=False)
    value["items"][0].update(orderable=False, lineTotalMinor=None)
    result = shopping_cart(CartView.model_validate(value))
    payload = cart_payload(result)
    assert payload["currency"] is None and payload["subtotal"] is None
    assert payload["items"][0]["line_total"] is None
    assert "subtotal unavailable" in cart_summary(result)
    normal = Cart(
        currency="CNY", items=[CartItem(product_id="p", title="P", price=12.5, quantity=2)]
    )
    assert cart_summary(normal) == "2 item(s), subtotal 25.00 CNY"


def test_payment_only_order_is_not_falsely_marked_shipped_and_reorder_keeps_currency():
    raw = order()
    value = shopping_order(OrderView.model_validate(raw))
    assert value.status == OrderStatus.PAID and value.fulfillment is None
    assert value.tracking_url is None and value.items[0].price == 75
    assert order_payload(value)["payment"]["amountMinor"] == 7500
    state = ShoppingSessionState()
    remember_order_items(state, [value])
    assert state.seen_products["AR-1001"].currency == "CNY"
    assert Order.model_validate(value.model_dump()).status == OrderStatus.PAID
    raw.update(status="UNPAID", payment=None)
    assert shopping_order(OrderView.model_validate(raw)).status == OrderStatus.UNPAID
    raw.update(
        status="PAID",
        fulfillment={
            "method": "DELIVERY",
            "stage": "SHIPPED",
            "promisedDeliveryAt": None,
            "estimatedDeliveryAt": "2026-09-08T01:00:00Z",
            "packedAt": None,
            "shippedAt": "2026-09-07T01:00:00Z",
            "deliveredAt": None,
            "delayReason": None,
            "sourceKind": "fixture",
            "sourceRef": "shipment",
            "observedAt": "2026-09-07T01:00:00Z",
        },
    )
    value = shopping_order(OrderView.model_validate(raw))
    assert value.status == OrderStatus.SHIPPED
    assert value.estimated_delivery == "2026-09-08T09:00:00+08:00" and value.tracking_url is None


async def test_tool_command_is_committed_before_java_and_same_call_replays_current_cart(
    environment,
):
    env = environment
    observed = []

    def check_committed(key, body):
        with sqlite3.connect(env.path) as db:
            row = db.execute("SELECT request_key,operation,body FROM buyer_commands").fetchone()
        assert row[0] == key and row[1] == "ADD"
        observed.append(body)

    env.client.on_write = check_committed
    args = {"product_id": "AR-1001", "quantity": 24, "status": "Working"}
    with bound(env, "add_to_cart", args):
        await env.backend.add_to_cart(env.session, "AR-1001", 3)
        env.client.quote = CartView(
            version=9, currency=None, subtotalMinor=0, checkoutReady=False, items=[]
        )
        current = await env.backend.add_to_cart(env.session, "AR-1001", 3)
    command = env.commands.by_call(env.session.session_id, "buyer", "turn-1", "call-1")
    assert command.arguments == {"product_id": "AR-1001", "quantity": 24}
    assert command.body == {"productId": "AR-1001", "quantity": 3}
    assert observed == [{"productId": "AR-1001", "quantity": 3}] and not current.items
    assert command.result["receipt"]["appliedVersion"] == 5
    with (
        bound(env, "add_to_cart", {"product_id": "AR-1001", "quantity": 1}),
        pytest.raises(HTTPException) as error,
    ):
        await env.backend.add_to_cart(env.session, "AR-1001", 1)
    assert error.value.status_code == 409 and len(env.client.writes) == 1


async def test_unknown_write_restore_is_get_only_and_explicit_retry_keeps_original_version(
    environment,
):
    env = environment
    env.client.failure = CommerceError(503, "COMMERCE_UNAVAILABLE", "Unconfirmed")
    with (
        bound(env, "update_cart_item", {"product_id": "AR-1001", "quantity": 2}),
        pytest.raises(CommerceError),
    ):
        await env.backend.update_cart_item(env.session, "AR-1001", 2)
    command = env.commands.unknown_cart("buyer")[0]
    assert command.body["expectedCartVersion"] == 5
    env.client.quote.version = 9
    with bound(env):
        result = await env.backend.command_envelope(env.session, command.key)
        assert result["command"]["state"] == "unknown"
        assert len(env.client.writes) == 1
        env.client.failure = None
        result = await env.backend.command_envelope(env.session, command.key, retry=True)
    assert len(env.client.writes) == 2
    assert env.client.writes[1][1] == command.key
    assert env.client.writes[1][2]["expectedCartVersion"] == 5
    assert result["command"]["state"] == "confirmed"


async def test_committed_but_lost_response_recovers_receipt_without_sending_again(environment):
    env = environment
    env.client.failure = CommerceError(503, "COMMERCE_UNAVAILABLE", "Unconfirmed")
    with (
        bound(env, "add_to_cart", {"product_id": "AR-1001", "quantity": 1}),
        pytest.raises(CommerceError),
    ):
        await env.backend.add_to_cart(env.session, "AR-1001", 1)
    command = env.commands.unknown_cart("buyer")[0]
    env.client.receipts[command.key] = CartResult.model_validate(cart_result(command.key))
    with bound(env):
        result = await env.backend.command_envelope(env.session, command.key, retry=True)
    assert result["command"]["state"] == "confirmed" and len(env.client.writes) == 1
    assert not env.commands.unknown_cart("buyer")


@pytest.mark.parametrize(
    "status,category,rejected",
    [
        (409, "VERSION_CONFLICT", True),
        (403, "AUTHORIZATION", True),
        (409, "INCONSISTENT_DURABLE_STATE", False),
        (429, "INDETERMINATE", False),
        (503, "RETRYABLE_CONCURRENCY", False),
    ],
)
async def test_only_definitive_refusal_settles_command(environment, status, category, rejected):
    env = environment
    env.client.failure = CommerceError(status, category, "Test failure")
    with bound(env, "remove_from_cart", {"product_id": "AR-1001"}), pytest.raises(CommerceError):
        await env.backend.remove_from_cart(env.session, "AR-1001")
    command = env.commands.by_call(env.session.session_id, "buyer", "turn-1", "call-1")
    assert (command.rejection is not None) is rejected
    assert command.result is None


async def test_cancelled_tool_leaves_original_unknown_command_for_read_only_recovery(environment):
    env = environment
    env.client.failure = asyncio.CancelledError()
    with (
        bound(env, "add_to_cart", {"product_id": "AR-1001", "quantity": 1}),
        pytest.raises(asyncio.CancelledError),
    ):
        await env.backend.add_to_cart(env.session, "AR-1001", 1)
    command = env.commands.unknown_cart("buyer")[0]
    with bound(env):
        await env.backend.command_envelope(env.session, command.key)
    assert len(env.client.writes) == 1 and command.result is None and command.rejection is None


async def test_other_conversation_can_recover_own_command_without_changing_original_binding(
    environment,
):
    env = environment
    original = env.session
    command = env.commands.register(
        session_id=original.session_id,
        owner="buyer",
        turn_id="t",
        call_id="c",
        kind="cart",
        operation="ADD",
        arguments={"product_id": "AR-1001", "quantity": 1},
        body={"productId": "AR-1001", "quantity": 1},
    )
    env.client.receipts[command.key] = CartResult.model_validate(cart_result(command.key))
    other = env.store.create("buyer", role="buyer")
    env.session = ShoppingSessionContext(session_id=other.session_id, user_id="buyer")
    with bound(env):
        records = await env.backend.recover_cart_commands(env.session)
        replay = await env.backend.command_envelope(env.session, command.key, retry=True)
    assert records[0]["state"] == "confirmed"
    assert ("buyer", original.session_id, "shopping:cart:read") in env.auth.scopes
    assert replay["command"]["session_id"] == original.session_id
    assert not env.client.writes


@pytest.mark.parametrize("role,owner", [("merchant", "buyer"), ("buyer", "other")])
async def test_bound_role_and_owner_cannot_be_replaced_by_tool_session(environment, role, owner):
    env = environment
    with bound(env, role=role, subject=owner), pytest.raises(CommerceError) as error:
        await env.backend.get_product_details(env.session, "AR-1001")
    assert error.value.status_code == 403 and not env.client.reads


async def test_ui_command_does_not_silently_retry_or_reinterpret_old_key(environment):
    env = environment
    body = {"productId": "AR-1001", "quantity": 1}
    with bound(env):
        await env.backend.cart_mutation(env.session, "ADD", body, "ui/?#key")
        again = await env.backend.cart_mutation(env.session, "ADD", body, "ui/?#key")
        with pytest.raises(HTTPException):
            await env.backend.cart_mutation(env.session, "ADD", body | {"quantity": 2}, "ui/?#key")
    assert len(env.client.writes) == 1 and again["command"]["state"] == "confirmed"
    assert again["quote"]["items"][0]["unitPriceMinor"] == 7900


async def test_profile_policy_order_and_delivery_are_actual_reads(environment):
    env = environment
    with bound(env):
        profile = await env.backend.get_preferences(env.session)
        policies = await env.backend.search_policies(env.session, "returns")
        orders = await env.backend.get_orders(env.session)
        assert await env.backend.get_order(env.session, "missing") is None
        options = await env.backend.get_fulfillment_options(env.session, ["AR-1001", "unknown"])
        assert await env.backend.get_fulfillment_options(env.session, ["unknown"]) == []
    assert profile.default_location is None and profile.preferences == {}
    assert policies[0].content == "Published only" and orders[0].status == OrderStatus.PAID
    assert options[0].eta == "2026-09-07T11:00:00+08:00"
    assert options[0].estimate_only and options[0].currency == "CNY"
    assert (
        "delivery",
        [{"productId": "AR-1001", "quantity": 1}],
        "direct-token",
    ) in env.client.reads
    assert {scope[2] for scope in env.auth.scopes} == {
        "shopping:profile:read",
        "shopping:orders:read",
    }
    family = product("family") | {
        "kind": "family",
        "productId": None,
        "publicationVersion": None,
        "options": [{"name": "size", "values": ["M"]}],
    }
    env.client.products_by_id["family"] = RetailProduct.model_validate(family)
    with bound(env), pytest.raises(NotOffered):
        await env.backend.get_fulfillment_options(env.session, ["family"])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1])
def test_invalid_search_amounts_are_not_guessed(value):
    with pytest.raises(CommerceError):
        price_bound(value, minimum=True)


async def test_full_cart_delivery_preserves_quantities_and_rejects_unquotable_cart(environment):
    env = environment
    env.client.quote.items[0].quantity = 3
    with bound(env):
        result = await env.backend.delivery_cart(env.session)
        assert result["estimate"]["itemSubtotalMinor"] == 7900
        assert result["options"][0]["estimate_only"] is True
        assert env.client.reads[-1] == (
            "delivery",
            [{"productId": "AR-1001", "quantity": 3}],
            "direct-token",
        )
        env.client.quote.checkoutReady = False
        with pytest.raises(CommerceError) as error:
            await env.backend.delivery_cart(env.session)
        assert error.value.category == "NOT_ORDERABLE"
