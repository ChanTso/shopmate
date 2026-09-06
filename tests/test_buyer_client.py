import hashlib
import hmac
import json

import httpx
import pytest

from shopmate.buyer_client import BuyerClient
from shopmate.commerce_client import CommerceError

STAMP = "2026-09-07T01:02:03Z"
TOKEN = "direct-user-token"
OBO = "shopping-obo-token"
SESSION = "shopping-session"


def product(identifier="AR-1001"):
    return {
        "id": identifier,
        "kind": "plain",
        "productId": identifier,
        "variantOf": None,
        "title": "Coffee machine",
        "shortDescription": "Actual catalog text",
        "priceMinor": 7900,
        "currency": "CNY",
        "stockQuantity": 20,
        "available": True,
        "inStock": True,
        "publicationVersion": 3,
        "metadataVersion": 1,
        "familyMetadataVersion": None,
        "content": {"rating": 4.5},
        "options": [],
        "optionValues": {},
    }


def cart():
    return {
        "version": 5,
        "currency": "CNY",
        "subtotalMinor": 7900,
        "checkoutReady": True,
        "items": [
            {
                "productId": "AR-1001",
                "quantity": 1,
                "name": "Coffee machine",
                "unitPriceMinor": 7900,
                "currency": "CNY",
                "productVersion": 3,
                "stockQuantity": 20,
                "available": True,
                "publicationState": "PUBLISHED",
                "lineTotalMinor": 7900,
                "orderable": True,
                "imageUrl": None,
                "optionValues": {},
                "familyId": None,
            }
        ],
    }


def cart_result(key="add-1", operation="ADD"):
    return {
        "receipt": {
            "key": key,
            "operation": operation,
            "productId": "AR-1001",
            "beforeQuantity": 0,
            "afterQuantity": 1,
            "appliedVersion": 5,
        },
        "cart": cart(),
        "replayed": False,
    }


def order():
    return {
        "orderKind": "STANDARD",
        "orderId": "order-1",
        "status": "PAID",
        "stateVersion": 2,
        "createdAt": STAMP,
        "unpaidDeadline": None,
        "product": {
            "productId": "AR-1001",
            "name": "Historical name",
            "unitPriceMinor": 7500,
            "currency": "CNY",
            "quantity": 1,
            "totalPriceMinor": 7500,
            "productVersion": 2,
        },
        "payment": {
            "attemptId": "attempt-1",
            "state": "SUCCEEDED",
            "stateVersion": 2,
            "amountMinor": 7500,
            "refundedAmountMinor": 0,
            "currency": "CNY",
            "succeededAt": STAMP,
        },
        "refunds": {
            "reservedAmountMinor": 1000,
            "byState": [
                {
                    "state": "REQUESTED",
                    "count": 1,
                    "requestedAmountMinor": 1000,
                    "refundedAmountMinor": 0,
                }
            ],
        },
        "fulfillment": None,
    }


def checkout():
    return {
        "checkoutId": "checkout-1",
        "sourceCartVersion": 5,
        "currency": "CNY",
        "totalMinor": 7500,
        "createdAt": STAMP,
        "paymentStatus": "PAID",
        "orders": [order()],
        "replayed": False,
    }


def pending():
    return {
        "pendingActionId": "action-1",
        "actionType": "REFUND_REQUEST",
        "userSubject": "buyer-1",
        "supportSessionId": SESSION,
        "traceId": "trace-1",
        "turnId": "turn-1",
        "requiredScope": "refund:create",
        "sandboxId": None,
        "orderId": "order-1",
        "targetVersion": 2,
        "amountMinor": 1000,
        "currency": "CNY",
        "state": "PREPARED",
        "expiresAt": STAMP,
        "replayed": False,
    }


def action_receipt():
    return {
        "receiptId": "receipt-1",
        "pendingActionId": "action-1",
        "actionType": "REFUND_REQUEST",
        "status": "REQUESTED",
        "orderId": "order-1",
        "refundId": "refund-1",
        "resourceVersion": 1,
        "amountMinor": 1000,
        "currency": "CNY",
        "committedAt": STAMP,
        "replayed": True,
    }


