"""HTTP payloads, durable recovery, nullable facts and local-calendar reporting."""

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from merchant_agent.changes import ChangeNotApplicable
from merchant_agent.types import (
    AnalysisTable,
    Campaign,
    CampaignDraft,
    InventoryActionItem,
    MerchantSessionContext,
    MerchantSessionState,
    PriceUpdateItem,
    PromotionDraft,
)

from shopmate import presentation
from shopmate.analysis_sql import validate_sql
from shopmate.auth import RequestIdentity, bind_context
from shopmate.backend import CityBuddyMerchantBackend, ShopMateConfig, reporting_period
from shopmate.commerce_client import (
    CampaignView,
    ChangeView,
    CommerceClient,
    CommerceError,
)
from shopmate.sessions import SessionStore

WINDOW = {
    "start": "2026-08-05T16:00:00Z",
    "end": "2026-09-04T16:00:00Z",
    "timeZone": "Asia/Shanghai",
}


def listing_row(identifier="sku", *, kind="plain", variants=None):
    return {
        "id": identifier,
        "kind": kind,
        "variantOf": "family" if kind == "variant" else None,
        "title": identifier,
        "shortDescription": "Actual description",
        "priceMinor": 1000,
        "currency": "USD" if identifier == "usd" else "CNY",
        "stockQuantity": 9,
        "available": True,
        "publicationState": "PUBLISHED",
        "status": "active",
        "publicationVersion": None if kind == "family" else 4,
        "metadataVersion": 2,
        "familyMetadataVersion": 2 if kind != "plain" else None,
        "content": {
            "category": "kids-room",
            "brand": "ShopMate",
            "attributes": {"material": "wood"},
            "specs": {"pieces": "54"},
            "imageUrl": "/sku.webp",
        },
        "options": [{"name": "size", "values": ["M", "L"]}] if kind == "family" else [],
        "optionValues": {"size": "M"} if kind == "variant" else {},
        "contentQuality": None,
        "operations": None,
        "salesLast30d": {
            "orderCount": 3,
            "units": 5,
            "refundRequestedOrderCount": 1,
            "refundRequestedOrderPct": 33.33,
        },
        "marginPct": None,
        "priceEditable": kind != "family",
        "window": WINDOW,
        "variants": variants or [],
    }


def campaign_row():
    return {
        "campaignId": "c1",
        "name": "Campaign",
        "objective": "visits",
        "audience": None,
        "copyText": None,
        "channel": "email",
        "currency": "CNY",
        "budgetMinor": None,
        "startsAt": None,
        "endsAt": None,
        "state": "active",
        "version": 1,
        "createdAt": "2026-08-01T00:00:00Z",
        "updatedAt": "2026-08-01T00:00:00Z",
        "sourceChangeId": None,
        "spendMinor": 10000,
        "revenueMinor": None,
        "observationSourceKind": "FIXTURE",
        "observationSourceRef": "retail/C-203",
        "observedAt": "2026-09-04T16:00:00Z",
        "observationStart": "2026-08-04T16:00:00Z",
        "observationEnd": "2026-09-04T16:00:00Z",
        "fixtureVersion": "retail-v1",
    }


