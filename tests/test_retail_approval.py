import copy
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "retail_approval",
    Path(__file__).resolve().parents[1] / "scripts/retail_approval.py",
)
approval = importlib.util.module_from_spec(spec)
spec.loader.exec_module(approval)
matches = approval.matches_retail_payload

LISTING = {"listingId": "AR-1606", "fields": {"material": "棉", "title": "双人床单"}}
INVENTORY = {
    "items": [
        {"listingId": "AR-1606", "action": "restock", "quantity": 10},
        {"listingId": "AR-1606", "action": "activate"},
        {"listingId": "AR-1607", "action": "pause"},
    ]
}
PROMOTION = {
    "name": "秋季优惠",
    "listingIds": ["AR-1606", "AR-1607"],
    "discountPct": 10,
    "starts": "2026-09-07",
    "ends": "2026-09-08",
}
CAMPAIGN = {
    "campaignId": "campaign-1",
    "name": "秋季计划",
    "objective": "提高老客复购",
    "audience": "老客",
    "budgetMinor": 10000,
    "copyText": "秋日新品",
    "starts": "2026-09-07T10:00:00+08:00",
    "ends": "2026-09-08T10:00:00+08:00",
}


def test_listing_matches_complete_fields_without_trimming_or_dropping_keys():
    assert matches("LISTING_UPDATE", LISTING, copy.deepcopy(LISTING))
    assert matches(
        "LISTING_UPDATE",
        LISTING,
        {**LISTING, "fields": dict(reversed(LISTING["fields"].items()))},
    )
    assert not matches("LISTING_UPDATE", LISTING, {**LISTING, "listingId": "AR-1607"})
    assert not matches("LISTING_UPDATE", LISTING, {**LISTING, "fields": {"material": "棉"}})
    assert not matches(
        "LISTING_UPDATE",
        LISTING,
        {**LISTING, "fields": {**LISTING["fields"], "material": "棉 "}},
    )


def test_inventory_matches_unordered_whole_batch_and_preserves_intended_action_and_increment():
    assert matches("INVENTORY_ACTION", INVENTORY, {"items": list(reversed(INVENTORY["items"]))})
    assert not matches("INVENTORY_ACTION", INVENTORY, {"items": INVENTORY["items"][:2]})
    different_quantity = copy.deepcopy(INVENTORY)
    different_quantity["items"][0]["quantity"] = 11
    assert not matches("INVENTORY_ACTION", INVENTORY, different_quantity)
    different_action = copy.deepcopy(INVENTORY)
    different_action["items"][1]["action"] = "pause"
    assert not matches("INVENTORY_ACTION", INVENTORY, different_action)


@pytest.mark.parametrize(
    "items",
    [
        [{"listingId": "a", "action": "restock", "quantity": 1}] * 2,
        [
            {"listingId": "a", "action": "pause"},
            {"listingId": "a", "action": "activate"},
        ],
        [{"listingId": "a", "action": "activate"}] * 2,
    ],
)
def test_inventory_rejects_duplicate_affected_targets(items):
    with pytest.raises(ValueError):
        matches("INVENTORY_ACTION", {"items": items}, INVENTORY)


def test_promotion_compares_all_fields_and_only_normalizes_targets_and_numeric_discount():
    wanted = {
        **PROMOTION,
        "listingIds": list(reversed(PROMOTION["listingIds"])),
        "discountPct": 10.0,
    }
    assert matches("PROMOTION", PROMOTION, wanted)
    for field, replacement in {
        "name": "另一个活动",
        "listingIds": ["AR-1606"],
        "discountPct": 11,
        "starts": "2026-09-07T00:00:00+08:00",
        "ends": "2026-09-09",
    }.items():
        assert not matches("PROMOTION", PROMOTION, {**PROMOTION, field: replacement})
    fractional = {**PROMOTION, "discountPct": 0.29}
    assert matches("PROMOTION", fractional, fractional)


def test_campaign_optional_field_presence_and_null_are_part_of_authorization():
    assert matches("CAMPAIGN", CAMPAIGN, dict(reversed(CAMPAIGN.items())))
    assert matches("CAMPAIGN", {"name": "新计划"}, {"name": "新计划"})
    for field in (
        "campaignId",
        "objective",
        "audience",
        "budgetMinor",
        "copyText",
        "starts",
        "ends",
    ):
        omitted = {key: value for key, value in CAMPAIGN.items() if key != field}
        cleared = {**CAMPAIGN, field: None}
        assert matches("CAMPAIGN", cleared, copy.deepcopy(cleared))
        assert not matches("CAMPAIGN", omitted, cleared)
        assert not matches("CAMPAIGN", CAMPAIGN, cleared)
    assert not matches(
        "CAMPAIGN",
        {"name": "计划", "budgetMinor": None},
        {"name": "计划", "budgetMinor": 0},
    )