async def test_catalog_pages_search_and_family_variants_use_direct_identity_and_integer_filters():
    seen = []
    family = product("family-1") | {
        "kind": "family",
        "productId": None,
        "publicationVersion": None,
        "options": [{"name": "size", "values": ["M"]}],
        "variants": [
            product("sku-1")
            | {"kind": "variant", "variantOf": "family-1", "optionValues": {"size": "M"}}
        ],
    }

    def handle(request):
        seen.append(request)
        return httpx.Response(
            200, json=family if request.url.path.endswith("family-1") else [family]
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle),
        headers={"X-Shopping-Session-Id": "stale", "X-Eval-Sandbox-Id": "other"},
    ) as http:
        client = BuyerClient("http://commerce.test", http)
        values = await client.products(TOKEN, limit=50, offset=50)
        await client.search_products(
            TOKEN,
            {"query": "cup", "currency": "CNY", "minPriceMinor": 100, "limit": 8, "offset": 8},
        )
        detail = await client.product("family-1", TOKEN)
    assert seen[0].url.params == httpx.QueryParams({"limit": "50", "offset": "50"})
    assert json.loads(seen[1].content)["minPriceMinor"] == 100
    assert json.loads(seen[1].content)["offset"] == 8
    assert values[0].productId is None
    assert detail.variants[0].optionValues == {"size": "M"}
    assert detail.variants[0].priceMinor == 7900
    for request in seen:
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert "X-Shopping-Session-Id" not in request.headers
        assert "X-Eval-Sandbox-Id" not in request.headers


async def test_cart_commands_encode_query_key_and_preserve_receipt_plus_current_cart():
    seen = []
    key = "already/added?why#yes"

    def handle(request):
        seen.append(request)
        result = cart_result(key)
        if request.url.path.endswith("commands"):
            result["replayed"] = True
            result["cart"]["version"] = 9
            result["cart"]["items"] = []
            result["cart"].update(currency=None, subtotalMinor=0, checkoutReady=False)
        return httpx.Response(
            200, json=result if request.url.path != "/internal/shopping/cart" else cart()
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = BuyerClient("http://commerce.test", http)
        await client.cart(OBO, SESSION)
        await client.cart_add(OBO, SESSION, key, "AR-1001", 1)
        await client.cart_set(OBO, SESSION, "set-key", "AR-1001", 2, 5)
        await client.cart_remove(OBO, SESSION, "remove-key", "AR-1001", 6)
        result = await client.cart_command(key, OBO, SESSION)
    assert [r.method for r in seen] == ["GET", "POST", "PUT", "DELETE", "GET"]
    assert json.loads(seen[1].content) == {"productId": "AR-1001", "quantity": 1}
    assert seen[1].headers["Idempotency-Key"] == key
    assert json.loads(seen[2].content) == {"quantity": 2, "expectedCartVersion": 5}
    assert seen[3].url.params == httpx.QueryParams({"expectedCartVersion": "6"})
    assert "If-Match" not in seen[3].headers
    assert seen[4].url.params["key"] == key and not seen[4].url.fragment
    assert result.receipt.appliedVersion == 5 and result.cart.version == 9
    assert result.replayed and not result.cart.items
    assert all(r.headers["X-Shopping-Session-Id"] == SESSION for r in seen)
    assert all(r.headers["Authorization"] == "Bearer " + OBO for r in seen)


async def test_facts_preserve_actual_nulls_and_shanghai_delivery_dates():
    seen = []

    def handle(request):
        seen.append(request)
        if request.url.path.endswith("preferences"):
            value = {
                "userId": "buyer-1",
                "displayName": None,
                "loyaltyTier": "NONE",
                "defaultLocation": None,
                "preferences": {},
            }
        elif request.url.path.endswith("policies"):
            value = [
                {
                    "policyId": "policy-1",
                    "title": "Returns",
                    "category": "policy",
                    "content": "Published text",
                    "publicationVersion": 7,
                    "publishedAt": STAMP,
                },
                {
                    "policyId": "policy-uncategorized",
                    "title": "Published returns policy",
                    "category": None,
                    "content": "Published text without classification",
                    "publicationVersion": 2,
                    "publishedAt": STAMP,
                },
            ]
        else:
            value = {
                "quotedAt": STAMP,
                "configVersion": 2,
                "currency": "CNY",
                "timeZone": "Asia/Shanghai",
                "itemSubtotalMinor": 7900,
                "items": [
                    {
                        "productId": "AR-1001",
                        "quantity": 1,
                        "unitPriceMinor": 7900,
                        "productVersion": 3,
                    }
                ],
                "estimateOnly": True,
                "options": [
                    {
                        "code": "pickup",
                        "method": "pickup",
                        "feeMinor": 0,
                        "earliestDate": None,
                        "latestDate": None,
                        "readyAt": "2026-09-07T03:00:00Z",
                        "location": "Shanghai demo store",
                    }
                ],
            }
        return httpx.Response(200, json=value)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = BuyerClient("http://commerce.test", http)
        profile = await client.preferences(OBO, SESSION)
        policies = await client.policies("退货/换货?", TOKEN)
        estimate = await client.delivery([{"productId": "AR-1001", "quantity": 1}], TOKEN)
    assert profile.defaultLocation is None and profile.preferences == {}
    assert policies[0].publicationVersion == 7 and policies[0].category == "policy"
    assert policies[1].category is None and policies[1].publicationVersion == 2
    assert estimate.estimateOnly and estimate.options[0].feeMinor == 0
    assert estimate.options[0].earliestDate is None
    assert seen[0].headers["X-Shopping-Session-Id"] == SESSION
    assert seen[1].url.params["query"] == "退货/换货?"
    assert "X-Shopping-Session-Id" not in seen[2].headers
    assert json.loads(seen[2].content) == {"items": [{"productId": "AR-1001", "quantity": 1}]}


async def test_owned_order_and_checkout_reads_keep_payment_and_fulfillment_separate():
    seen = []

    def handle(request):
        seen.append(request)
        value = (
            checkout()
            if "checkouts" in request.url.path
            else [order()]
            if request.url.path.endswith("orders")
            else order()
        )
        return httpx.Response(200, json=value)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = BuyerClient("http://commerce.test", http)
        orders = await client.orders(OBO, SESSION, limit=50)
        item = await client.order("order-1", OBO, SESSION)
        group = await client.checkout("checkout-1", OBO, SESSION)
    assert orders[0].product.unitPriceMinor == 7500
    assert item.payment.state == "SUCCEEDED" and item.fulfillment is None
    assert item.refunds.reservedAmountMinor == 1000
    assert group.paymentStatus == "PAID" and group.orders[0].fulfillment is None
    assert seen[0].url.params == httpx.QueryParams({"limit": "50"})
    assert all(r.headers["X-Shopping-Session-Id"] == SESSION for r in seen)


async def test_direct_checkout_and_payment_accept_created_status_without_obo_or_owner_in_body():
    seen = []
    command = {
        "expectedCartVersion": 5,
        "currency": "CNY",
        "items": [
            {
                "productId": "AR-1001",
                "quantity": 1,
                "expectedProductVersion": 2,
                "expectedUnitPriceMinor": 7500,
            }
        ],
    }

    def handle(request):
        seen.append(request)
        value = (
            checkout()
            if request.url.path.endswith("checkouts")
            else {
                "attemptId": "attempt-1",
                "callbackCorrelationId": "correlation-1",
                "orderId": "order-1",
                "orderKind": "STANDARD",
                "amountMinor": 7500,
                "currency": "CNY",
                "state": "PENDING",
                "replayed": False,
            }
        )
        return httpx.Response(201, json=value)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), headers={"X-Shopping-Session-Id": "other"}
    ) as http:
        client = BuyerClient("http://commerce.test", http)
        receipt = await client.create_checkout(
            TOKEN, "checkout-key", command, correlation_id="correlation-1"
        )
        attempt = await client.start_payment("order-1", TOKEN, "pay-key", 7500, "CNY")
    assert receipt.checkoutId == "checkout-1" and attempt.state == "PENDING"
    assert json.loads(seen[0].content) == command
    assert json.loads(seen[1].content) == {"amountMinor": 7500, "currency": "CNY"}
    assert seen[0].headers["X-Correlation-Id"] == "correlation-1"
    assert [r.headers["Idempotency-Key"] for r in seen] == ["checkout-key", "pay-key"]
    assert all("X-Shopping-Session-Id" not in r.headers for r in seen)
    assert all(r.headers["Authorization"] == "Bearer " + TOKEN for r in seen)


