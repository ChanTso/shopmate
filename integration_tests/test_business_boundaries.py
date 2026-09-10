"""Explicit real-service checks: run with pytest integration_tests, never by default.

Requires the isolated Java/Auth/SQL fixture and private .run credentials. The write test
changes only the reserved retail products through actual operator approval. It does not
reset them: the environment owner resets the fixture before model acceptance.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import aiomysql
import httpx
import pytest
from merchant_agent import MerchantSessionContext
from merchant_agent.types import CampaignDraft, InventoryActionItem, PriceUpdateItem, PromotionDraft

from shopmate.analysis_sql import AnalysisQueryError, AnalysisSQL, capture_analysis_queries
from shopmate.app import create_app
from shopmate.auth import AuthClient, RequestIdentity, bind_context
from shopmate.backend import CityBuddyMerchantBackend
from shopmate.commerce_client import CommerceClient
from shopmate.sessions import SessionStore
from shopmate.settings import ROOT, Settings

COFFEE = "AR-1001"
TEA = "AR-1004"


@pytest.fixture
def settings():
    return Settings.load()


def _password() -> str:
    return (ROOT / ".run/operator_password").read_text().strip()


async def _analysis_connection(settings, *, timeout_ms=None):
    command = "SET SESSION time_zone = '+00:00'"
    if timeout_ms is not None:
        command += f", max_execution_time = {int(timeout_ms)}"
    return await aiomysql.connect(
        host=settings.sql_host,
        port=settings.sql_port,
        user=settings.sql_user,
        password=settings.sql_password,
        db=settings.sql_database,
        autocommit=True,
        connect_timeout=5,
        charset="utf8mb4",
        init_command=command,
    )


@pytest.fixture
async def sql(settings):
    value = AnalysisSQL(settings)
    await value.start()
    try:
        yield value
    finally:
        await value.close()


async def test_sql_account_has_six_views_but_no_base_table_or_write_privilege(settings):
    # Do not set transaction_read_only here: this check exercises the account grants themselves.
    connection = await _analysis_connection(settings)
    try:
        async with connection.cursor() as cursor:
            for view in (
                "merchant_products",
                "merchant_paid_orders",
                "merchant_daily_sales",
                "merchant_listing_facts",
                "merchant_store_traffic_daily",
                "merchant_campaign_facts",
            ):
                await cursor.execute(f"SELECT COUNT(*) FROM {view}")
                assert (await cursor.fetchone())[0] > 0
            for table in ("product", "standard_order", "merchant_price_draft"):
                with pytest.raises(aiomysql.OperationalError) as failure:
                    await cursor.execute(f"SELECT * FROM {table} LIMIT 1")
                assert failure.value.args[0] in (1142, 1143)
            # The false predicate makes a misconfigured grant fail without changing any row.
            with pytest.raises(aiomysql.OperationalError) as failure:
                await cursor.execute(
                    "UPDATE merchant_products SET price_minor = price_minor WHERE 1 = 0"
                )
            assert failure.value.args[0] in (1142, 1143)
    finally:
        connection.close()


async def test_sql_real_error_can_be_corrected_and_result_truncation_is_explicit(settings, sql):
    with pytest.raises(AnalysisQueryError, match="Unknown column"):
        await sql.query("SELECT missing_business_column FROM merchant_products")
    corrected = await sql.query("SELECT COUNT(*) AS product_count FROM merchant_products")
    assert corrected.rows == [[104]] and not corrected.truncated
    limited = AnalysisSQL(replace(settings, sql_max_rows=2))
    await limited.start()
    try:
        result = await limited.query(
            "SELECT product_id, name FROM merchant_products ORDER BY product_id"
        )
        assert len(result.rows) == 2 and result.truncated and "unknown" in result.note
        assert len(result.model_dump_json().encode()) <= settings.sql_max_bytes
        # The capped unbuffered connection is discarded; a subsequent acquisition is still usable.
        after = await limited.query("SELECT COUNT(*) AS product_count FROM merchant_products")
        assert after.rows == [[104]] and not after.truncated
    finally:
        await limited.close()


def _expensive_select() -> str:
    # An aggregate avoids materializing a large result while exercising real database work.
    sources = " CROSS JOIN ".join(f"merchant_products p{i}" for i in range(9))
    terms = " + ".join(f"p{i}.price_minor" for i in range(9))
    return f"SELECT SUM({terms}) AS amount_sum FROM {sources}"


async def test_sql_real_server_execution_limit_and_host_deadline(settings):
    connection = await _analysis_connection(settings, timeout_ms=50)
    try:
        async with connection.cursor() as cursor:
            with pytest.raises(aiomysql.OperationalError) as failure:
                await cursor.execute(_expensive_select())
            assert failure.value.args[0] == 3024
    finally:
        connection.close()
    limited = AnalysisSQL(replace(settings, sql_timeout_ms=50))
    await limited.start()
    try:
        with pytest.raises(AnalysisQueryError, match="deadline"):
            await limited.query(_expensive_select())
        result = await limited.query("SELECT COUNT(*) AS product_count FROM merchant_products")
        assert result.rows == [[104]]
    finally:
        await limited.close()


async def test_running_host_http_reads_use_real_business_data(truth, settings):
    base = os.environ.get("SHOPMATE_BASE_URL", "http://127.0.0.1:8101")
    async with httpx.AsyncClient(base_url=base, timeout=30, follow_redirects=False) as http:
        login = await http.post(
            "/api/merchant/login",
            json={
                "loginIdentifier": "shopmate-fixture-operator",
                "password": _password(),
            },
        )
        assert login.status_code == 200
        headers = {"Authorization": "Bearer " + login.json()["accessToken"]}
        session = await http.post("/api/merchant/session", headers=headers)
        assert session.status_code == 200
        headers["X-Session-Id"] = session.json()["session_id"]
        overview = await http.get("/api/merchant/overview", headers=headers)
        assert overview.status_code == 200
        home = overview.json()
        snapshot = home["snapshot"]
        end = datetime.fromisoformat(settings.as_of)
        start = end - timedelta(days=14)
        expected = (
            await _rows(
                truth,
                "SELECT SUM(total_price_minor) AS amount, SUM(quantity) AS units, COUNT(*) AS orders "
                "FROM merchant_paid_orders WHERE currency='CNY' AND succeeded_at>=%s AND succeeded_at<%s",
                (
                    start.astimezone(UTC).replace(tzinfo=None),
                    end.astimezone(UTC).replace(tzinfo=None),
                ),
            )
        )[0]
        visits = (
            await _rows(
                truth,
                "SELECT SUM(visits) AS visits FROM retail_store_traffic_daily WHERE local_date>=%s AND local_date<%s",
                (start.date(), end.date()),
            )
        )[0]["visits"]
        assert (
            snapshot["currency"] == "CNY" and snapshot["sales"] == float(expected["amount"]) / 100
        )
        assert snapshot["units"] == expected["units"] and snapshot["orders"] == expected["orders"]
        assert snapshot["traffic"] == visits
        expected_orders = await _rows(
            truth,
            "WITH orders AS (SELECT 'STANDARD' AS kind,order_id,status,created_at,quantity,"
            "total_price_minor,currency FROM standard_order WHERE sandbox_id IS NULL UNION ALL "
            "SELECT 'SECKILL',order_id,status,created_at,quantity,total_price_minor,currency FROM seckill_order) "
            "SELECT * FROM orders ORDER BY created_at DESC,order_id DESC,kind LIMIT 6",
        )
        assert len(home["recent_orders"]) == len(expected_orders) == 6
        for order, expected_order in zip(home["recent_orders"], expected_orders, strict=True):
            assert (order["orderKind"], order["orderId"], order["status"]) == (
                expected_order["kind"],
                expected_order["order_id"],
                expected_order["status"],
            )
            assert (
                datetime.fromisoformat(order["createdAt"]).astimezone(UTC).replace(tzinfo=None)
                == expected_order["created_at"]
            )
            assert order["product"]["quantity"] == expected_order["quantity"]
            assert order["product"]["totalPriceMinor"] == expected_order["total_price_minor"]
            assert order["product"]["currency"] == expected_order["currency"]
            payments = await _rows(
                truth,
                "SELECT state,amount_minor,refunded_amount_minor FROM mock_payment_attempt "
                "WHERE order_kind=%s AND order_id=%s AND sandbox_id IS NULL",
                (order["orderKind"], order["orderId"]),
            )
            if payments:
                assert order["payment"]["state"] == payments[0]["state"]
                assert order["payment"]["amountMinor"] == payments[0]["amount_minor"]
                assert (
                    order["payment"]["refundedAmountMinor"] == payments[0]["refunded_amount_minor"]
                )
            else:
                assert order["payment"] is None
            fulfillment = (
                await _rows(
                    truth,
                    "SELECT stage,source_ref FROM retail_order_fulfillment WHERE order_id=%s",
                    (order["orderId"],),
                )
                if order["orderKind"] == "STANDARD"
                else []
            )
            if fulfillment:
                assert order["fulfillment"]["stage"] == fulfillment[0]["stage"]
                assert order["fulfillment"]["sourceRef"] == fulfillment[0]["source_ref"]
            else:
                assert order["fulfillment"] is None
        daily = await _rows(
            truth,
            "SELECT DATE(DATE_ADD(succeeded_at,INTERVAL 8 HOUR)) AS day, "
            "SUM(total_price_minor)/100 AS sales,COUNT(*) AS orders,AVG(total_price_minor)/100 AS aov "
            "FROM merchant_paid_orders WHERE currency='CNY' AND succeeded_at>=%s AND succeeded_at<%s "
            "GROUP BY day ORDER BY day",
            (start.astimezone(UTC).replace(tzinfo=None), end.astimezone(UTC).replace(tzinfo=None)),
        )
        for name, column in (
            ("sales", "sales"),
            ("orders", "orders"),
            ("average_order_value", "aov"),
        ):
            actual = {point["date"]: point["value"] for point in home["trends"][name]}
            assert actual == pytest.approx({str(row["day"]): float(row[column]) for row in daily})
        conversion = await _rows(
            truth,
            "SELECT t.local_date AS day,100.0*COALESCE(p.orders,0)/NULLIF(t.visits,0) AS value "
            "FROM retail_store_traffic_daily t LEFT JOIN "
            "(SELECT DATE(DATE_ADD(succeeded_at,INTERVAL 8 HOUR)) AS day,COUNT(*) AS orders "
            "FROM merchant_paid_orders WHERE currency='CNY' AND succeeded_at>=%s AND succeeded_at<%s "
            "GROUP BY day) p ON p.day=t.local_date WHERE t.local_date>=%s AND t.local_date<%s ORDER BY day",
            (
                start.astimezone(UTC).replace(tzinfo=None),
                end.astimezone(UTC).replace(tzinfo=None),
                start.date(),
                end.date(),
            ),
        )
        assert {
            point["date"]: point["value"] for point in home["trends"]["conversion"]
        } == pytest.approx(
            {str(row["day"]): float(row["value"]) for row in conversion if row["value"] is not None}
        )
        assert home["prior_window"]["end"] == home["window"]["start"]
        products, offset = [], 0
        while offset is not None:
            page = await http.get(
                "/api/merchant/listings", headers=headers, params={"limit": 50, "offset": offset}
            )
            assert page.status_code == 200
            products.extend(page.json()["listings"])
            offset = page.json()["next_offset"]
        assert len(products) == len({row["listing_id"] for row in products}) == 87
        detail = await http.get(f"/api/merchant/listings/{COFFEE}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["listing"]["price_editable"] is True
        issues = await http.get("/api/merchant/order-issues", headers=headers)
        assert issues.status_code == 200
        issue = next(row for row in issues.json()["order_issues"] if row["issue_id"] == "ISS-101")
        expected_issue = (
            await _rows(
                truth,
                "SELECT order_id, buyer_message_excerpt FROM retail_order_issue WHERE issue_id='ISS-101'",
            )
        )[0]
        assert issue["order_id"] == expected_issue["order_id"]
        assert issue["buyer_message_excerpt"] == expected_issue["buyer_message_excerpt"]
        assert issue["listing_id"] == "AR-1804" and issue["refund_requested_order_count"] == 6
        assert issue["source_kind"] == "FIXTURE" and issue["source_ref"]


@pytest.fixture
async def truth():
    values = json.loads((ROOT / ".run/truth-settings.json").read_text())
    connection = await aiomysql.connect(
        host=values["sql_host"],
        port=values["sql_port"],
        user=values["sql_user"],
        password=values["sql_password"],
        db=values["sql_database"],
        autocommit=True,
        connect_timeout=5,
        charset="utf8mb4",
        init_command="SET SESSION time_zone = '+00:00', transaction_read_only = 1",
    )
    try:
        yield connection
    finally:
        connection.close()


async def _rows(connection, sql, values=()):
    async with connection.cursor(aiomysql.DictCursor) as cursor:
        await cursor.execute(sql, values)
        return list(await cursor.fetchall())


async def _products(connection):
    return await _rows(
        connection,
        """
        SELECT product_id, price_minor, publication_version, stock_quantity, available
        FROM product WHERE product_id IN (%s, %s) ORDER BY product_id
        """,
        (COFFEE, TEA),
    )


async def _paid_truth(connection):
    return await _rows(
        connection,
        """
        SELECT o.product_id, COUNT(*) AS orders, SUM(o.quantity) AS units,
               SUM(o.total_price_minor) AS amount_minor
        FROM standard_order o
        JOIN mock_payment_attempt a ON a.order_kind = 'STANDARD' AND a.order_id = o.order_id
        WHERE o.product_id IN (%s, %s) AND o.status = 'PAID'
          AND o.sandbox_id IS NULL AND a.sandbox_id IS NULL
          AND a.state = 'SUCCEEDED' AND a.succeeded_at IS NOT NULL
          AND a.user_subject = o.user_subject
          AND a.amount_minor = o.total_price_minor AND a.currency = o.currency
        GROUP BY o.product_id ORDER BY o.product_id
        """,
        (COFFEE, TEA),
    )


async def test_write_prepare_operator_approval_conflict_and_replay_have_sql_truth(
    settings, truth, tmp_path
):
    auth, client, sql = (
        AuthClient(settings),
        CommerceClient(settings.commerce_url),
        AnalysisSQL(settings),
    )
    store = SessionStore(tmp_path / "business-integration.sqlite3")
    await sql.start()
    backend = CityBuddyMerchantBackend(auth, store, client, sql)
    # No model/client is constructed. The real host routes still call real Auth and Java services.
    app = create_app(
        settings,
        auth=auth,
        store=store,
        backend=backend,
        agent=object(),
        buyer_agent=object(),
        provider=object(),
    )
    try:
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://shopmate.integration"
            ) as http,
        ):
            login = await http.post(
                "/api/merchant/login",
                json={
                    "loginIdentifier": "shopmate-fixture-operator",
                    "password": _password(),
                },
            )
            assert login.status_code == 200
            identity = RequestIdentity(login.json()["subject"], login.json()["accessToken"])
            headers = {"Authorization": "Bearer " + identity.token}
            created = await http.post("/api/merchant/session", headers=headers)
            assert created.status_code == 200
            session_id = created.json()["session_id"]
            headers["X-Session-Id"] = session_id
            session = MerchantSessionContext(
                session_id=session_id,
                merchant_id="citybuddy",
                operator=identity.subject,
                now=datetime.now(UTC),
            )

            async def prepare(prices):
                current = store.get(session_id, identity.subject)
                turn_id = store.begin_turn(current)
                try:
                    with bind_context(identity, session_id, turn_id):
                        change = await backend.stage_price_update(
                            session,
                            [
                                PriceUpdateItem(listing_id=product_id, new_price=minor / 100)
                                for product_id, minor in prices.items()
                            ],
                        )
                    return change
                finally:
                    store.finish_turn(current, "completed")

            before = await _products(truth)
            history_before = await _paid_truth(truth)
            baseline = {row["product_id"]: row for row in before}
            stale = await prepare(
                {product_id: row["price_minor"] + 10 for product_id, row in baseline.items()}
            )
            assert await _products(truth) == before
            stored = await _rows(
                truth,
                "SELECT state, items, result FROM merchant_price_draft WHERE draft_id = %s",
                (stale.change_id,),
            )
            assert stored[0]["state"] == "PREPARED" and stored[0]["result"] is None
            competitor = await prepare({TEA: baseline[TEA]["price_minor"] + 20})
            applied = await http.post(
                f"/api/merchant/changes/{competitor.change_id}/apply", headers=headers
            )
            assert applied.status_code == 200 and applied.json()["ok"] is True
            after_competitor = await _products(truth)
            rejected = await http.post(
                f"/api/merchant/changes/{stale.change_id}/apply", headers=headers
            )
            assert rejected.status_code == 200 and rejected.json()["ok"] is False
            assert rejected.json()["receipt"]["state"] == "REJECTED"
            assert rejected.json()["receipt"]["result"]["reason"] == "VERSION_CONFLICT"
            assert await _products(truth) == after_competitor
            assert after_competitor[0] == before[0]
            rejected_truth = await _rows(
                truth,
                "SELECT state, result FROM merchant_price_draft WHERE draft_id = %s",
                (stale.change_id,),
            )
            assert rejected_truth[0]["state"] == "REJECTED"
            assert json.loads(rejected_truth[0]["result"])["productId"] == TEA

            fresh_prices = {row["product_id"]: row["price_minor"] + 10 for row in after_competitor}
            fresh = await prepare(fresh_prices)
            success = await http.post(
                f"/api/merchant/changes/{fresh.change_id}/apply", headers=headers
            )
            assert success.status_code == 200 and success.json()["ok"] is True
            receipt = success.json()["receipt"]
            assert receipt["state"] == "APPLIED" and len(receipt["result"]["changes"]) == 2
            final = await _products(truth)
            for row in final:
                assert row["price_minor"] == fresh_prices[row["product_id"]]
                assert row["publication_version"] == baseline[row["product_id"]][
                    "publication_version"
                ] + (2 if row["product_id"] == TEA else 1)
                assert row["stock_quantity"] == baseline[row["product_id"]]["stock_quantity"]
                assert row["available"] == baseline[row["product_id"]]["available"]
            assert await _paid_truth(truth) == history_before
            event_ids = [item["eventId"] for item in receipt["result"]["changes"]]
            events = await _rows(
                truth,
                """
                SELECT event_id, aggregate_id, aggregate_version, event_type
                FROM commerce_outbox WHERE event_id IN (%s, %s) ORDER BY aggregate_id
                """,
                tuple(event_ids),
            )
            assert len(events) == 2
            assert all(event["event_type"] == "PRODUCT_PUBLICATION_CHANGED" for event in events)
            assert {event["aggregate_id"] for event in events} == {COFFEE, TEA}
            duplicate = await http.post(
                f"/api/merchant/changes/{fresh.change_id}/apply", headers=headers
            )
            assert duplicate.status_code == 200 and duplicate.json()["receipt"] == receipt
            assert await _products(truth) == final
            readback = await http.get(f"/api/merchant/changes/{fresh.change_id}", headers=headers)
            assert readback.status_code == 200 and readback.json()["receipt"] == receipt
            for product_id, minor in fresh_prices.items():
                detail = await http.get(f"/api/merchant/listings/{product_id}", headers=headers)
                assert detail.status_code == 200
                assert detail.json()["listing"]["price"] == minor / 100
    finally:
        store.close()
        await sql.close()
        await client.close()
        await auth.close()


async def test_committed_approval_recovers_after_host_loses_response(settings, truth, tmp_path):
    revisions = {
        name: (
            await asyncio.to_thread(
                subprocess.check_output, ["git", "-C", str(path), "rev-parse", "HEAD"], text=True
            )
        ).strip()
        for name, path in {
            "citybuddy_sha": settings.citybuddy_dir,
            "shopmate_sha": ROOT,
        }.items()
    }
    lost = False
    apply_path = None

    async def lose_one_committed_response(response):
        nonlocal lost
        if (
            not lost
            and response.request.method == "POST"
            and response.request.url.path == apply_path
            and response.status_code == 200
        ):
            # Real Java has answered 200; withhold that response before CommerceClient observes it.
            lost = True
            await response.aclose()
            raise httpx.ReadError("Injected post-commit response loss", request=response.request)

    java_http = httpx.AsyncClient(
        timeout=15, follow_redirects=False, event_hooks={"response": [lose_one_committed_response]}
    )
    auth = AuthClient(settings)
    client = CommerceClient(settings.commerce_url, http_client=java_http)
    sql = AnalysisSQL(settings)
    store = SessionStore(tmp_path / "approval-response-loss.sqlite3")
    backend = CityBuddyMerchantBackend(auth, store, client, sql)
    app = create_app(
        settings,
        auth=auth,
        store=store,
        backend=backend,
        agent=object(),
        buyer_agent=object(),
        provider=object(),
    )
    try:
        await sql.start()
        async with (
            app.router.lifespan_context(app),
            httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://shopmate.integration"
            ) as http,
        ):
            login = await http.post(
                "/api/merchant/login",
                json={
                    "loginIdentifier": "shopmate-fixture-operator",
                    "password": _password(),
                },
            )
            assert login.status_code == 200
            identity = RequestIdentity(login.json()["subject"], login.json()["accessToken"])
            headers = {"Authorization": "Bearer " + identity.token}
            created = await http.post("/api/merchant/session", headers=headers)
            assert created.status_code == 200
            session_id = created.json()["session_id"]
            headers["X-Session-Id"] = session_id
            session = MerchantSessionContext(
                session_id=session_id,
                merchant_id="citybuddy",
                operator=identity.subject,
                now=datetime.now(UTC),
            )
            baseline = {row["product_id"]: row for row in await _products(truth)}

            async def snapshot():
                return {
                    "products": await _products(truth),
                    "paid_history": await _paid_truth(truth),
                    "generation": await _rows(
                        truth,
                        "SELECT publication_generation FROM catalog_metadata WHERE singleton_id=1",
                    ),
                    "new_events": await _rows(
                        truth,
                        """
                        SELECT event_id, aggregate_id, aggregate_version, event_type
                        FROM commerce_outbox
                        WHERE aggregate_type = 'PRODUCT' AND aggregate_id = %s
                          AND aggregate_version > %s
                        ORDER BY aggregate_version, event_id
                        """,
                        (COFFEE, baseline[COFFEE]["publication_version"]),
                    ),
                }

            before = await snapshot()
            assert before["new_events"] == []
            print(json.dumps({**revisions, "phase": "before_prepare", **before}, default=str))
            current = store.get(session_id, identity.subject)
            turn_id = store.begin_turn(current)
            try:
                with bind_context(identity, session_id, turn_id):
                    change = await backend.stage_price_update(
                        session,
                        [
                            PriceUpdateItem(
                                listing_id=COFFEE,
                                new_price=(baseline[COFFEE]["price_minor"] + 10) / 100,
                            )
                        ],
                    )
            finally:
                store.finish_turn(current, "completed")
            assert await snapshot() == before
            apply_path = f"/api/merchant/changes/{change.change_id}/apply"
            host_path = f"/api/merchant/changes/{change.change_id}"
            unavailable = await http.post(host_path + "/apply", headers=headers)
            assert lost and unavailable.status_code == 503
            assert unavailable.json()["category"] == "COMMERCE_UNAVAILABLE"

            draft = await _rows(
                truth,
                "SELECT state, result FROM merchant_price_draft WHERE draft_id = %s",
                (change.change_id,),
            )
            committed = await snapshot()
            print(
                json.dumps(
                    {**revisions, "phase": "response_lost", "draft": draft, **committed},
                    default=str,
                )
            )
            assert draft[0]["state"] == "APPLIED"
            result = json.loads(draft[0]["result"])
            assert len(result["changes"]) == 1
            expected_products = [
                {
                    **row,
                    "price_minor": row["price_minor"] + (10 if row["product_id"] == COFFEE else 0),
                    "publication_version": row["publication_version"]
                    + (1 if row["product_id"] == COFFEE else 0),
                }
                for row in before["products"]
            ]
            assert committed["products"] == expected_products
            assert committed["paid_history"] == before["paid_history"]
            assert committed["generation"][0]["publication_generation"] == (
                before["generation"][0]["publication_generation"] + 1
            )
            assert committed["new_events"] == [
                {
                    "event_id": result["changes"][0]["eventId"],
                    "aggregate_id": COFFEE,
                    "aggregate_version": baseline[COFFEE]["publication_version"] + 1,
                    "event_type": "PRODUCT_PUBLICATION_CHANGED",
                }
            ]
            readback = await http.get(host_path, headers=headers)
            assert readback.status_code == 200
            receipt = readback.json()["receipt"]
            assert receipt["state"] == "APPLIED" and receipt["result"] == result
            retry = await http.post(host_path + "/apply", headers=headers)
            assert retry.status_code == 200 and retry.json()["ok"] is True
            assert retry.json()["receipt"] == receipt
            recovered = await snapshot()
            print(json.dumps({**revisions, "phase": "get_and_retry", **recovered}, default=str))
            assert recovered == committed
    finally:
        store.close()
        await sql.close()
        await client.close()
        await java_http.aclose()
        await auth.close()


async def test_unsigned_subtraction_reports_code_and_signed_query_recovers(sql):
    with capture_analysis_queries() as records:
        with pytest.raises(AnalysisQueryError, match="SIGNED") as failure:
            await sql.query("SELECT CAST(0 AS UNSIGNED) - CAST(1 AS UNSIGNED) AS difference")
        assert failure.value.mysql_error_code == 1690
        corrected = await sql.query("SELECT CAST(0 AS SIGNED) - CAST(1 AS SIGNED) AS difference")
    assert corrected.rows == [[-1]] and not corrected.truncated
    assert records[0]["status"] == "error" and records[0]["mysql_error_code"] == 1690
    assert records[1]["status"] == "success" and records[1]["result"]["rows"] == [[-1]]


async def test_full_retail_changes_apply_to_live_authority_and_restore(settings, truth, tmp_path):
    auth, client, sql = (
        AuthClient(settings),
        CommerceClient(settings.commerce_url),
        AnalysisSQL(settings),
    )
    store = SessionStore(tmp_path / "retail-actions.sqlite3")
    backend = CityBuddyMerchantBackend(
        auth, store, client, sql, datetime.fromisoformat(settings.as_of)
    )
    await sql.start()
    try:
        login = await auth.login("shopmate-fixture-operator", _password())
        identity = RequestIdentity(login["subject"], login["accessToken"])
        record = store.create(identity.subject)
        session = MerchantSessionContext(
            session_id=record.session_id,
            merchant_id="citybuddy",
            operator=identity.subject,
            now=datetime.now(UTC),
            timezone="Asia/Shanghai",
        )

        async def stage(call):
            record = store.get(session.session_id, identity.subject)
            turn = store.begin_turn(record)
            try:
                with bind_context(identity, session.session_id, turn):
                    return await call()
            finally:
                store.finish_turn(record, "completed")

        with bind_context(identity, session.session_id):
            family_before = await backend.get_listing(session, "AR-1606")
        change = await stage(
            lambda: backend.stage_listing_update(
                session, "AR-1606", {"material": "Silk fixture approval"}
            )
        )
        with bind_context(identity, session.session_id):
            assert (await backend.apply_by_operator(session, change.change_id))["ok"]
            for variant in family_before.variants:
                actual = await backend.get_listing(session, variant.listing_id)
                assert actual.attributes["material"] == "Silk fixture approval"
            paused = await backend.get_listing(session, "AR-1207")
        change = await stage(
            lambda: backend.stage_inventory_action(
                session, [InventoryActionItem(listing_id="AR-1207", action="restock", quantity=5)]
            )
        )
        with bind_context(identity, session.session_id):
            assert (await backend.apply_by_operator(session, change.change_id))["ok"]
            stocked = await backend.get_listing(session, "AR-1207")
            assert stocked.stock == paused.stock + 5 and stocked.status == "paused"

        now = datetime.now(UTC)
        future = await stage(
            lambda: backend.stage_promotion(
                session,
                PromotionDraft(
                    name="Future sale",
                    listing_ids=["AR-1806"],
                    discount_pct=10,
                    starts=(now + timedelta(days=1)).isoformat(),
                    ends=(now + timedelta(days=2)).isoformat(),
                ),
            )
        )
        from shopmate.commerce_client import CommerceError

        with bind_context(identity, session.session_id):
            with pytest.raises(CommerceError) as early:
                await backend.apply_by_operator(session, future.change_id)
            assert early.value.category == "promotion_not_started"
            assert (await backend.get_change(session, future.change_id)).status == "staged"
            assert (await backend.discard_by_operator(session, future.change_id))["ok"]
            before = await backend.get_listing(session, "AR-1806")
        sale = await stage(
            lambda: backend.stage_promotion(
                session,
                PromotionDraft(
                    name="Current sale",
                    listing_ids=["AR-1806"],
                    discount_pct=10,
                    starts=(now - timedelta(minutes=1)).isoformat(),
                    ends=(now + timedelta(days=1)).isoformat(),
                ),
            )
        )
        with bind_context(identity, session.session_id):
            result = await backend.apply_by_operator(session, sale.change_id)
            assert result["ok"]
            after = await backend.get_listing(session, "AR-1806")
            assert round(after.price * 100) == round(before.price * 90)
            promotions = await backend.promotions_page(session)
            promotion = next(
                row for row in promotions["items"] if row["sourceChangeId"] == sale.change_id
            )
            assert promotion["state"] == "active"
            assert promotion["targets"][0]["currentPriceMinor"] == round(after.price * 100)
            assert not promotion["targets"][0]["overridden"]
            assert await backend.promotion_detail(session, promotion["promotionId"]) == promotion
            assert (await backend.apply_by_operator(session, sale.change_id))["receipt"] == result[
                "receipt"
            ]

        observed = await _rows(
            truth,
            "SELECT revenue_minor,spend_minor,observation_source_ref FROM retail_campaign WHERE campaign_id='C-203'",
        )
        campaign = await stage(
            lambda: backend.stage_campaign(
                session,
                CampaignDraft(
                    campaign_id="C-203",
                    name="Local approved plan",
                    budget=None,
                    copy_text="Review in local workspace",
                ),
            )
        )
        with bind_context(identity, session.session_id):
            assert (await backend.apply_by_operator(session, campaign.change_id))["ok"]
            reread = await backend.get_campaign_performance(session)
            target = next(row for row in reread if row.campaign_id == "C-203")
            assert target.budget is None and target.revenue is None
            record = store.get(session.session_id, identity.subject)
            record.state.seen_campaigns["C-203"] = target
            store.save(record)
            assert (
                store.get(session.session_id, identity.subject).state.seen_campaigns["C-203"].budget
                is None
            )
        assert (
            await _rows(
                truth,
                "SELECT revenue_minor,spend_minor,observation_source_ref FROM retail_campaign WHERE campaign_id='C-203'",
            )
            == observed
        )
        rows = await _rows(
            truth,
            "SELECT kind,state FROM merchant_price_draft WHERE session_id=%s",
            (session.session_id,),
        )
        assert {row["kind"] for row in rows if row["state"] == "APPLIED"} == {
            "LISTING_UPDATE",
            "INVENTORY_ACTION",
            "PROMOTION",
            "CAMPAIGN",
        }
    finally:
        store.close()
        await sql.close()
        await client.close()
        await auth.close()


def test_fixture_preflight_protects_exact_owners_and_unrelated_change_records(monkeypatch):
    import importlib
    from uuid import uuid4

    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    runtime = importlib.import_module("local_runtime")
    retail = importlib.import_module("retail_fixture")
    queries = retail.preflight_queries()
    assert all(runtime.sql(query) == "0" for query in queries.values())
    # Exercise the real ai_ci order column; a differently cased subject is not our fixture owner.
    case = runtime.sql(
        "START TRANSACTION; UPDATE standard_order SET user_subject='Shopmate-retail-history' "
        "WHERE user_subject='shopmate-retail-history' LIMIT 1; "
        + queries["non-fixture order references"]
        + "ROLLBACK;"
    )
    assert case == "1"
    statements = []
    for kind, item, payload in (
        ("PRICE_UPDATE", {"productId": "AR-1001"}, None),
        (
            "LISTING_UPDATE",
            {"target": "AR-1606", "field": "material", "before": "a", "after": "b"},
            {},
        ),
        (
            "INVENTORY_ACTION",
            {"target": "AR-1207", "field": "stock", "before": 64, "after": 69},
            {},
        ),
    ):
        statements.append(
            retail.insert(
                "merchant_price_draft",
                draft_id=str(uuid4()),
                operator_subject="Shopmate-fixture-operator",
                session_id="maintenance-reference",
                request_key=str(uuid4()),
                intent_hash="a" * 64,
                currency="CNY",
                state="PREPARED",
                kind=kind,
                items=[item],
                payload=payload,
            )
        )
    changes = runtime.sql(
        "START TRANSACTION;"
        + "".join(statements)
        + queries["non-fixture product changes"]
        + "ROLLBACK;"
    )
    assert changes == "3"
    assert all(runtime.sql(query) == "0" for query in queries.values())


async def test_live_catalog_counts_and_campaign_window_reach_model_context(settings, sql, truth):
    from uuid import uuid4

    auth = AuthClient(settings)
    client = CommerceClient(settings.commerce_url)
    backend = CityBuddyMerchantBackend(auth, None, client, sql)
    try:
        login = await auth.login("shopmate-fixture-operator", _password())
        identity = RequestIdentity(login["subject"], login["accessToken"])
        session = MerchantSessionContext(
            session_id=str(uuid4()),
            merchant_id="citybuddy",
            operator=identity.subject,
            now=datetime.now(UTC),
        )
        with bind_context(identity, session.session_id):
            context = await backend.get_merchant_context(session)
            schema = json.loads((await backend.get_analysis_schema(session)).split("\n\n", 1)[0])
            campaigns = await backend.get_campaign_performance(session, "C-203")
        counts = context["current_catalog_counts"]
        assert counts == schema["current_catalog_counts"]
        assert not counts["truncated"]
        currency, skus, roots, sellable = counts["rows"][0]
        assert (currency, skus, roots) == ("CNY", 104, 87)
        actual = await _rows(
            truth,
            "SELECT COUNT(*) AS sellable FROM product WHERE currency='CNY' "
            "AND publication_state='PUBLISHED' AND available=1 AND stock_quantity>0",
        )
        assert sellable == actual[0]["sellable"]
        assert len(campaigns) == 1
        campaign = campaigns[0]
        assert campaign.observation_start == "2026-06-15T00:00:00+08:00"
        assert campaign.observation_end == "2026-07-16T00:00:00+08:00"
        assert campaign.observation_period.endswith("2026-07-16T00:00:00+08:00（不含）")
    finally:
        await auth.close()
        await client.close()
