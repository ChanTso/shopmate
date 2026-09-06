import json

import httpx
import pytest

from shopmate.commerce_client import CommerceClient, CommerceError


def draft_response(state="PREPARED"):
    return {
        "changeId": "draft-1",
        "kind": "PRICE_UPDATE",
        "payload": None,
        "currency": "CNY",
        "state": state,
        "items": [
            {
                "productId": "coffee",
                "name": "Coffee",
                "oldPriceMinor": 2400,
                "newPriceMinor": 2520,
                "currency": "CNY",
                "expectedVersion": 3,
            }
        ],
        "result": None if state == "PREPARED" else {"status": state, "reason": "VERSION_CONFLICT"},
        "createdAt": "2026-09-05T00:00:00Z",
        "resolvedAt": None if state == "PREPARED" else "2026-09-05T00:01:00Z",
    }


async def test_prepare_maps_exact_body_and_bound_headers():
    body = {"currency": "CNY", "items": [{"productId": "coffee", "newPriceMinor": 2520}]}
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json=draft_response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = CommerceClient("http://commerce.test", http)
        draft = await client.prepare(body, "stable-key", "obo-token", "session-1")
    request = seen[0]
    assert request.url.path == "/internal/merchant/changes"
    assert request.headers["Authorization"] == "Bearer obo-token"
    assert request.headers["X-Merchant-Session-Id"] == "session-1"
    assert request.headers["Idempotency-Key"] == "stable-key"
    assert json.loads(request.content) == {"kind": "PRICE_UPDATE", "payload": body}
    assert draft.items[0]["newPriceMinor"] == 2520


async def test_apply_keeps_authoritative_business_rejection_and_direct_token():
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(409, json=draft_response("REJECTED"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        result = await CommerceClient("http://commerce.test", http).apply("draft-1", "direct-token")
    assert result.state == "REJECTED"
    assert result.result["reason"] == "VERSION_CONFLICT"
    assert seen[0].url.path == "/api/merchant/changes/draft-1/apply"
    assert seen[0].headers["Authorization"] == "Bearer direct-token"
    assert "X-Merchant-Session-Id" not in seen[0].headers
    assert seen[0].content in (b"", b"null")


@pytest.mark.parametrize("outcome", ["network", "forbidden", "invalid_amount"])
async def test_http_boundary_reports_safe_errors_and_rejects_fractional_minor_units(outcome):
    def handle(request):
        if outcome == "network":
            raise httpx.ConnectError(
                "private token upstream-secret at private-host", request=request
            )
        if outcome == "forbidden":
            return httpx.Response(
                403, json={"message": "upstream-secret", "category": "AUTHORIZATION"}
            )
        value = draft_response()
        value["items"][0]["newPriceMinor"] = 2520.5
        return httpx.Response(200, json=value)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(CommerceError) as failure:
            await CommerceClient("http://commerce.test", http).draft("draft-1", "obo", "s")
    assert (
        failure.value.status_code
        == {"network": 503, "forbidden": 403, "invalid_amount": 502}[outcome]
    )
    assert "upstream-secret" not in str(failure.value)
    assert "private-host" not in str(failure.value)


def order_response():
    return {
        "orderKind": "STANDARD",
        "orderId": "historical-order",
        "status": "PAID",
        "stateVersion": 2,
        "createdAt": "2026-09-01T12:00:00Z",
        "unpaidDeadline": None,
        "product": {
            "productId": "coffee",
            "name": "Historical coffee",
            "unitPriceMinor": 1250,
            "currency": "CNY",
            "quantity": 2,
            "totalPriceMinor": 2500,
            "productVersion": 7,
        },
        "payment": {
            "attemptId": "payment-1",
            "state": "SUCCEEDED",
            "stateVersion": 2,
            "amountMinor": 2500,
            "refundedAmountMinor": 0,
            "currency": "CNY",
            "succeededAt": "2026-09-01T12:01:00Z",
        },
        "refunds": {
            "reservedAmountMinor": 100,
            "byState": [
                {
                    "state": "REQUESTED",
                    "count": 1,
                    "requestedAmountMinor": 100,
                    "refundedAmountMinor": 0,
                }
            ],
        },
        "fulfillment": {
            "method": "STANDARD",
            "stage": "DELIVERED",
            "promisedDeliveryAt": None,
            "estimatedDeliveryAt": "2026-09-05T12:00:00Z",
            "packedAt": None,
            "shippedAt": "2026-09-02T12:00:00Z",
            "deliveredAt": "2026-09-03T12:00:00Z",
            "delayReason": None,
            "sourceKind": "FIXTURE",
            "sourceRef": "synthetic-shipment",
            "observedAt": "2026-09-04T12:00:00Z",
        },
    }


@pytest.mark.parametrize("limit", [None, 50])
async def test_recent_orders_uses_only_limit_and_merchant_binding_with_typed_historical_facts(
    limit,
):
    seen = []
    unpaid = order_response()
    unpaid.update(orderId="newer-order", orderKind="SECKILL", status="UNPAID", stateVersion=1)
    unpaid["product"]["productVersion"] = None
    unpaid["payment"] = None
    unpaid["fulfillment"] = None
    unpaid["refunds"] = {"reservedAmountMinor": 0, "byState": []}

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json=[unpaid, order_response()])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = CommerceClient("http://commerce.test/", http)
        orders = await client.recent_orders(
            "merchant-obo", "merchant-session", **({} if limit is None else {"limit": limit})
        )
    assert len(seen) == 1
    request = seen[0]
    assert request.method == "GET"
    assert request.url.path == "/internal/merchant/orders"
    assert request.url.params.multi_items() == [("limit", str(6 if limit is None else limit))]
    assert request.headers.get_list("Authorization") == ["Bearer merchant-obo"]
    assert request.headers.get_list("X-Merchant-Session-Id") == ["merchant-session"]
    assert "X-Shopping-Session-Id" not in request.headers
    assert "Idempotency-Key" not in request.headers
    assert request.content in (b"", b"null")
    assert [order.orderId for order in orders] == ["newer-order", "historical-order"]
    assert orders[0].payment is None and orders[0].fulfillment is None
    assert orders[0].product.productVersion is None
    paid = orders[1]
    assert paid.product.unitPriceMinor == 1250 and paid.product.productVersion == 7
    assert paid.payment.refundedAmountMinor == 0
    assert paid.refunds.byState[0].requestedAmountMinor == 100
    assert paid.refunds.byState[0].refundedAmountMinor == 0
    assert paid.fulfillment.deliveredAt.isoformat() == "2026-09-03T12:00:00+00:00"
    assert paid.fulfillment.estimatedDeliveryAt.isoformat() == "2026-09-05T12:00:00+00:00"


async def test_recent_orders_accepts_a_real_empty_array():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[]))
    ) as http:
        assert await CommerceClient("http://commerce.test", http).recent_orders("obo", "s") == []