async def test_payment_callback_signs_exact_java_non_evaluation_canonical_without_bearer():
    body = {
        "callbackEventId": "event-1",
        "callbackCorrelationId": "correlation-1",
        "orderId": "order-1",
        "amountMinor": 7500,
        "currency": "CNY",
        "outcome": "SUCCEEDED",
    }
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "attemptId": "attempt-1",
                "callbackCorrelationId": "correlation-1",
                "orderId": "order-1",
                "state": "SUCCEEDED",
                "replayed": True,
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle),
        headers={"Authorization": "Bearer stale", "X-Shopping-Session-Id": "stale"},
    ) as http:
        value = await BuyerClient("http://commerce.test", http).payment_callback(
            body, "callback-key", key_id="test-key", secret="test-secret", timestamp=1799999999
        )
    request = seen[0]
    canonical = "test-key\n1799999999\ncallback-key\nevent-1\ncorrelation-1\norder-1\n7500\nCNY\nSUCCEEDED\n\n\n\n"
    expected = hmac.new(b"test-secret", canonical.encode(), hashlib.sha256).hexdigest()
    assert request.headers["X-Mock-Payment-Signature"] == expected
    assert request.headers["X-Mock-Payment-Key-Id"] == "test-key"
    assert request.headers["X-Mock-Payment-Timestamp"] == "1799999999"
    assert request.headers["Idempotency-Key"] == "callback-key"
    assert "Authorization" not in request.headers and "X-Shopping-Session-Id" not in request.headers
    assert "test-secret" not in request.content.decode()
    assert json.loads(request.content) == body
    assert value.state == "SUCCEEDED" and value.replayed


