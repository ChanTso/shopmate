"""Real buyer routes, Java transactions and readonly SQL; no model or pressure workload.

Run after the isolated retail fixture reset. These tests retain their paid orders/refunds;
the environment owner resets the controlled fixture after reviewing the run.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import httpx
import test_business_boundaries as business

from shopmate.app import create_app
from shopmate.auth import AuthClient
from shopmate.buyer_client import BuyerClient
from shopmate.sessions import SessionStore
from shopmate.settings import ROOT

# Reuse the existing real-service fixtures without loading credentials at collection time.
settings = business.settings
truth = business.truth
_rows = business._rows

BUYERS = ("shopmate-retail-buyer", "shopmate-retail-buyer-2")
PRODUCTS = ("AR-1001", "AR-1004")


def key(prefix):
    return f"buyer-it-{prefix}-{uuid4()}"


@asynccontextmanager
async def portal(settings, tmp_path, *, hooks=None):
    auth = AuthClient(settings)
    store = SessionStore(tmp_path / "buyer-business.sqlite3")
    java_http = httpx.AsyncClient(
        timeout=20, trust_env=False, follow_redirects=False, event_hooks=hooks or {}
    )
    client = BuyerClient(settings.commerce_url, java_http)
    app = create_app(
        settings,
        auth=auth,
        store=store,
        backend=object(),
        agent=object(),
        provider=object(),
        buyer_agent=object(),
        buyer_client=client,
    )
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://shopmate.integration",
                timeout=30,
            ) as http,
        ):
            yield SimpleNamespace(http=http, app=app, store=store, client=client, auth=auth)
    finally:
        store.close()
        await auth.close()
        await java_http.aclose()


async def login(http, index=1):
    password = (ROOT / f".run/buyer_{index}_password").read_text().strip()
    response = await http.post(
        "/api/buyer/login", json={"loginIdentifier": BUYERS[index - 1], "password": password}
    )
    assert response.status_code == 200
    headers = {"Authorization": "Bearer " + response.json()["accessToken"]}
    response = await http.post("/api/buyer/session", headers=headers)
    assert response.status_code == 200
    headers["X-Session-Id"] = response.json()["session_id"]
    return headers


async def get(http, path, headers):
    response = await http.get(path, headers=headers)
    assert response.status_code == 200
    return response.json()


async def post(http, path, headers, body):
    response = await http.post(path, headers=headers, json=body)
    assert response.status_code == 200
    return response.json()


async def clear_cart(http, headers):
    quote = (await get(http, "/api/buyer/cart", headers))["quote"]
    for item in list(quote["items"]):
        value = await post(
            http,
            "/api/buyer/cart/remove",
            headers,
            {
                "request_key": key("clear"),
                "productId": item["productId"],
                "expectedCartVersion": quote["version"],
            },
        )
        quote = value["quote"]
    assert not quote["items"]


async def fill_cart(http, headers, products=PRODUCTS):
    await clear_cart(http, headers)
    value = None
    for identifier in products:
        value = await post(
            http,
            "/api/buyer/cart/add",
            headers,
            {
                "request_key": key("add"),
                "productId": identifier,
                "quantity": 1,
            },
        )
    assert value is not None and value["quote"]["checkoutReady"]
    return value["quote"]


def checkout_body(quote, request_key=None):
    return {
        "request_key": request_key or key("checkout"),
        "expectedCartVersion": quote["version"],
        "currency": quote["currency"],
        "items": [
            {
                "productId": item["productId"],
                "quantity": item["quantity"],
                "expectedProductVersion": item["productVersion"],
                "expectedUnitPriceMinor": item["unitPriceMinor"],
            }
            for item in quote["items"]
        ],
    }


async def test_two_buyers_full_catalog_and_published_facts_use_real_identity(
    settings, tmp_path, truth
):
    async with portal(settings, tmp_path) as p:
        first, second = await login(p.http), await login(p.http, 2)
        roots, offset = [], 0
        while offset is not None:
            page = await get(p.http, f"/api/buyer/products?limit=50&offset={offset}", first)
            roots.extend(page["products"])
            offset = page["next_offset"]
        assert len(roots) == len({value["product_id"] for value in roots}) == 88
        assert any(value["product_id"] == "SM-LIMITED-CUP" for value in roots)
        families = [value for value in roots if value["options"]]
        assert len(families) == 4
        variants = []
        for family in families:
            detail = (await get(p.http, "/api/buyer/products/" + family["product_id"], first))[
                "product"
            ]
            assert detail["product_id"] == family["product_id"]
            assert detail["variants"] and all(
                value["variant_of"] == detail["product_id"] for value in detail["variants"]
            )
            variants.extend(detail["variants"])
        assert len(variants) == len({value["product_id"] for value in variants}) == 21
        plain_ids = {value["product_id"] for value in roots if not value["options"]}
        variant_ids = {value["product_id"] for value in variants}
        assert not plain_ids & variant_ids
        assert len(plain_ids | variant_ids) == 104
        profile = (await get(p.http, "/api/buyer/profile", first))["profile"]
        assert profile["user_id"] == BUYERS[0]
        policies = await get(p.http, "/api/buyer/policies?query=returns", first)
        assert policies["policies"]
        for policy in policies["policies"]:
            published = (
                await _rows(
                    truth,
                    "SELECT published_question,published_answer FROM faq_source "
                    "WHERE faq_id=%s AND published_version>0",
                    (policy["policy_id"],),
                )
            )[0]
            assert policy["title"] == published["published_question"]
            assert policy["content"] == published["published_answer"]
        for query in (None, "", "x" * 201):
            params = {} if query is None else {"query": query}
            assert (
                await p.http.get("/api/buyer/policies", headers=first, params=params)
            ).status_code == 422
        delivery = await post(p.http, "/api/buyer/delivery", first, {"product_ids": [PRODUCTS[0]]})
        assert delivery["options"] and all(
            option["estimate_only"] and option["currency"] == "CNY"
            for option in delivery["options"]
        )
        borrowed = second | {"X-Session-Id": first["X-Session-Id"]}
        borrowed_cart = await get(p.http, "/api/buyer/cart", borrowed)
        assert borrowed_cart == await get(p.http, "/api/buyer/cart", second)
        assert (await p.http.get("/api/buyer/session", headers=borrowed)).status_code == 404
        assert (await p.http.post("/api/merchant/session", headers=first)).status_code == 403
        assert (
            await p.http.post(
                "/api/buyer/cart/add",
                headers=first,
                json={
                    "request_key": key("forged"),
                    "productId": PRODUCTS[0],
                    "quantity": 1,
                    "userSubject": BUYERS[1],
                },
            )
        ).status_code == 422


async def test_two_line_checkout_payment_and_refund_replay_have_authoritative_sql(
    settings, truth, tmp_path
):
    async with portal(settings, tmp_path) as p:
        first, second = await login(p.http), await login(p.http, 2)
        quote = await fill_cart(p.http, first)
        delivery = await post(p.http, "/api/buyer/delivery/cart", first, {})
        assert delivery["estimate"]["itemSubtotalMinor"] == quote["subtotalMinor"]
        command = checkout_body(quote)
        created = await post(p.http, "/api/buyer/checkouts", first, command)
        checkout = created["checkout"]
        assert (
            checkout["totalMinor"] == quote["subtotalMinor"] and type(checkout["totalMinor"]) is int
        )
        assert len(checkout["orders"]) == 2 and checkout["paymentStatus"] == "UNPAID"
        repeated = await post(p.http, "/api/buyer/checkouts", first, command)
        assert repeated["checkout"]["checkoutId"] == checkout["checkoutId"]
        assert not (await get(p.http, "/api/buyer/cart", first))["quote"]["items"]
        paid = await post(p.http, f"/api/buyer/checkouts/{checkout['checkoutId']}/pay", first, {})
        assert paid["checkout"]["paymentStatus"] == "PAID"
        sql = await _rows(
            truth,
            """
            SELECT o.order_id,o.user_subject,o.product_id,o.quantity,o.total_price_minor,o.status,
                   a.state AS payment_state,a.amount_minor,a.succeeded_at,c.result_state AS callback_state
            FROM shopping_checkout_order x JOIN standard_order o ON o.order_id=x.order_id
            JOIN mock_payment_attempt a ON a.order_kind='STANDARD' AND a.order_id=o.order_id
            JOIN mock_payment_callback c ON c.attempt_id=a.attempt_id
            WHERE x.checkout_id=%s ORDER BY x.line_no
        """,
            (checkout["checkoutId"],),
        )
        assert len(sql) == 2
        assert all(
            row["user_subject"] == BUYERS[0]
            and row["status"] == "PAID"
            and row["payment_state"] == "SUCCEEDED"
            and row["callback_state"] == "APPLIED"
            and row["amount_minor"] == row["total_price_minor"]
            and row["succeeded_at"] is not None
            for row in sql
        )
        assert sum(row["total_price_minor"] for row in sql) == checkout["totalMinor"]
        ledger = await _rows(
            truth,
            """
            SELECT COUNT(*) AS n,SUM(l.payment_amount_minor) AS amount_minor
            FROM inventory_ledger l JOIN shopping_checkout_order x ON x.order_id=l.order_id
            WHERE x.checkout_id=%s AND l.movement_type='STANDARD_PAYMENT'
        """,
            (checkout["checkoutId"],),
        )
        assert ledger[0]["n"] == 2 and ledger[0]["amount_minor"] == checkout["totalMinor"]
        order_id = sql[0]["order_id"]
        owned = (await get(p.http, "/api/buyer/orders/" + order_id, first))["order"]
        assert owned["payment"]["state"] == "SUCCEEDED" and owned["fulfillment"] is None
        assert (
            await p.http.get("/api/buyer/orders/" + order_id, headers=second)
        ).status_code == 404
        action = (
            await post(
                p.http,
                "/api/buyer/actions/prepare",
                first,
                {
                    "request_key": key("refund"),
                    "orderId": order_id,
                    "amountMinor": 1000,
                    "currency": "CNY",
                },
            )
        )["action"]
        assert action["state"] == "PREPARED" and action["amountMinor"] == 1000
        same_owner_other_session = await login(p.http)
        path = "/api/buyer/actions/" + action["pendingActionId"] + "/confirm"
        assert (await p.http.post(path, headers=second, json={})).status_code == 404
        receipt = (await post(p.http, path, same_owner_other_session, {}))["receipt"]
        replay = (await post(p.http, path, first, {}))["receipt"]
        assert (
            replay["receiptId"] == receipt["receiptId"]
            and replay["refundId"] == receipt["refundId"]
            and replay["replayed"]
        )
        refunds = await _rows(
            truth,
            """
            SELECT p.state AS pending_state,r.refund_id,r.requested_amount_minor,r.refunded_amount_minor,r.state,
                   a.receipt_id,a.amount_minor,a.result_state,e.event_type
            FROM pending_action p JOIN action_receipt a ON a.pending_action_id=p.pending_action_id
            JOIN mock_refund r ON r.refund_id=a.refund_id
            JOIN commerce_outbox e ON e.event_id=a.outbox_event_id
            WHERE p.pending_action_id=%s
        """,
            (action["pendingActionId"],),
        )
        assert len(refunds) == 1
        assert (
            refunds[0]["pending_state"] == "CONSUMED"
            and refunds[0]["requested_amount_minor"] == 1000
        )
        assert refunds[0]["refunded_amount_minor"] == 0 and refunds[0]["state"] == "REQUESTED"
        assert (
            refunds[0]["result_state"] == "REQUESTED"
            and refunds[0]["event_type"] == "REFUND_REQUESTED"
        )


async def test_quote_and_cart_conflicts_do_not_create_orders(settings, truth, tmp_path):
    async with portal(settings, tmp_path) as p:
        headers = await login(p.http)
        quote = await fill_cart(p.http, headers, PRODUCTS[:1])
        before = await _rows(
            truth,
            "SELECT COUNT(*) AS n FROM standard_order WHERE CAST(user_subject AS BINARY)=CAST(%s AS BINARY)",
            (BUYERS[0],),
        )
        stale_price = checkout_body(quote)
        stale_price["items"][0]["expectedUnitPriceMinor"] += 1
        response = await p.http.post("/api/buyer/checkouts", headers=headers, json=stale_price)
        assert response.status_code == 409 and response.json()["category"] == "stale_quote"
        stale_cart = checkout_body(quote)
        await post(
            p.http,
            "/api/buyer/cart/add",
            headers,
            {"request_key": key("advance-cart"), "productId": PRODUCTS[1], "quantity": 1},
        )
        response = await p.http.post("/api/buyer/checkouts", headers=headers, json=stale_cart)
        assert response.status_code == 409 and response.json()["category"] == "stale_cart"
        after = await _rows(
            truth,
            "SELECT COUNT(*) AS n FROM standard_order WHERE CAST(user_subject AS BINARY)=CAST(%s AS BINARY)",
            (BUYERS[0],),
        )
        assert after == before
        no_checkout = await _rows(
            truth,
            "SELECT COUNT(*) AS n FROM shopping_checkout WHERE CAST(user_subject AS BINARY)=CAST(%s AS BINARY) AND request_key IN (%s,%s)",
            (BUYERS[0], stale_price["request_key"], stale_cart["request_key"]),
        )
        assert no_checkout[0]["n"] == 0
        await clear_cart(p.http, headers)


async def test_cart_post_commit_response_loss_restores_original_receipt_without_duplicate_add(
    settings, truth, tmp_path
):
    lost = False
    submitted = 0

    async def lose(response):
        nonlocal lost, submitted
        if (
            response.request.method == "POST"
            and response.request.url.path == "/internal/shopping/cart/items"
        ):
            submitted += 1
            if not lost and response.status_code == 200:
                lost = True
                await response.aclose()
                raise httpx.ReadError(
                    "Injected cart response loss after Java commit", request=response.request
                )

    async with portal(settings, tmp_path, hooks={"response": [lose]}) as p:
        headers = await login(p.http)
        await clear_cart(p.http, headers)
        request_key = key("lost") + "/?#"
        response = await p.http.post(
            "/api/buyer/cart/add",
            headers=headers,
            json={"request_key": request_key, "productId": PRODUCTS[0], "quantity": 1},
        )
        assert response.status_code == 503 and lost
        commands = p.app.state.resources["commands"]
        assert commands.get(request_key, headers["X-Session-Id"], BUYERS[0]).result is None
        restored = await get(p.http, "/api/buyer/session", headers)
        stored = next(item for item in restored["commands"] if item["request_key"] == request_key)
        assert stored["state"] == "confirmed"
        retried = await post(
            p.http, "/api/buyer/commands/retry", headers, {"request_key": request_key}
        )
        assert submitted == 1 and retried["quote"]["items"][0]["quantity"] == 1
        sql = await _rows(
            truth,
            "SELECT before_quantity,after_quantity,applied_cart_version FROM shopping_cart_command WHERE CAST(user_subject AS BINARY)=CAST(%s AS BINARY) AND command_key=%s",
            (BUYERS[0], request_key),
        )
        assert len(sql) == 1 and sql[0]["before_quantity"] == 0 and sql[0]["after_quantity"] == 1
        await clear_cart(p.http, headers)


async def test_local_registration_without_dispatch_cannot_first_write_on_restore(
    settings, truth, tmp_path
):
    submitted = 0

    async def observe(request):
        nonlocal submitted
        if request.method == "POST" and request.url.path == "/internal/shopping/cart/items":
            submitted += 1

    async with portal(settings, tmp_path, hooks={"request": [observe]}) as p:
        headers = await login(p.http)
        await clear_cart(p.http, headers)
        commands = p.app.state.resources["commands"]
        command = commands.register(
            session_id=headers["X-Session-Id"],
            owner=BUYERS[0],
            turn_id="interrupted-before-java",
            call_id="tool-call",
            kind="cart",
            operation="ADD",
            arguments={"product_id": PRODUCTS[0], "quantity": 1},
            body={"productId": PRODUCTS[0], "quantity": 1},
        )
        restored = await get(p.http, "/api/buyer/session", headers)
        assert (
            next(value for value in restored["commands"] if value["request_key"] == command.key)[
                "state"
            ]
            == "unknown"
        )
        assert (
            submitted == 0 and not (await get(p.http, "/api/buyer/cart", headers))["quote"]["items"]
        )
        sql = await _rows(
            truth,
            "SELECT COUNT(*) AS n FROM shopping_cart_command WHERE CAST(user_subject AS BINARY)=CAST(%s AS BINARY) AND command_key=%s",
            (BUYERS[0], command.key),
        )
        assert sql[0]["n"] == 0
        value = await post(
            p.http, "/api/buyer/commands/retry", headers, {"request_key": command.key}
        )
        assert value["command"]["state"] == "confirmed" and submitted == 1
        sql = await _rows(
            truth,
            "SELECT after_quantity FROM shopping_cart_command WHERE CAST(user_subject AS BINARY)=CAST(%s AS BINARY) AND command_key=%s",
            (BUYERS[0], command.key),
        )
        assert sql == [{"after_quantity": 1}]
        await clear_cart(p.http, headers)


async def test_second_child_payment_failure_exposes_partial_then_continues_original_orders(
    settings, truth, tmp_path
):
    callbacks = 0
    interrupted = False

    async def fail_second(request):
        nonlocal callbacks, interrupted
        if request.url.path == "/internal/mock-payments/callback":
            callbacks += 1
            if callbacks == 2:
                interrupted = True
                raise httpx.ConnectError(
                    "Injected second-child callback failure before dispatch", request=request
                )

    async with portal(settings, tmp_path, hooks={"request": [fail_second]}) as p:
        headers = await login(p.http, 2)
        quote = await fill_cart(p.http, headers)
        created = (await post(p.http, "/api/buyer/checkouts", headers, checkout_body(quote)))[
            "checkout"
        ]
        checkout_id = created["checkoutId"]
        response = await p.http.post(
            f"/api/buyer/checkouts/{checkout_id}/pay", headers=headers, json={}
        )
        assert response.status_code == 503 and interrupted
        partial = (await get(p.http, f"/api/buyer/checkouts/{checkout_id}", headers))["checkout"]
        assert partial["paymentStatus"] == "PARTIALLY_PAID"
        rows = await _rows(
            truth,
            """
            SELECT o.order_id,o.status,a.state AS payment_state FROM shopping_checkout_order x
            JOIN standard_order o ON o.order_id=x.order_id
            JOIN mock_payment_attempt a ON a.order_kind='STANDARD' AND a.order_id=o.order_id
            WHERE x.checkout_id=%s ORDER BY x.line_no
        """,
            (checkout_id,),
        )
        assert sorted(row["status"] for row in rows) == ["PAID", "UNPAID"]
        assert sorted(row["payment_state"] for row in rows) == ["PENDING", "SUCCEEDED"]
        done = (await post(p.http, f"/api/buyer/checkouts/{checkout_id}/pay", headers, {}))[
            "checkout"
        ]
        assert done["paymentStatus"] == "PAID" and callbacks == 3
        assert {value["orderId"] for value in done["orders"]} == {
            value["orderId"] for value in created["orders"]
        }
        final = await _rows(
            truth,
            """
            SELECT COUNT(*) AS orders,COUNT(DISTINCT a.attempt_id) AS attempts,COUNT(DISTINCT c.callback_event_id) AS callbacks,
                   SUM(o.status='PAID' AND a.state='SUCCEEDED' AND a.amount_minor=o.total_price_minor) AS paid
            FROM shopping_checkout_order x JOIN standard_order o ON o.order_id=x.order_id
            JOIN mock_payment_attempt a ON a.order_kind='STANDARD' AND a.order_id=o.order_id
            JOIN mock_payment_callback c ON c.attempt_id=a.attempt_id WHERE x.checkout_id=%s
        """,
            (checkout_id,),
        )
        assert (
            final[0]["orders"]
            == final[0]["attempts"]
            == final[0]["callbacks"]
            == final[0]["paid"]
            == 2
        )