@pytest.mark.parametrize(
    "kind,payload",
    [
        ("LISTING_UPDATE", {"request": LISTING, "operation": {}}),
        ("LISTING_UPDATE", {**LISTING, "extra": True}),
        ("LISTING_UPDATE", {**LISTING, "fields": {}}),
        ("LISTING_UPDATE", {**LISTING, "fields": {"material": None}}),
        ("LISTING_UPDATE", {**LISTING, "fields": {"material": True}}),
        ("LISTING_UPDATE", {**LISTING, "fields": {"title": "x" * 201}}),
        ("INVENTORY_ACTION", {"items": []}),
        (
            "INVENTORY_ACTION",
            {"items": [{"listingId": "a", "action": "pause", "quantity": None}]},
        ),
        ("INVENTORY_ACTION", {"items": [{"listingId": "a", "action": "restock"}]}),
        (
            "INVENTORY_ACTION",
            {"items": [{"listingId": "a", "action": "RESTOCK", "quantity": 1}]},
        ),
        ("PROMOTION", {**PROMOTION, "listingIds": ["a", "a"]}),
        ("PROMOTION", {**PROMOTION, "listingIds": "a"}),
        ("PROMOTION", {**PROMOTION, "starts": None}),
        ("PROMOTION", {**PROMOTION, "ends": "tomorrow"}),
        ("PROMOTION", {**PROMOTION, "ends": "2026-09-06"}),
        ("PROMOTION", {**PROMOTION, "starts": "2026-09-07T10:00:00"}),
        ("PROMOTION", {**PROMOTION, "starts": "2026-02-30"}),
        ("CAMPAIGN", {"name": None}),
        ("CAMPAIGN", {"name": "计划", "spendMinor": 100}),
        ("CAMPAIGN", {**CAMPAIGN, "objective": ["old customers"]}),
        ("CAMPAIGN", {**CAMPAIGN, "ends": "2026-09-06T10:00:00+08:00"}),
    ],
)
def test_malformed_payload_is_rejected_on_either_side(kind, payload):
    valid = {
        "LISTING_UPDATE": LISTING,
        "INVENTORY_ACTION": INVENTORY,
        "PROMOTION": PROMOTION,
        "CAMPAIGN": CAMPAIGN,
    }[kind]
    with pytest.raises(ValueError):
        matches(kind, payload, valid)
    with pytest.raises(ValueError):
        matches(kind, valid, payload)


@pytest.mark.parametrize("value", [True, False, 1.0, "1", None, 0, 501])
def test_inventory_quantity_is_integer_increment_not_coerced(value):
    payload = {"items": [{"listingId": "a", "action": "restock", "quantity": value}]}
    with pytest.raises(ValueError):
        matches("INVENTORY_ACTION", payload, payload)


@pytest.mark.parametrize("value", [True, False, 100.0, "100", -1, 1_000_001])
def test_campaign_budget_is_integer_minor_units_not_coerced(value):
    payload = {"name": "计划", "budgetMinor": value}
    with pytest.raises(ValueError):
        matches("CAMPAIGN", payload, payload)


@pytest.mark.parametrize(
    "value", [True, False, "10", None, float("nan"), float("inf"), 0, 50.01, 1.001]
)
def test_discount_accepts_numeric_percent_only_with_supported_precision(value):
    payload = {**PROMOTION, "discountPct": value}
    with pytest.raises(ValueError):
        matches("PROMOTION", payload, payload)


def test_calendar_end_date_is_inclusive_but_timestamp_end_is_exclusive():
    single_day = {**PROMOTION, "ends": PROMOTION["starts"]}
    assert matches("PROMOTION", single_day, single_day)
    zero_window = {
        **PROMOTION,
        "starts": "2026-09-07T00:00:00Z",
        "ends": "2026-09-07T00:00:00Z",
    }
    with pytest.raises(ValueError):
        matches("PROMOTION", zero_window, zero_window)


def test_match_does_not_mutate_payloads_or_handle_price_receipts():
    before = copy.deepcopy(PROMOTION)
    assert matches("PROMOTION", PROMOTION, PROMOTION)
    assert PROMOTION == before
    with pytest.raises(ValueError):
        matches("PRICE_UPDATE", {}, {})