class Wire:
    def __init__(self):
        self.requests, self.receipts, self.keys, self.owners = ([], {}, {}, {})
        self.lose_prepare = False
        self.early_promotion = False
        self.price_minor = 1000

    def handle(self, request):
        self.requests.append(request)
        path, method = (request.url.path, request.method)
        session = request.headers.get("x-merchant-session-id")
        if path == "/internal/merchant/listings":
            offset = int(request.url.params.get("offset", 0))
            return httpx.Response(
                200,
                json={
                    "items": [listing_row("sku" + str(offset))],
                    "nextOffset": 50 if offset == 0 else None,
                    "window": WINDOW,
                },
            )
        if path.startswith("/internal/merchant/listings/"):
            identifier = path.rsplit("/", 1)[1].lower()
            row = listing_row(identifier)
            row["priceMinor"] = self.price_minor
            if identifier == "family":
                row = listing_row(
                    identifier, kind="family", variants=[listing_row("variant", kind="variant")]
                )
            return httpx.Response(200, json=row)
        if path == "/internal/merchant/inventory-alerts":
            return httpx.Response(200, json={"items": [], "nextOffset": None, "window": WINDOW})
        if path == "/internal/merchant/order-issues":
            return httpx.Response(200, json=[])
        if path == "/internal/merchant/campaigns":
            return httpx.Response(200, json=[campaign_row()])
        if path == "/internal/merchant/campaigns/c1":
            return httpx.Response(200, json=campaign_row())
        if path == "/internal/merchant/changes" and method == "POST":
            key, body = (request.headers["idempotency-key"], json.loads(request.content))
            if key not in self.keys:
                identifier = "change-" + str(len(self.keys))
                self.keys[key] = identifier
                payload, kind = (body["payload"], body["kind"])
                items = (
                    [
                        {
                            "productId": item["productId"],
                            "name": item["productId"],
                            "oldPriceMinor": self.price_minor,
                            "newPriceMinor": item["newPriceMinor"],
                            "currency": payload["currency"],
                            "expectedVersion": 4,
                        }
                        for item in payload["items"]
                    ]
                    if kind == "PRICE_UPDATE"
                    else [{"target": "sku", "field": "stock", "before": 9, "after": 14}]
                )
                self.receipts[identifier] = {
                    "changeId": identifier,
                    "kind": kind,
                    "state": "PREPARED",
                    "currency": payload.get("currency"),
                    "items": items,
                    "payload": payload,
                    "result": None,
                    "createdAt": "2026-09-07T01:00:00Z",
                    "resolvedAt": None,
                }
                self.owners[identifier] = session
            if self.lose_prepare:
                self.lose_prepare = False
                raise httpx.ReadError("response lost after commit", request=request)
            return httpx.Response(200, json=self.receipts[self.keys[key]])
        if path == "/internal/merchant/changes":
            rows = [
                row
                for identifier, row in self.receipts.items()
                if self.owners[identifier] == session
                and (
                    not request.url.params.get("state")
                    or row["state"] == request.url.params["state"]
                )
            ]
            offset, limit = (
                int(request.url.params.get("offset", 0)),
                int(request.url.params.get("limit", 100)),
            )
            return httpx.Response(200, json=rows[offset : offset + limit])
        if "/changes/" in path:
            identifier = path.split("/changes/", 1)[1].split("/")[0]
            if identifier not in self.receipts:
                return httpx.Response(404, json={"category": "NOT_FOUND"})
            row = self.receipts[identifier]
            if path.endswith("/apply"):
                assert request.headers["authorization"] == "Bearer direct"
                assert session is None
                if self.early_promotion:
                    return httpx.Response(
                        409, json={"category": "promotion_not_started", "message": "not yet"}
                    )
                row.update(
                    state="APPLIED", result={"status": "APPLIED"}, resolvedAt="2026-09-07T01:02:00Z"
                )
            elif self.owners[identifier] != session:
                return httpx.Response(404, json={"category": "NOT_FOUND"})
            elif path.endswith("/cancel") and row["state"] == "PREPARED":
                row.update(
                    state="CANCELLED",
                    result={"status": "CANCELLED"},
                    resolvedAt="2026-09-07T01:02:00Z",
                )
            return httpx.Response(200, json=row)
        raise AssertionError((method, path))


@pytest.fixture
async def retail():
    wire, store = (Wire(), SessionStore(":memory:"))
    record = store.create("operator")
    turn = store.begin_turn(record)
    session = MerchantSessionContext(
        session_id=record.session_id,
        merchant_id="citybuddy",
        operator="operator",
        now=datetime(2026, 9, 7, 2, tzinfo=UTC),
    )
    auth = SimpleNamespace(exchange=AsyncMock(return_value="obo"))
    sql = SimpleNamespace(
        query=AsyncMock(
            return_value=AnalysisTable(columns=["bucket", "value"], rows=[["2026-09-03", 2000]])
        )
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(wire.handle)) as http:
        client = CommerceClient("http://commerce", http)
        backend = CityBuddyMerchantBackend(
            auth, store, client, sql, report_as_of=datetime(2026, 9, 4, 16, tzinfo=UTC)
        )
        with bind_context(RequestIdentity("operator", "direct"), record.session_id, turn):
            yield SimpleNamespace(
                wire=wire,
                store=store,
                record=record,
                session=session,
                auth=auth,
                sql=sql,
                backend=backend,
                client=client,
                turn=turn,
            )
    store.close()


