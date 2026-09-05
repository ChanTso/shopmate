"""The driver parser and approval selector must not guess at a truncated or ambiguous response."""

import importlib.util
import io
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "run_tasks", Path(__file__).resolve().parents[1] / "scripts/run_tasks.py"
)
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)


def test_sse_keeps_exact_raw_bytes_across_utf8_and_crlf_chunks():
    raw = (
        ': keepalive\r\n\r\nevent: text_delta\r\ndata: {"text": "人民币"}\r\n\r\n'
        'event: turn_complete\r\ndata: {\r\ndata: "stop_reason": "end_turn"}\r\n\r\n'
    ).encode()
    sink = io.BytesIO()
    events = list(driver.iter_sse((raw[i : i + 1] for i in range(len(raw))), sink))
    assert sink.getvalue() == raw
    assert events == [
        {"type": "text_delta", "data": {"text": "人民币"}},
        {"type": "turn_complete", "data": {"stop_reason": "end_turn"}},
    ]


def test_sse_error_is_preserved_as_error_not_completion():
    sink = io.BytesIO()
    events = list(driver.iter_sse([b'event: error\ndata: {"message":"unavailable"}\n\n'], sink))
    assert events == [{"type": "error", "data": {"message": "unavailable"}}]


@pytest.mark.parametrize(
    "raw",
    [
        b'event: turn_complete\ndata: {"stop_reason":"end_turn"}\n',
        b"event: turn_complete\ndata: not-json\n\n",
        b"event: turn_complete\ndata: []\n\n",
        b'event: text_delta\ndata: {"text":"\xff"}\n\n',
    ],
)
def test_sse_invalid_or_unfinished_frame_fails_and_retains_bytes(raw):
    sink = io.BytesIO()
    with pytest.raises(driver.TaskFailure):
        list(driver.iter_sse([raw], sink))
    assert sink.getvalue() == raw


def receipt(draft_id, products, *, currency="CNY", state="PREPARED"):
    return {
        "draftId": draft_id,
        "currency": currency,
        "state": state,
        "items": [
            {"productId": product, "newPriceMinor": price, "currency": currency}
            for product, price in products
        ],
    }


MATCH = {
    "currency": "CNY",
    "state": "PREPARED",
    "items": [
        {"productId": "coffee", "newPriceMinor": 2500},
        {"productId": "tea", "newPriceMinor": 1900},
    ],
}


def test_exact_draft_ignores_item_order_and_includes_all_targets():
    value = receipt("right", [("tea", 1900), ("coffee", 2500)])
    others = [
        receipt("cancelled", [("coffee", 2500), ("tea", 1900)], state="CANCELLED"),
        receipt("other_currency", [("coffee", 2500), ("tea", 1900)], currency="USD"),
        receipt("different", [("coffee", 2400), ("tea", 1900)]),
    ]
    assert driver.unique_draft(others + [value], MATCH) == "right"


@pytest.mark.parametrize(
    "receipts",
    [
        [],
        [receipt("partial", [("coffee", 2500)])],
        [receipt("extra", [("coffee", 2500), ("tea", 1900), ("mug", 3900)])],
        [receipt("first", [("coffee", 2500)]), receipt("second", [("tea", 1900)])],
        [
            receipt("first", [("coffee", 2500), ("tea", 1900)]),
            receipt("second", [("tea", 1900), ("coffee", 2500)]),
        ],
        [receipt("duplicate", [("coffee", 2500), ("coffee", 2500), ("tea", 1900)])],
        [receipt("invalid_price", [("coffee", 2500.0), ("tea", 1900)])],
        [receipt("invalid_boolean", [("coffee", True), ("tea", 1900)])],
    ],
)
def test_incomplete_split_ambiguous_or_malformed_drafts_cannot_authorize(receipts):
    with pytest.raises(driver.TaskFailure):
        driver.unique_draft(receipts, MATCH)


def test_receipt_currency_must_agree_with_each_item():
    value = receipt("mixed", [("coffee", 2500), ("tea", 1900)])
    value["items"][1]["currency"] = "USD"
    with pytest.raises(driver.TaskFailure, match="currency"):
        driver.unique_draft([value], MATCH)


def test_provider_failure_requires_explicit_observation_not_generic_host_error():
    assert not driver.provider_failure({"message": "The turn could not complete"})
    assert not driver.provider_failure(
        {
            "provider_usage": {
                "model_observations": [
                    {"completed": False, "usage_available": False},
                ]
            }
        }
    )
    assert driver.provider_failure(
        {
            "provider_usage": {
                "model_observations": [
                    {"error_category": "provider_http", "http_status": 503},
                ]
            }
        }
    )
    assert not driver.provider_failure(
        {
            "provider_usage": {
                "stop_reason": "task_deadline",
                "model_observations": [{"error_category": "provider_transport"}],
            }
        }
    )
