"""The driver parser and approval selector must not guess at a truncated or ambiguous response."""

import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
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


@pytest.mark.parametrize("recovery_status", [200, 503])
def test_completed_turn_recovers_unknown_prepare_before_archival_or_retains_fixture(
    tmp_path, monkeypatch, recovery_status
):
    runtime = tmp_path / ".run"
    runtime.mkdir()
    (runtime / "operator_password").write_text("private-login-password")
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    monkeypatch.setattr(driver, "verify_sources", lambda *_: None)
    monkeypatch.setattr(
        driver.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=0)
    )
    calls = []
    recovered = False

    def handle(request):
        nonlocal recovered
        path = request.url.path.rsplit("/", 1)[-1]
        calls.append((request.method, path))
        if path == "login":
            return httpx.Response(
                200,
                json={
                    "subject": driver.SUBJECT,
                    "accessToken": "private-user-token",
                },
            )
        if path == "sessions":
            return httpx.Response(200, json={"sessions": [{"status": "completed"}]})
        if path == "session" and request.method == "POST":
            return httpx.Response(200, json={"session_id": "new-session"})
        if path == "listings":
            return httpx.Response(200, json={"listings": []})
        if path == "chat":
            # A tool failed after sending prepare; the model nevertheless finished its turn.
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream"},
                content=(
                    'event: tool_result\ndata: {"is_error":true,"reason":"COMMERCE_UNAVAILABLE"}\n\n'
                    'event: turn_complete\ndata: {"stop_reason":"end_turn"}\n\n'
                ),
            )
        if path == "overview":
            if recovery_status == 503:
                return httpx.Response(503, json={"category": "COMMERCE_UNAVAILABLE"})
            recovered = True
            return httpx.Response(200, json={"recent_changes": [{"change_id": "recovered-draft"}]})
        if path == "session":
            assert recovered, "Archival must happen after pending prepare recovery"
            return httpx.Response(200, json={"items": [{"changeIds": ["recovered-draft"]}]})
        raise AssertionError(f"Unexpected request {request.method} {path}")

    client_type = httpx.Client
    monkeypatch.setattr(
        driver.httpx,
        "Client",
        lambda **kwargs: client_type(**kwargs, transport=httpx.MockTransport(handle)),
    )
    monkeypatch.setattr(
        driver, "snapshot", lambda _evidence, stage, _paths, _session: calls.append(("SQL", stage))
    )
    evidence = driver.Evidence(
        tmp_path / "results",
        {
            "citybuddy_commit": "a" * 40,
            "shopmate_commit": "b" * 40,
        },
    )
    result = driver.run_task(
        {
            "steps": [{"kind": "chat", "message": "Prepare a draft"}],
            "evaluator": {"reference_sql": []},
        },
        {"common_context": "UTC"},
        evidence,
        SimpleNamespace(task_timeout_s=1, citybuddy_dir=tmp_path),
        "http://host/api/merchant",
    )
    assert calls.index(("GET", "overview")) < calls.index(("SQL", "after"))
    if recovery_status == 200:
        assert result["execution_status"] == "executed"
        assert calls.index(("GET", "overview")) < calls.index(("GET", "session"))
        saved = json.loads((evidence.path / "saved-session.json").read_text())
        assert "recovered-draft" in saved["data"]["response_body"]
    else:
        assert result["execution_status"] == "failed"
        assert result["fixture_retained"] is True
        assert ("GET", "session") not in calls
    assert calls.count(("GET", "overview")) == 1
