from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from merchant_agent.changes import ChangeNotApplicable
from merchant_agent.tools.registry import build_tools
from merchant_agent.types import (
    AnalysisTable,
    ListingFilters,
    MerchantSessionContext,
    PriceUpdateItem,
)

from shopmate.auth import RequestIdentity, bind_context
from shopmate.backend import CityBuddyMerchantBackend, ShopMateConfig, reporting_period
from shopmate.buyer_client import OrderView
from shopmate.commerce_client import (
    ChangeView,
    CommerceError,
    InventoryView,
    IssueView,
    ListingView,
    PageView,
    ProductView,
    SummaryView,
    WindowView,
)
from shopmate.sessions import SessionStore


class Auth:
    def __init__(self):
        self.scopes = []
        self.denied = False

    async def exchange(self, identity, session_id, scope):
        self.scopes.append((identity.subject, session_id, scope))
        if self.denied:
            raise HTTPException(403, "No merchant permission")
        return "obo:" + scope


class SQL:
    def __init__(self):
        self.calls = []

    async def query(self, sql):
        self.calls.append(sql)
        if "SUM(visits)" in sql:
            return AnalysisTable(columns=["visits", "observed_days"], rows=[[None, 0]], row_count=1)
        return AnalysisTable(columns=["bucket", "value"], rows=[["2026-08-22", 11500]], row_count=1)


class Client:
    def __init__(self):
        self.products_by_id = {
            key: ProductView(
                productId=key,
                name=key,
                priceMinor=amount,
                currency=currency,
                publicationVersion=3,
                stockQuantity=50,
                available=True,
                publicationState="PUBLISHED",
                priceEditable=True,
            )
            for key, amount, currency in (
                ("coffee", 2400, "CNY"),
                ("tea", 1800, "CNY"),
                ("cocoa", 1100, "USD"),
            )
        }
        self.prepares = []
        self.receipt = None
        self.fail_prepare_once = None
        self.applies = []
        self.cancel_result = "CANCELLED"

    async def product(self, product_id, token, session_id):
        return self.products_by_id.get(product_id.casefold())

    async def products(self, token, session_id):
        return list(self.products_by_id.values())

    async def listing(self, product_id, token, session_id, as_of=None):
        product = await self.product(product_id, token, session_id)
        if not product:
            return None
        return ListingView(
            id=product.productId,
            kind="plain",
            variantOf=None,
            title=product.name,
            shortDescription=None,
            priceMinor=product.priceMinor,
            currency=product.currency,
            stockQuantity=product.stockQuantity,
            available=product.available,
            publicationState=product.publicationState,
            status="active",
            publicationVersion=product.publicationVersion,
            metadataVersion=0,
            familyMetadataVersion=None,
            content={},
            options=[],
            optionValues={},
            contentQuality=None,
            operations=None,
            salesLast30d={
                "orderCount": 0,
                "units": 0,
                "refundRequestedOrderCount": 0,
                "refundRequestedOrderPct": None,
            },
            marginPct=None,
            priceEditable=product.priceEditable,
            window=WindowView(
                start="2026-08-05T16:00:00Z", end="2026-09-04T16:00:00Z", timeZone="Asia/Shanghai"
            ),
            variants=[],
        )

    async def listings(self, token, session_id, **params):
        rows = [await self.listing(key, token, session_id) for key in self.products_by_id]
        if params.get("query"):
            rows = [row for row in rows if params["query"] in row.title]
        if params.get("maxStock") is not None:
            rows = [row for row in rows if row.stockQuantity <= params["maxStock"]]
        if params.get("contentQuality"):
            rows = [row for row in rows if row.contentQuality == params["contentQuality"]]
        rows = rows[params.get("offset", 0) : params.get("offset", 0) + params.get("limit", 20)]
        window = WindowView(
            start="2026-08-05T16:00:00Z", end="2026-09-04T16:00:00Z", timeZone="Asia/Shanghai"
        )
        return PageView[ListingView](items=rows, nextOffset=None, window=window)

    async def inventory(self, token, session_id, **params):
        return PageView[InventoryView](
            items=[],
            nextOffset=None,
            window=WindowView(
                start="2026-08-05T16:00:00Z", end="2026-09-04T16:00:00Z", timeZone="Asia/Shanghai"
            ),
        )

    async def issues(self, token, session_id, limit=100):
        return []

    async def recent_orders(self, token, session_id, *, limit=6):
        return []

    async def changes(self, token, session_id, limit=100, offset=0, state=None):
        return (
            [self.receipt]
            if self.receipt
            and session_id == self.receipt_session
            and offset == 0
            and (state is None or state == self.receipt.state)
            else []
        )

    async def prepare(self, body, key, token, session_id):
        self.prepares.append((body, key, token, session_id))
        body = body.get("payload", body)
        self.receipt_session = session_id
        if self.fail_prepare_once:
            error, self.fail_prepare_once = self.fail_prepare_once, None
            raise error
        self.receipt = ChangeView.model_validate(
            {
                "changeId": "draft-1",
                "kind": "PRICE_UPDATE",
                "payload": body,
                "currency": body["currency"],
                "state": "PREPARED",
                "items": [
                    {
                        "productId": item["productId"],
                        "name": item["productId"],
                        "oldPriceMinor": self.products_by_id[item["productId"]].priceMinor,
                        "newPriceMinor": item["newPriceMinor"],
                        "currency": body["currency"],
                        "expectedVersion": 3,
                    }
                    for item in body["items"]
                ],
                "result": None,
                "createdAt": "2026-09-05T00:00:00Z",
                "resolvedAt": None,
            }
        )
        return self.receipt

    async def draft(self, draft_id, token, session_id):
        if session_id != self.receipt_session:
            raise CommerceError(404, "NOT_FOUND", "Unknown change in this session")
        assert draft_id == self.receipt.changeId
        return self.receipt

    def resolved(self, state):
        return self.receipt.model_copy(
            update={
                "state": state,
                "result": {"status": state},
                "resolvedAt": datetime(2026, 9, 5, 1, tzinfo=UTC),
            }
        )

    async def apply(self, draft_id, direct_token):
        self.applies.append((draft_id, direct_token))
        self.receipt = self.resolved("APPLIED")
        return self.receipt

    async def cancel(self, draft_id, token, session_id):
        self.receipt = self.resolved(self.cancel_result)
        return self.receipt

    async def summary(self, start, end, token, session_id):
        current = end.astimezone(ZoneInfo("Asia/Shanghai")).day == 5 and end.month == 9
        return SummaryView(
            start=start,
            end=end,
            basis="paid_gross_before_refunds",
            currencies=[
                {
                    "currency": "CNY",
                    "orderCount": 32,
                    "units": 96,
                    "amountMinor": 230400 if current else 195600,
                },
                {"currency": "USD", "orderCount": 14, "units": 28, "amountMinor": 28000},
            ],
        )