@pytest.mark.parametrize("limit", [0, 51, True, 1.5, "6"])
async def test_recent_orders_rejects_invalid_limit_without_dispatch(limit):
    def handle(request):
        raise AssertionError("Invalid limit must not cross the HTTP boundary")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(CommerceError) as failure:
            await CommerceClient("http://commerce.test", http).recent_orders(
                "obo", "s", limit=limit
            )
    assert failure.value.status_code == 400 and failure.value.category == "VALIDATION"


@pytest.mark.parametrize("outcome", ["network", "forbidden", "server_failure", "invalid_json"])
async def test_recent_orders_preserves_safe_errors_instead_of_reporting_an_empty_store(outcome):
    def handle(request):
        if outcome == "network":
            raise httpx.ReadTimeout("private upstream-secret host", request=request)
        if outcome == "invalid_json":
            return httpx.Response(200, content=b"private upstream-secret is not JSON")
        return httpx.Response(
            403 if outcome == "forbidden" else 500,
            json={"message": "private upstream-secret host", "category": "AUTHORIZATION"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        with pytest.raises(CommerceError) as failure:
            await CommerceClient("http://commerce.test", http).recent_orders("obo", "s")
    assert (
        failure.value.status_code
        == {
            "network": 503,
            "forbidden": 403,
            "server_failure": 503,
            "invalid_json": 502,
        }[outcome]
    )
    assert "upstream-secret" not in str(failure.value)
    assert "private" not in str(failure.value)


@pytest.mark.parametrize(
    "malformed",
    [
        "object",
        "over_limit",
        "row_type",
        "missing_payment",
        "fractional_amount",
        "boolean_quantity",
        "state",
    ],
)
async def test_recent_orders_rejects_an_invalid_page_without_dropping_bad_rows(malformed):
    value = [order_response()]
    if malformed == "object":
        value = {"orders": value}
    elif malformed == "over_limit":
        value *= 7
    elif malformed == "row_type":
        value.append("not an order")
    elif malformed == "missing_payment":
        del value[0]["payment"]
    elif malformed == "fractional_amount":
        value[0]["product"]["unitPriceMinor"] = 12.5
    elif malformed == "boolean_quantity":
        value[0]["product"]["quantity"] = True
    elif malformed == "state":
        value[0]["payment"]["state"] = "DELIVERED"
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=value))
    ) as http:
        with pytest.raises(CommerceError) as failure:
            await CommerceClient("http://commerce.test", http).recent_orders("obo", "s")
    assert failure.value.status_code == 502 and failure.value.category == "INVALID_RESPONSE"