async def test_refund_uses_existing_action_dto_and_stable_trace_turn_not_merchant_draft():
    seen = []
    body = {
        "actionType": "REFUND_REQUEST",
        "arguments": {"orderId": "order-1", "amountMinor": 1000, "currency": "CNY"},
    }

    def handle(request):
        seen.append(request)
        return httpx.Response(
            201 if request.url.path.endswith("prepare") else 200,
            json=pending() if request.url.path.endswith("prepare") else action_receipt(),
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = BuyerClient("http://commerce.test", http)
        prepared = await client.prepare_refund(OBO, SESSION, "trace-1", "turn-1", body)
        receipt = await client.confirm_refund(
            prepared.pendingActionId, OBO, SESSION, "trace-1", "turn-1"
        )
    assert prepared.requiredScope == "refund:create" and prepared.supportSessionId == SESSION
    assert receipt.status == "REQUESTED" and receipt.refundId == "refund-1"
    assert json.loads(seen[0].content) == body and json.loads(seen[1].content) == {}
    for request in seen:
        assert request.url.path.startswith("/internal/shopping/actions/")
        assert request.headers["X-Shopping-Session-Id"] == SESSION
        assert request.headers["X-Agent-Trace-Id"] == "trace-1"
        assert request.headers["X-Agent-Turn-Id"] == "turn-1"
        assert "Idempotency-Key" not in request.headers
        assert "X-Merchant-Session-Id" not in request.headers


@pytest.mark.parametrize("bad", [True, 7900.0, "7900", -1, 9223372036854775808])
async def test_money_response_rejects_coercions_and_out_of_range_values(bad):
    value = product() | {"priceMinor": bad}
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=value))
    ) as http:
        with pytest.raises(CommerceError) as error:
            await BuyerClient("http://commerce.test", http).product("AR-1001", TOKEN)
    assert error.value.status_code == 502 and error.value.category == "INVALID_RESPONSE"


@pytest.mark.parametrize("bad", [True, 7500.5, "7500", 0])
async def test_money_request_rejected_before_network_and_never_rounded(bad):
    def unexpected(_request):
        raise AssertionError("Invalid integer money must not be sent")

    async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as http:
        client = BuyerClient("http://commerce.test", http)
        with pytest.raises(CommerceError) as error:
            await client.start_payment("order-1", TOKEN, "pay-key", bad, "CNY")
    assert error.value.status_code == 400


@pytest.mark.parametrize(
    "status,category",
    [
        (404, "NOT_FOUND"),
        (403, "AUTHORIZATION"),
        (409, "stale_quote"),
        (422, "unsupported_currency"),
        (503, "UNAVAILABLE"),
    ],
)
async def test_only_get_404_is_optional_and_other_business_errors_remain_safe(status, category):
    seen = []

    def handle(request):
        seen.append(request)
        return httpx.Response(
            status, json={"category": category, "message": "upstream-secret private details"}
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        client = BuyerClient("http://commerce.test", http)
        if status == 404:
            assert await client.order("order-1", OBO, SESSION) is None
        else:
            with pytest.raises(CommerceError) as error:
                await client.order("order-1", OBO, SESSION)
            assert error.value.status_code == status and error.value.category == category
            assert "upstream-secret" not in str(error.value)
        with pytest.raises(CommerceError) as error:
            await client.cart_add(OBO, SESSION, "key", "AR-1001", 1)
        assert error.value.status_code == status
    assert len(seen) == 2


@pytest.mark.parametrize("failure", ["transport", "redirect", "bad_json", "bad_category"])
async def test_unknown_write_result_is_not_retried_and_errors_do_not_echo_upstream(failure):
    seen = []

    def handle(request):
        seen.append(request)
        if failure == "transport":
            raise httpx.ReadError("token-secret private-host", request=request)
        if failure == "redirect":
            return httpx.Response(307, headers={"Location": "https://other.test/leak"})
        if failure == "bad_json":
            return httpx.Response(201, content=b"private upstream secret")
        return httpx.Response(
            500, json={"category": "secret-untrusted-category", "message": "token-secret"}
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), follow_redirects=True
    ) as http:
        with pytest.raises(CommerceError) as error:
            await BuyerClient("http://commerce.test", http).cart_add(
                OBO, SESSION, "same-key", "AR-1001", 1
            )
    assert len(seen) == 1
    assert error.value.status_code in (502, 503)
    assert "secret" not in str(error.value) and "secret" not in error.value.category


async def test_shared_http_client_is_not_closed_by_buyer_client():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[]))
    ) as http:
        client = BuyerClient("http://commerce.test", http)
        await client.close()
        assert not http.is_closed