@pytest.fixture
def rig(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    record = store.create("operator")
    turn = store.begin_turn(record)
    session = MerchantSessionContext(
        session_id=record.session_id,
        operator="operator",
        merchant_id="citybuddy",
        now=datetime(2026, 9, 5, tzinfo=UTC),
    )
    auth, client, sql = Auth(), Client(), SQL()
    backend = CityBuddyMerchantBackend(auth, store, client, sql)
    with bind_context(RequestIdentity("operator", "direct-test-token"), record.session_id, turn):
        yield SimpleNamespace(
            store=store,
            record=record,
            session=session,
            auth=auth,
            client=client,
            sql=sql,
            backend=backend,
        )
    store.close()


def item(product="coffee", price=25.2):
    return PriceUpdateItem(listing_id=product, new_price=price)


def test_config_enables_full_retail_and_keeps_operator_only_approval():
    config = ShopMateConfig()
    names = {
        tool["name"] for tool in build_tools(config, ["performance-insights", "pricing-promotions"])
    }
    assert {
        "stage_price_update",
        "stage_promotion",
        "stage_campaign",
        "stage_listing_update",
        "stage_inventory_action",
        "get_order_issues",
        "get_campaign_performance",
        "discard_change",
        "run_analysis",
    } <= names
    assert "apply_change" not in names
    assert config.max_items_per_change == 25


def test_periods_use_shanghai_days_and_preserve_explicit_utc_instants(rig):
    recent = reporting_period(rig.session, "last_14_days")
    assert recent.start == datetime(2026, 8, 21, 16, tzinfo=UTC)
    assert recent.end == datetime(2026, 9, 4, 16, tzinfo=UTC)
    assert reporting_period(rig.session, "previous_14_days") == recent.previous()
    august = reporting_period(rig.session, "last_month")
    assert august.start == datetime(2026, 7, 31, 16, tzinfo=UTC)
    assert august.end == datetime(2026, 8, 31, 16, tzinfo=UTC)
    cutoff = reporting_period(rig.session, "2026-08-22T10:17:00Z/2026-08-23T10:17:00Z")
    assert cutoff.start.hour == cutoff.end.hour == 10
    with pytest.raises(ChangeNotApplicable):
        reporting_period(rig.session, "2026-09-05/2026-08-22")


async def test_staging_uses_persisted_canonical_intent_and_integer_prices(rig):
    first = await rig.backend.stage_price_update(
        rig.session, [item(), item("tea", 18.9)], "only a note"
    )
    second = await rig.backend.stage_price_update(rig.session, [item("tea", 18.9), item()])
    assert first.change_id == second.change_id
    assert len(rig.client.prepares) == 1
    body, key, token, session_id = rig.client.prepares[0]
    assert body["kind"] == "PRICE_UPDATE"
    assert body["payload"] == {
        "currency": "CNY",
        "items": [
            {"productId": "coffee", "newPriceMinor": 2520},
            {"productId": "tea", "newPriceMinor": 1890},
        ],
    }
    assert token == "obo:merchant:change:prepare" and session_id == rig.session.session_id
    assert rig.store.intent_rows(session_id)[0].key == key
    assert rig.store.owns_draft(session_id, first.change_id)
    assert "direct-test-token" not in first.model_dump_json()


async def test_uncertain_prepare_is_recovered_with_original_body_and_key(rig):
    rig.client.fail_prepare_once = CommerceError(503, "COMMERCE_UNAVAILABLE", "unavailable")
    with pytest.raises(CommerceError):
        await rig.backend.stage_price_update(rig.session, [item()])
    intent = rig.store.intent_rows(rig.session.session_id)[0]
    assert intent.draft_id is None and intent.rejection is None
    pending = await rig.backend.get_pending_changes(rig.session)
    assert len(pending) == 1
    assert rig.client.prepares[0] == rig.client.prepares[1]
    assert rig.store.intent_rows(rig.session.session_id)[0].draft_id == "draft-1"


async def test_definite_prepare_rejection_does_not_poison_later_reads(rig):
    rig.client.fail_prepare_once = CommerceError(409, "PRODUCT_NOT_EDITABLE", "not editable")
    with pytest.raises(ChangeNotApplicable):
        await rig.backend.stage_price_update(rig.session, [item()])
    assert rig.store.intent_rows(rig.session.session_id)[0].rejection == "PRODUCT_NOT_EDITABLE"
    assert await rig.backend.get_pending_changes(rig.session) == []
    with pytest.raises(ChangeNotApplicable, match="已被拒绝"):
        await rig.backend.stage_price_update(rig.session, [item()])
    assert len(rig.client.prepares) == 1


async def test_batch_rejects_canonical_duplicate_and_mixed_currencies(rig):
    for items in ([item(), item("COFFEE", 26)], [item(), item("cocoa", 11.5)]):
        with pytest.raises(ChangeNotApplicable):
            await rig.backend.stage_price_update(rig.session, items)
    assert rig.client.prepares == []
    assert rig.store.intent_rows(rig.session.session_id) == []


async def test_operator_apply_uses_direct_identity_and_session_owned_draft(rig):
    draft = await rig.backend.stage_price_update(rig.session, [item()])
    other = rig.store.create("operator")
    other_session = rig.session.model_copy(update={"session_id": other.session_id})
    with bind_context(RequestIdentity("operator", "direct-test-token"), other.session_id):
        with pytest.raises(CommerceError) as failure:
            await rig.backend.apply_by_operator(other_session, draft.change_id)
        assert failure.value.status_code == 404
    assert rig.client.applies == []
    result = await rig.backend.apply_by_operator(rig.session, draft.change_id)
    assert result["ok"] is True and result["receipt"]["state"] == "APPLIED"
    assert rig.client.applies == [(draft.change_id, "direct-test-token")]
    with pytest.raises(ChangeNotApplicable):
        await rig.backend.apply_change(rig.session, draft.change_id)


async def test_discard_does_not_claim_applied_draft_was_cancelled(rig):
    draft = await rig.backend.stage_price_update(rig.session, [item()])
    rig.client.cancel_result = "APPLIED"
    with pytest.raises(ChangeNotApplicable, match="APPLIED"):
        await rig.backend.discard_change(rig.session, draft.change_id)
    result = await rig.backend.discard_by_operator(rig.session, draft.change_id)
    assert result["ok"] is False and result["change"]["status"] == "applied"


async def test_sql_read_requires_merchant_permission_even_without_java_read(rig):
    rig.auth.denied = True
    for call in (
        lambda: rig.backend.execute_analysis_query(rig.session, "SELECT * FROM merchant_products"),
        lambda: rig.backend.query_metrics(rig.session, "sales"),
    ):
        with pytest.raises(HTTPException) as failure:
            await call()
        assert failure.value.status_code == 403
    assert rig.sql.calls == []
    assert all(scope == "merchant:read" for _, _, scope in rig.auth.scopes)


async def test_snapshot_does_not_sum_currencies_or_invent_unknown_metrics(rig):
    snapshot = await rig.backend.get_business_snapshot(rig.session)
    assert snapshot.sales == 2304 and snapshot.units == 96 and snapshot.orders == 32
    assert snapshot.currency == "CNY" and snapshot.sales_change_pct == 17.79
    assert snapshot.traffic is None and snapshot.conversion_rate is None
    assert snapshot.alerts.low_stock == 0 and snapshot.alerts.order_issues == 0
    series = await rig.backend.query_metrics(rig.session, "sales", segment="USD")
    assert series.unit == "USD" and "'USD'" in rig.sql.calls[-1]
    assert series.points[0].value == 115
    with pytest.raises(ChangeNotApplicable):
        await rig.backend.query_metrics(rig.session, "profit")


async def test_catalog_name_lookup_omits_filters_and_supported_filters_remain_effective(rig):
    tool = next(t for t in build_tools(ShopMateConfig(), []) if t["name"] == "search_listings")
    schema = tool["input_schema"]
    filters = schema["properties"]["filters"]
    assert set(filters["properties"]) == {
        "status",
        "category",
        "content_quality",
        "max_stock",
        "sort",
    }
    assert set(filters["properties"]["sort"]["enum"]) == {
        "relevance",
        "stock_asc",
        "price_desc",
        "price_asc",
        "sales_desc",
    }
    assert "filters" not in schema["required"]
    assert not filters.get("required")
    assert [row.listing_id for row in await rig.backend.search_listings(rig.session, "coffee")] == [
        "coffee"
    ]
    rig.client.products_by_id["tea"] = rig.client.products_by_id["tea"].model_copy(
        update={"stockQuantity": 3}
    )
    rows = await rig.backend.search_listings(
        rig.session, "", ListingFilters(status="active", max_stock=3, sort="price_asc")
    )
    assert [row.listing_id for row in rows] == ["tea"]
    assert (
        await rig.backend.search_listings(
            rig.session, "coffee", ListingFilters(content_quality="good")
        )
        == []
    )


class OverviewSQL(SQL):
    async def query(self, sql):
        self.calls.append(sql)
        if "AS observed_days" in sql:
            return AnalysisTable(
                columns=["visits", "observed_days"], rows=[[1000, 14]], row_count=1
            )
        current = ">= '2026-08-21" in sql
        amount = 230400 if current else 195600
        if "WITH traffic AS" in sql:
            value = 3.2
        elif "COUNT(*) AS value" in sql:
            value = 32
        elif "SUM(total_price_minor) / NULLIF" in sql:
            value = amount / 32
        elif "SUM(total_price_minor) AS value" in sql:
            value = amount
        else:
            raise AssertionError("Unexpected overview query: " + sql)
        return AnalysisTable(
            columns=["bucket", "value"],
            rows=[["2026-08-22" if current else "2026-08-08", value]],
            row_count=1,
        )


def overview_issue():
    return IssueView(
        issueId="issue-one",
        orderId="order-one",
        kind="buyer_message",
        summary="核对买家问题",
        listingId="coffee",
        buyerMessageExcerpt="请核对包装",
        openedAt="2026-09-08T00:00:00Z",
        fulfillment=None,
        refundRequestedOrderCount=None,
        windowStart=None,
        windowEnd=None,
        sourceKind="FIXTURE",
        sourceRef="issue-fixture",
    )


async def test_overview_uses_one_alert_read_and_distinct_real_metric_series(rig):
    rig.backend.sql = OverviewSQL()
    alerts = [
        InventoryView(
            listingId=key,
            title=key,
            kind=kind,
            variantOf=None,
            optionValues={},
            stock=stock,
            threshold=5,
            salesLast30d=sales,
            daysOfCover=None,
            storefrontVisible=True,
        )
        for key, kind, stock, sales in (
            ("coffee", "low_stock", 2, 10),
            ("tea", "slow_mover", 40, 0),
        )
    ]
    rig.client.inventory = AsyncMock(
        return_value=PageView[InventoryView](
            items=alerts,
            nextOffset=None,
            window=WindowView(
                start="2026-08-05T16:00:00Z", end="2026-09-04T16:00:00Z", timeZone="Asia/Shanghai"
            ),
        )
    )
    rig.client.issues = AsyncMock(return_value=[overview_issue()])
    order = OrderView(
        orderKind="STANDARD",
        orderId="new-unpaid",
        status="UNPAID",
        stateVersion=1,
        createdAt="2026-09-08T00:00:00Z",
        unpaidDeadline=None,
        product={
            "productId": "coffee",
            "name": "Historical name",
            "unitPriceMinor": 1250,
            "currency": "CNY",
            "quantity": 2,
            "totalPriceMinor": 2500,
            "productVersion": 7,
        },
        payment=None,
        refunds={"reservedAmountMinor": 0, "byState": []},
        fulfillment=None,
    )
    rig.client.recent_orders = AsyncMock(return_value=[order])
    result = await rig.backend.overview(rig.session)
    rig.client.inventory.assert_awaited_once()
    rig.client.issues.assert_awaited_once_with(
        "obo:merchant:read", rig.record.session_id, limit=100
    )
    rig.client.recent_orders.assert_awaited_once_with(
        "obo:merchant:read", rig.record.session_id, limit=6
    )
    assert result["snapshot"]["alerts"] == {
        "low_stock": 1,
        "slow_movers": 1,
        "order_issues": 1,
        "pending_changes": 0,
    }
    attention = result["needs_attention"]
    assert attention["low_stock"][0]["listing_id"] == "coffee"
    assert attention["slow_movers"][0]["listing_id"] == "tea"
    assert attention["order_issues"][0]["buyer_message_excerpt"] == "请核对包装"
    assert attention["order_issues_limit"] == 100 and not attention["order_issues_may_have_more"]
    assert result["trends"] == {
        name: [{"date": "2026-08-22", "value": value}]
        for name, value in (
            ("sales", 2304),
            ("orders", 32),
            ("conversion", 3.2),
            ("average_order_value", 72),
        )
    }
    assert result["trends_prior"]["sales"] == [{"date": "2026-08-08", "value": 1956}]
    assert result["prior_window"]["end"] == result["window"]["start"]
    assert datetime.fromisoformat(result["window"]["end"]) == datetime(2026, 9, 4, 16, tzinfo=UTC)
    assert result["recent_orders"][0]["createdAt"].startswith("2026-09-08")
    assert result["recent_orders"][0]["status"] == "UNPAID"
    assert result["recent_orders"][0]["payment"] is None
    assert result["recent_orders"][0]["product"]["totalPriceMinor"] == 2500


async def test_overview_keeps_capped_issue_counts_unknown_and_propagates_order_read_failure(rig):
    rig.client.issues = AsyncMock(return_value=[overview_issue()] * 100)
    result = await rig.backend.overview(rig.session)
    assert result["snapshot"]["alerts"]["order_issues"] is None
    assert result["needs_attention"]["order_issues_may_have_more"] is True
    assert result["trends"]["conversion"] == []
    assert "未知" in result["trend_notes"]["conversion"]
    rig.client.recent_orders = AsyncMock(
        side_effect=CommerceError(502, "INVALID_RESPONSE", "Invalid order response")
    )
    with pytest.raises(CommerceError, match="Invalid order response"):
        await rig.backend.overview(rig.session)
