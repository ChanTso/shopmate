"""Explicit real-service checks: run with pytest integration_tests, never by default.

Requires the isolated Java/Auth/SQL fixture and private .run credentials. The write test
changes only the fixture coffee/tea products through actual operator approval. It does not
reset them: the environment owner resets the fixture before model acceptance.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
from dataclasses import replace
from datetime import UTC, datetime

import aiomysql
import httpx
import pytest
from merchant_agent import MerchantSessionContext
from merchant_agent.types import PriceUpdateItem

from shopmate.analysis_sql import AnalysisQueryError, AnalysisSQL, capture_analysis_queries
from shopmate.app import create_app
from shopmate.auth import AuthClient, RequestIdentity, bind_context
from shopmate.backend import CityBuddyMerchantBackend
from shopmate.commerce_client import CommerceClient
from shopmate.sessions import SessionStore
from shopmate.settings import ROOT, Settings

COFFEE = "shopmate-fixture-coffee"
TEA = "shopmate-fixture-tea"


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


async def test_sql_account_has_three_views_but_no_base_table_or_write_privilege(settings):
    # Do not set transaction_read_only here: this check exercises the account grants themselves.
    connection = await _analysis_connection(settings)
    try:
        async with connection.cursor() as cursor:
            for view in ("merchant_products", "merchant_paid_orders", "merchant_daily_sales"):
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
    assert corrected.rows == [[7]] and not corrected.truncated
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
        assert after.rows == [[7]] and not after.truncated
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
        assert result.rows == [[7]]
    finally:
        await limited.close()


async def test_running_host_http_reads_use_real_business_data():
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
        snapshot = overview.json()["snapshot"]
        assert snapshot["currency"] == "CNY" and snapshot["sales"] == 2304
        assert snapshot["units"] == 96 and snapshot["traffic"] is None
        products = await http.get("/api/merchant/listings", headers=headers)
        assert products.status_code == 200 and products.json()["total"] == 7
        detail = await http.get(f"/api/merchant/listings/{COFFEE}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["listing"]["attributes"]["price_editable"] == "true"


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
        settings, auth=auth, store=store, backend=backend, agent=object(), provider=object()
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
            "citybuddy_sha": ROOT.parent / "citybuddy",
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
        settings, auth=auth, store=store, backend=backend, agent=object(), provider=object()
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
            apply_path = f"/api/merchant/price-drafts/{change.change_id}/apply"
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