async def test_all_five_prepares_use_generic_wire_and_stock_is_an_increment(retail):
    r = retail
    calls = [
        r.backend.stage_price_update(r.session, [PriceUpdateItem(listing_id="sku", new_price=11)]),
        r.backend.stage_listing_update(
            r.session, "sku", {"long_description": "Actual new description"}
        ),
        r.backend.stage_inventory_action(
            r.session, [InventoryActionItem(listing_id="sku", action="restock", quantity=5)]
        ),
        r.backend.stage_promotion(
            r.session,
            PromotionDraft(
                name="Sale",
                listing_ids=["sku"],
                discount_pct=10,
                starts="2026-09-07",
                ends="2026-09-09",
            ),
        ),
        r.backend.stage_campaign(
            r.session, CampaignDraft(name="Email", budget=100, copy_text="News")
        ),
    ]
    for call in calls:
        assert (await call).status == "staged"
    bodies = [
        json.loads(request.content)
        for request in r.wire.requests
        if request.method == "POST" and request.url.path == "/internal/merchant/changes"
    ]
    assert [body["kind"] for body in bodies] == [
        "PRICE_UPDATE",
        "LISTING_UPDATE",
        "INVENTORY_ACTION",
        "PROMOTION",
        "CAMPAIGN",
    ]
    assert bodies[2]["payload"]["items"] == [
        {"listingId": "sku", "action": "restock", "quantity": 5}
    ]
    assert bodies[4]["payload"] == {"name": "Email", "budgetMinor": 10000, "copyText": "News"}
    assert all(
        call.args[-1] in {"merchant:read", "merchant:change:prepare"}
        for call in r.auth.exchange.call_args_list
    )


async def test_twenty_five_prices_and_canonical_duplicates(retail):
    r = retail
    result = await r.backend.stage_price_update(
        r.session, [PriceUpdateItem(listing_id=f"sku{i}", new_price=11) for i in range(25)]
    )
    assert len(result.items) == 25
    for items in (
        [PriceUpdateItem(listing_id="sku", new_price=11)] * 26,
        [
            PriceUpdateItem(listing_id="sku", new_price=11),
            PriceUpdateItem(listing_id="SKU", new_price=12),
        ],
        [
            PriceUpdateItem(listing_id="sku", new_price=11),
            PriceUpdateItem(listing_id="usd", new_price=11),
        ],
    ):
        with pytest.raises(ChangeNotApplicable):
            await r.backend.stage_price_update(r.session, items)
    assert len(r.wire.keys) == 1


async def test_committed_prepare_without_local_ref_is_replayed_with_original_key(retail):
    r = retail
    r.wire.lose_prepare = True
    with pytest.raises(CommerceError):
        await r.backend.stage_inventory_action(
            r.session, [InventoryActionItem(listing_id="sku", action="pause")]
        )
    intent = r.store.intent_rows(r.session.session_id)[0]
    assert intent.draft_id is None
    changes = await r.backend.get_pending_changes(r.session)
    assert len(changes) == len(r.wire.keys) == 1
    requests = [q for q in r.wire.requests if q.method == "POST"]
    assert (
        requests[0].headers["idempotency-key"]
        == requests[1].headers["idempotency-key"]
        == intent.key
    )
    assert requests[0].content == requests[1].content
    assert "quantity" not in json.loads(requests[0].content)["payload"]["items"][0]


async def test_legacy_price_intent_is_recovered_without_rewriting_its_key_or_body(retail):
    r = retail
    body = {"currency": "CNY", "items": [{"productId": "sku", "newPriceMinor": 1100}]}
    intent = r.store.prepare_intent(r.session.session_id, r.turn, body)
    r.wire.lose_prepare = True
    with pytest.raises(CommerceError):
        await r.client.prepare(body, intent.key, "obo", r.session.session_id)
    rows = await r.backend.get_pending_changes(r.session)
    assert len(rows) == len(r.wire.keys) == 1
    assert r.store.intent_rows(r.session.session_id)[0].body == body
    assert r.store.intent_rows(r.session.session_id)[0].key == intent.key


