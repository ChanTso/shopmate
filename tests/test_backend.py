from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from merchant_agent.changes import ChangeNotApplicable
from merchant_agent.tools.registry import build_tools
from merchant_agent.types import AnalysisTable, MerchantSessionContext, PriceUpdateItem

from shopmate.auth import RequestIdentity, bind_context
from shopmate.backend import CityBuddyMerchantBackend, ShopMateConfig, reporting_period
from shopmate.commerce_client import CommerceError, DraftView, ProductView, SummaryView
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

    async def prepare(self, body, key, token, session_id):
        self.prepares.append((body, key, token, session_id))
        if self.fail_prepare_once:
            error, self.fail_prepare_once = self.fail_prepare_once, None
            raise error
        self.receipt = DraftView.model_validate(
            {
                "draftId": "draft-1",
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
        assert draft_id == self.receipt.draftId
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
        current = end.day == 5 and end.month == 9
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


def test_config_removes_unimplemented_and_operator_only_tools():
    config = ShopMateConfig()
    names = {
        tool["name"] for tool in build_tools(config, ["performance-insights", "pricing-promotions"])
    }
    assert {"stage_price_update", "discard_change", "run_analysis"} <= names
    assert (
        not {
            "apply_change",
            "stage_promotion",
            "stage_inventory_action",
            "get_order_issues",
            "stage_listing_update",
            "get_campaign_performance",
        }
        & names
    )


def test_periods_preserve_utc_half_open_calendar_and_previous_windows(rig):
    recent = reporting_period(rig.session, "last_14_days")
    assert recent.start == datetime(2026, 8, 22, tzinfo=UTC)
    assert recent.end == datetime(2026, 9, 5, tzinfo=UTC)
    assert reporting_period(rig.session, "previous_14_days") == recent.previous()
    august = reporting_period(rig.session, "last_month")
    assert august.start == datetime(2026, 8, 1, tzinfo=UTC)
    assert august.end == datetime(2026, 9, 1, tzinfo=UTC)
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
    assert body == {
        "currency": "CNY",
        "items": [
            {"productId": "coffee", "newPriceMinor": 2520},
            {"productId": "tea", "newPriceMinor": 1890},
        ],
    }
    assert token == "obo:merchant:price:prepare" and session_id == rig.session.session_id
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
    assert snapshot.alerts.low_stock is None and snapshot.alerts.order_issues is None
    series = await rig.backend.query_metrics(rig.session, "sales", segment="USD")
    assert series.unit == "USD" and "'USD'" in rig.sql.calls[-1]
    assert series.points[0].value == 115
    with pytest.raises(ChangeNotApplicable):
        await rig.backend.query_metrics(rig.session, "profit")
