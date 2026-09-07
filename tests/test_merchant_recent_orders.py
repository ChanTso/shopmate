"""The model uses the same live, authorized order feed as the merchant overview."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from commerce_common.skills import SkillRegistry
from merchant_agent import MerchantSessionContext, MerchantSessionState
from merchant_agent.fencing import MERCHANT_FENCE

from shopmate.auth import AuthClient, RequestIdentity, bind_context
from shopmate.backend import CityBuddyMerchantBackend, ShopMateConfig
from shopmate.commerce_client import CommerceClient, CommerceError
from shopmate.merchant_executor import RetailMerchantExecutor
from shopmate.provider import build_agent
from shopmate.settings import Settings
from tests.test_commerce_client import order_response


def session():
    return MerchantSessionContext(
        session_id="session-1", merchant_id="citybuddy", operator="operator-1"
    )


def executor(backend):
    return RetailMerchantExecutor(
        backend=backend,
        config=ShopMateConfig(),
        state=MerchantSessionState(),
        session=session(),
        skills=SkillRegistry([]),
    )


def test_production_factory_registers_recent_order_tool_once_without_actor_arguments():
    backend = CityBuddyMerchantBackend(object(), object(), object(), object())
    agent = build_agent(Settings(), backend, SimpleNamespace(client=object()))
    tools = [tool for tool in agent._tools if tool["name"] == "get_recent_orders"]
    assert len(tools) == 1
    schema = tools[0]["input_schema"]
    assert set(schema["properties"]) == {"limit"}
    limit = schema["properties"]["limit"]
    assert (limit["type"], limit["default"], limit["minimum"], limit["maximum"]) == (
        "integer",
        6,
        1,
        50,
    )
    assert schema["additionalProperties"] is False
    assert "get_recent_orders" not in agent.config.absent_tools()
    assert "web_search" in {tool["name"] for tool in agent._tools}


@pytest.mark.parametrize("arguments,limit", [({}, 6), ({"limit": 50}, 50)])
async def test_model_dispatch_exchanges_bound_obo_and_keeps_orders_newer_than_report_cutoff(
    arguments, limit
):
    recent = order_response()
    recent.update(
        orderId="new-unpaid",
        createdAt="2026-09-08T00:00:00Z",
        status="UNPAID",
        stateVersion=1,
        payment=None,
        fulfillment=None,
        refunds={"reservedAmountMinor": 0, "byState": []},
    )
    seen = []

    def handle(request):
        seen.append(request)
        if request.url.host == "auth.test":
            assert request.method == "POST"
            assert request.url.path == "/auth/token/exchange"
            assert request.headers["X-User-Authorization"] == "Bearer synthetic-direct"
            assert json.loads(request.content) == {
                "sessionId": "session-1",
                "userSubject": "operator-1",
                "scope": "merchant:read",
            }
            return httpx.Response(200, json={"accessToken": "synthetic-merchant-obo"})
        assert request.method == "GET"
        assert request.url.path == "/internal/merchant/orders"
        assert list(request.url.params.multi_items()) == [("limit", str(limit))]
        assert request.headers["Authorization"] == "Bearer synthetic-merchant-obo"
        assert request.headers["X-Merchant-Session-Id"] == "session-1"
        assert request.content == b""
        return httpx.Response(200, json=[recent, order_response()])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        auth = AuthClient(
            Settings(auth_url="http://auth.test", merchant_service_secret="synthetic-service"), http
        )
        backend = CityBuddyMerchantBackend(
            auth,
            object(),
            CommerceClient("http://commerce.test", http),
            object(),
            report_as_of=datetime(2026, 9, 4, 16, tzinfo=UTC),
        )
        with bind_context(RequestIdentity("operator-1", "synthetic-direct"), "session-1"):
            outcome = await executor(backend).execute("get_recent_orders", arguments)
    assert len(seen) == 2
    assert not outcome.is_error
    assert outcome.result_text.startswith(MERCHANT_FENCE.open + "\n")
    assert outcome.result_text.endswith("\n" + MERCHANT_FENCE.close)
    rows = json.loads(outcome.result_text.split("\n", 1)[1].rsplit("\n", 1)[0])
    assert [row["orderId"] for row in rows] == ["new-unpaid", "historical-order"]
    assert rows[0]["createdAt"] == "2026-09-08T00:00:00Z"
    assert rows[0]["payment"] is None and rows[0]["fulfillment"] is None
    assert rows[0]["product"]["totalPriceMinor"] == 2500
    assert rows[1]["refunds"]["byState"][0] == {
        "state": "REQUESTED",
        "count": 1,
        "requestedAmountMinor": 100,
        "refundedAmountMinor": 0,
    }
    assert rows[1]["fulfillment"]["stage"] == "DELIVERED"


@pytest.mark.parametrize(
    "arguments",
    [
        {"limit": True},
        {"limit": False},
        {"limit": 0},
        {"limit": 51},
        {"limit": 6.0},
        {"limit": "6"},
        {"limit": None},
        {"owner": "another-operator"},
        {"userSubject": "another-operator", "limit": 6},
        {"scope": "merchant:change:prepare"},
        {"session_id": "other-session"},
        {"asOf": "2026-09-05T00:00:00Z"},
        {"offset": 50},
    ],
)
async def test_invalid_business_arguments_do_not_call_backend(arguments):
    backend = SimpleNamespace(get_recent_orders=AsyncMock())
    outcome = await executor(backend).execute("get_recent_orders", arguments)
    assert outcome.is_error
    backend.get_recent_orders.assert_not_awaited()


async def test_runtime_progress_metadata_remains_separate_from_business_arguments():
    backend = SimpleNamespace(get_recent_orders=AsyncMock(return_value=[]))
    outcome = await executor(backend).execute(
        "get_recent_orders", {"limit": 6, "status": "Reading recent orders"}
    )
    assert not outcome.is_error
    backend.get_recent_orders.assert_awaited_once_with(session(), limit=6)


async def test_backend_read_error_is_an_error_outcome_not_an_empty_order_feed():
    backend = SimpleNamespace(
        get_recent_orders=AsyncMock(
            side_effect=CommerceError(403, "AUTHORIZATION", "Merchant read denied")
        )
    )
    outcome = await executor(backend).execute("get_recent_orders", {})
    assert outcome.is_error
    assert "unavailable" in outcome.result_text
    assert "merchant_data" not in outcome.result_text


async def test_context_mismatch_cannot_exchange_another_session_or_operator():
    auth = SimpleNamespace(exchange=AsyncMock())
    client = SimpleNamespace(recent_orders=AsyncMock())
    backend = CityBuddyMerchantBackend(auth, object(), client, object())
    with bind_context(RequestIdentity("another-operator", "synthetic-direct"), "session-1"):
        outcome = await executor(backend).execute("get_recent_orders", {})
    assert outcome.is_error
    auth.exchange.assert_not_awaited()
    client.recent_orders.assert_not_awaited()