async def test_operator_scope_and_not_started_keep_prepared_and_cancel_reads_terminal(retail):
    r = retail
    proposal = await r.backend.stage_promotion(
        r.session,
        PromotionDraft(
            name="Sale",
            listing_ids=["sku"],
            discount_pct=10,
            starts="2026-09-08",
            ends="2026-09-10",
        ),
    )
    r.wire.early_promotion = True
    with pytest.raises(CommerceError) as failure:
        await r.backend.apply_by_operator(r.session, proposal.change_id)
    assert failure.value.category == "promotion_not_started"
    assert (await r.backend.get_change(r.session, proposal.change_id)).status == "staged"
    r.wire.early_promotion = False
    assert (await r.backend.apply_by_operator(r.session, proposal.change_id))["ok"]
    assert not (await r.backend.discard_by_operator(r.session, proposal.change_id))["ok"]
    with pytest.raises(ChangeNotApplicable):
        await r.backend.discard_change(r.session, proposal.change_id)
    with bind_context(RequestIdentity("operator", "direct"), "other-session"):
        with pytest.raises(CommerceError) as failure:
            await r.backend.apply_by_operator(
                r.session.model_copy(update={"session_id": "other-session"}), proposal.change_id
            )
        assert failure.value.status_code == 404


async def test_catalog_page_and_family_details_use_report_cutoff_not_operation_clock(retail):
    r = retail
    first = await r.backend.listings_page(r.session, limit=50)
    second = await r.backend.listings_page(r.session, limit=50, offset=first["nextOffset"])
    assert first["items"][0]["listing_id"] == "sku0"
    assert second["items"][0]["listing_id"] == "sku50" and second["nextOffset"] is None
    family = await r.backend.get_listing(r.session, "family")
    price = await r.backend.get_pricing_context(r.session, "family")
    assert family.variants[0].listing_id == price.variants[0].listing_id == "variant"
    assert family.content["specs"] == {"pieces": "54"}
    assert family.refund_requested_order_pct == 33.33 and family.return_rate_pct is None
    assert price.unit_cost is None and price.min_price is None and (price.max_price_delta_pct == 20)
    assert all(q.url.params["asOf"] == "2026-09-04T16:00:00+00:00" for q in r.wire.requests)
    context = await r.backend.get_merchant_context(r.session)
    assert context["operation_time"].startswith("2026-09-07T10:")
    assert context["report_as_of"].startswith("2026-09-04T16:")


def test_shanghai_calendar_and_explicit_offsets_are_different_but_exact():
    s = MerchantSessionContext(
        session_id="s", merchant_id="m", operator="o", now=datetime(2026, 9, 5, 0, tzinfo=UTC)
    )
    recent = reporting_period(s, "last_14_days")
    assert recent.start == datetime(2026, 8, 21, 16, tzinfo=UTC)
    assert recent.end == datetime(2026, 9, 4, 16, tzinfo=UTC)
    explicit = reporting_period(s, "2026-08-22T00:00:00Z/2026-09-05T00:00:00Z")
    assert explicit.start == datetime(2026, 8, 22, 0, tzinfo=UTC)
    assert explicit.end == datetime(2026, 9, 5, 0, tzinfo=UTC)


async def test_aov_kids_room_and_conversion_queries_are_valid_and_use_matching_denominators(retail):
    r = retail
    result = await r.backend.query_metrics(
        r.session, "aov", segment="kids-room", granularity="month"
    )
    query = r.sql.query.call_args.args[0]
    assert validate_sql(query)
    assert "NULLIF(COUNT(*), 0)" in query and "category = 'kids-room'" in query
    assert "INTERVAL 8 HOUR" in query and "2026-09-04 16:00:00" in query
    assert result.points[0].value == 20
    r.sql.query.side_effect = [
        AnalysisTable(rows=[[1400, 14]]),
        AnalysisTable(rows=[["2026-09-01", 2.5]]),
    ]
    converted = await r.backend.query_metrics(r.session, "conversion", granularity="month")
    query = r.sql.query.call_args.args[0]
    assert validate_sql(query)
    assert "NULLIF(t.visits, 0)" in query and "COUNT(*) AS orders" in query
    assert converted.points[0].value == 2.5 and converted.unit == "%"
    unsupported = await r.backend.query_metrics(r.session, "traffic", segment="kids-room")
    assert unsupported.points == [] and "分母" in unsupported.note


