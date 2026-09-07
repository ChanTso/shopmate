"""Match an operator's complete intent to the request exposed by a change receipt."""

import re
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any


def _object(value: Any, required: set[str], allowed: set[str]) -> dict[str, Any]:
    if type(value) is not dict or not required <= value.keys() or not value.keys() <= allowed:
        raise ValueError("Unexpected or missing operation fields")
    return value


def _text(value: Any, maximum: int) -> str:
    if type(value) is not str or not value.strip() or len(value) > maximum:
        raise ValueError("Operation text must be bounded and nonblank")
    return value


def _integer(value: Any, minimum: int, maximum: int) -> int:
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("Operation value must be an integer in range")
    return value


def _items(value: Any) -> list[Any]:
    if type(value) is not list or not 1 <= len(value) <= 25:
        raise ValueError("An operation requires 1..25 items")
    return value


def _date(value: Any, *, end: bool) -> datetime:
    encoded = _text(value, 40)
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", encoded):
            parsed = datetime.fromisoformat(encoded).replace(tzinfo=timezone(timedelta(hours=8)))
            if end:
                parsed += timedelta(days=1)
        elif re.fullmatch(
            r"\d{4}-\d{2}-\d{2}[Tt]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,9})?)?"
            r"(?:[Zz]|[+-]\d{2}:\d{2}(?::\d{2})?)",
            encoded,
        ):
            parsed = datetime.fromisoformat(encoded.upper())
            if abs(parsed.utcoffset()) > timedelta(hours=18):
                raise ValueError("Invalid timestamp offset")
        else:
            raise ValueError("Expected an ISO calendar date or timestamp with an offset")
        parsed = parsed.astimezone(UTC)
        if not datetime(1970, 1, 1, tzinfo=UTC) <= parsed <= datetime(9999, 12, 30, tzinfo=UTC):
            raise ValueError("Marketing date is outside the persistence range")
        return parsed
    except OverflowError as exc:
        raise ValueError("Marketing date is outside the persistence range") from exc


def _window(payload: dict[str, Any]) -> None:
    starts = _date(payload["starts"], end=False) if payload.get("starts") is not None else None
    ends = _date(payload["ends"], end=True) if payload.get("ends") is not None else None
    if starts is not None and ends is not None and starts >= ends:
        raise ValueError("Marketing window must have starts before ends")


def _listing(payload: Any) -> dict[str, Any]:
    value = _object(payload, {"listingId", "fields"}, {"listingId", "fields"})
    _text(value["listingId"], 64)
    fields = value["fields"]
    if type(fields) is not dict or not 1 <= len(fields) <= 25:
        raise ValueError("A listing update requires 1..25 fields")
    # Attribute names depend on the listing. Java checks eligibility and option dimensions.
    for name, content in fields.items():
        if type(name) is not str or not name.strip():
            raise ValueError("A listing field name must be nonblank text")
        _text(content, 200 if name == "title" else 2000)
    return value


def _inventory(payload: Any) -> list[tuple[str, str, int | None]]:
    value = _object(payload, {"items"}, {"items"})
    normalized = []
    targets = set()
    for item in _items(value["items"]):
        if type(item) is not dict or item.get("action") not in (
            "restock",
            "pause",
            "activate",
        ):
            raise ValueError("Invalid inventory action")
        action = item["action"]
        fields = (
            {"listingId", "action", "quantity"} if action == "restock" else {"listingId", "action"}
        )
        _object(item, fields, fields)
        listing_id = _text(item["listingId"], 64)
        quantity = _integer(item["quantity"], 1, 500) if action == "restock" else None
        # A restock and activation may coexist; pause and activate both change availability.
        target = (listing_id, "stock" if action == "restock" else "available")
        if target in targets:
            raise ValueError("Duplicate inventory target")
        targets.add(target)
        normalized.append((listing_id, action, quantity))
    return sorted(normalized)


def _promotion(payload: Any) -> dict[str, Any]:
    fields = {"name", "listingIds", "discountPct", "starts", "ends"}
    value = _object(payload, fields, fields)
    _text(value["name"], 80)
    listings = [_text(item, 64) for item in _items(value["listingIds"])]
    if len(set(listings)) != len(listings):
        raise ValueError("Duplicate promotion target")
    discount = value["discountPct"]
    if type(discount) not in (int, float):
        raise ValueError("Promotion discount must be numeric")
    number = Decimal(str(discount))
    if not number.is_finite() or not Decimal("0.01") <= number <= 50:
        raise ValueError("Promotion discount must be between 0.01 and 50 percent")
    points = number * 100
    if points != points.to_integral_value():
        raise ValueError("Promotion discount must have at most two decimal places")
    if value["starts"] is None or value["ends"] is None:
        raise ValueError("A promotion requires both window bounds")
    _window(value)
    return {**value, "listingIds": sorted(listings), "discountPct": number}


def _campaign(payload: Any) -> dict[str, Any]:
    text_fields = {
        "campaignId": 64,
        "objective": 200,
        "audience": 300,
        "copyText": 600,
    }
    value = _object(payload, {"name"}, set(text_fields) | {"name", "budgetMinor", "starts", "ends"})
    _text(value["name"], 80)
    for name, maximum in text_fields.items():
        if name in value and value[name] is not None:
            _text(value[name], maximum)
    if "budgetMinor" in value and value["budgetMinor"] is not None:
        _integer(value["budgetMinor"], 0, 1_000_000)
    _window(value)
    return value


def matches_retail_payload(kind: str, actual_payload: Any, wanted_payload: Any) -> bool:
    """Compare full HTTP request payloads; malformed shapes or values raise ValueError.

    Only inventory actions and promotion targets are unordered. Optional campaign fields
    retain presence and null, and dates retain their exact authorized spelling. Java remains
    responsible for current listing eligibility, family expansion and transactional state.
    """
    if kind == "LISTING_UPDATE":
        actual, wanted = _listing(actual_payload), _listing(wanted_payload)
    elif kind == "INVENTORY_ACTION":
        actual, wanted = _inventory(actual_payload), _inventory(wanted_payload)
    elif kind == "PROMOTION":
        actual, wanted = _promotion(actual_payload), _promotion(wanted_payload)
    elif kind == "CAMPAIGN":
        actual, wanted = _campaign(actual_payload), _campaign(wanted_payload)
    else:
        raise ValueError("Unsupported retail approval kind")
    return actual == wanted
