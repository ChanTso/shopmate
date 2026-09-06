import json

import httpx
import pytest

from shopmate.commerce_client import CommerceClient, CommerceError


def draft_response(state="PREPARED"):
    return {
        "draftId": "draft-1",
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
    assert request.url.path == "/internal/merchant/price-drafts"
    assert request.headers["Authorization"] == "Bearer obo-token"
    assert request.headers["X-Merchant-Session-Id"] == "session-1"
    assert request.headers["Idempotency-Key"] == "stable-key"
    assert json.loads(request.content) == body
    assert draft.items[0].newPriceMinor == 2520


async def test_apply_keeps_authoritative_business_rejection_and_direct_token():
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(409, json=draft_response("REJECTED"))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        result = await CommerceClient("http://commerce.test", http).apply("draft-1", "direct-token")
    assert result.state == "REJECTED"
    assert result.result["reason"] == "VERSION_CONFLICT"
    assert seen[0].url.path == "/api/merchant/price-drafts/draft-1/apply"
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