async def test_missing_traffic_does_not_become_zero_or_conversion(retail):
    r = retail
    r.sql.query.return_value = AnalysisTable(rows=[[100, 13]])
    result = await r.backend.query_metrics(r.session, "traffic")
    assert result.points == [] and "不完整" in result.note
    assert r.sql.query.call_count == 1


def test_nullable_campaign_budget_survives_real_session_state_roundtrip():
    state = MerchantSessionState()
    row = presentation.campaign(CampaignView.model_validate(campaign_row()))
    assert row.budget is None and row.revenue is None and (row.roas is None)
    state.seen_campaigns[row.campaign_id] = row
    restored = MerchantSessionState.model_validate_json(state.model_dump_json())
    assert isinstance(restored.seen_campaigns["c1"], Campaign)
    assert restored.seen_campaigns["c1"].budget is None
    assert (
        restored.seen_campaigns["c1"].spend == 100 and restored.seen_campaigns["c1"].revenue is None
    )


@pytest.mark.parametrize(
    "kind,field,before,after,expected",
    [
        ("INVENTORY_ACTION", "stock", 9, 14, 14),
        ("INVENTORY_ACTION", "available", False, True, True),
        ("LISTING_UPDATE", "long_description", "Old", "New", "New"),
        ("PROMOTION", "promotion_price", 1000, 900, 9.0),
        ("CAMPAIGN", "budget", None, 10000, 100.0),
    ],
)
def test_generic_diff_only_converts_money(kind, field, before, after, expected):
    receipt = ChangeView(
        changeId="c",
        kind=kind,
        state="PREPARED",
        currency="CNY",
        items=[{"target": "sku", "field": field, "before": before, "after": after}],
        payload={},
        result=None,
        createdAt="2026-09-07T00:00:00Z",
        resolvedAt=None,
    )
    card = presentation.change(receipt, "operator")
    assert card.items[0].after == expected and type(card.items[0].after) is type(expected)
    assert card.receipt["items"][0]["after"] == after
    assert card.kind.value == kind.lower() and card.status == "staged"


def test_full_retail_configuration_retains_host_approval():
    config = ShopMateConfig()
    assert config.enable_listing_edits and config.enable_inventory and config.enable_campaigns
    assert config.max_items_per_change == 25 and config.max_price_delta_pct == 20
    assert "apply_change" in config.absent_tools()
    assert "stage_promotion" not in config.absent_tools()


async def test_core_price_movement_rule_runs_before_any_durable_prepare(retail):
    with pytest.raises(ChangeNotApplicable, match="20%"):
        await retail.backend.stage_price_update(
            retail.session, [PriceUpdateItem(listing_id="sku", new_price=12.01)]
        )
    assert retail.store.intent_rows(retail.session.session_id) == []
    assert retail.wire.keys == {}


async def test_exact_twenty_percent_boundary_uses_minor_units(retail):
    retail.wire.price_minor = 2400
    change = await retail.backend.stage_price_update(
        retail.session, [PriceUpdateItem(listing_id="sku", new_price=28.8)]
    )
    assert change.items[0].before == 24 and change.items[0].after == 28.8


async def test_unknown_history_is_not_reported_as_zero_sales(retail):
    result = await retail.backend.query_metrics(retail.session, "sales", "last_180_days")
    assert result.points == [] and "覆盖" in result.note
    retail.sql.query.assert_not_called()


def test_campaign_tool_uses_local_instants_and_keeps_exclusive_end():
    row = CampaignView.model_validate(campaign_row())
    card = presentation.campaign(row)
    assert card.observation_start == "2026-08-05T00:00:00+08:00"
    assert card.observation_end == "2026-09-05T00:00:00+08:00"
    assert card.observation_period == (
        "上海时间：2026-08-05T00:00:00+08:00（含）至 2026-09-05T00:00:00+08:00（不含）"
    )
    absent = row.model_copy(update={"observationStart": None, "observationEnd": None})
    assert presentation.campaign(absent).observation_period is None
