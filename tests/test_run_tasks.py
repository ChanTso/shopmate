"""The driver parser and approval selector must not guess at a truncated or ambiguous response."""

import importlib.util
import io
import json
import socket
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

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
    for account in driver.ACTORS.values():
        (runtime / account["password"]).write_text("private-login-password")
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    monkeypatch.setattr(driver, "verify_sources", lambda *_: None)
    monkeypatch.setattr(
        driver.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(returncode=0)
    )
    calls = []
    recovered = False
    session_created = False

    def handle(request):
        nonlocal recovered, session_created
        path = request.url.path.rsplit("/", 1)[-1]
        calls.append((request.method, path))
        if path == "login":
            return httpx.Response(
                200,
                json={
                    "subject": json.loads(request.content)["loginIdentifier"],
                    "accessToken": "private-user-token",
                },
            )
        if path == "sessions":
            items = (
                [{"session_id": "new-session", "status": "completed"}]
                if session_created and "/merchant/" in request.url.path
                else []
            )
            return httpx.Response(200, json={"sessions": items})
        if path == "session" and request.method == "POST":
            session_created = True
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
        driver,
        "snapshot",
        lambda _evidence, stage, _paths, _session, _bindings=None: calls.append(("SQL", stage)),
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
        saved = json.loads((evidence.path / "merchant/saved-session.json").read_text())
        assert "recovered-draft" in saved["data"]["response_body"]
    else:
        assert result["execution_status"] == "failed"
        assert result["fixture_retained"] is True
        assert ("GET", "session") not in calls
    assert calls.count(("GET", "overview")) == 1


def generic_receipt(identifier, products, *, kind="PRICE_UPDATE"):
    value = receipt(identifier, products)
    value["changeId"] = value.pop("draftId")
    value["kind"] = kind
    return value


def test_generic_price_receipt_keeps_exact_whole_batch_authorization():
    price = generic_receipt("price", [("tea", 1900), ("coffee", 2500)])
    inventory = generic_receipt(
        "inventory", [("tea", 1900), ("coffee", 2500)], kind="INVENTORY_ACTION"
    )
    assert driver.unique_draft([inventory, price], MATCH) == "price"
    with pytest.raises(driver.TaskFailure, match="No unique exact"):
        driver.unique_draft([inventory], MATCH)
    with pytest.raises(driver.TaskFailure, match="only authorizes"):
        driver.unique_draft([inventory], MATCH | {"kind": "INVENTORY_ACTION"})


@pytest.mark.parametrize("mutation", [{"kind": "UNKNOWN"}, {"kind": None}, {"draftId": "other"}])
def test_generic_unknown_kind_or_conflicting_id_cannot_authorize(mutation):
    value = generic_receipt("price", [("tea", 1900), ("coffee", 2500)])
    value.update(mutation)
    with pytest.raises(driver.TaskFailure):
        driver.unique_draft([value], MATCH)


def test_retail_suite_has_isolated_reference_sql_and_no_assumed_product_versions():
    suite = driver.load_suite("retail/development")
    assert suite["protocol_id"] == "shopmate-retail-development-v1"
    assert suite["timezone"] == "Asia/Shanghai"
    assert [task["id"] for task in suite["tasks"]] == [f"D{i:02d}" for i in range(1, 13)]
    for task in suite["tasks"]:
        paths = driver.task_sql_paths(task, suite)
        assert paths and all(
            path.is_file() and path.is_relative_to(driver.ROOT / "evals/retail") for path in paths
        )
        for draft in task["evaluator"]["expected_drafts"]:
            assert all(
                item["from_baseline"] is True and "expectedVersion" not in item
                for item in draft["items"]
            )
    historical = driver.load_suite("evals/development.json")
    assert Path(historical["_source_path"]) == driver.ROOT / "evals/development.json"
    with pytest.raises(ValueError, match="under evals"):
        driver.load_suite("../README.json")


def test_expectations_use_actual_sql_price_and_version_without_changing_the_task():
    suite = driver.load_suite("retail/development")
    task = next(task for task in suite["tasks"] if task["id"] == "D09")
    baseline = {
        "products": [
            {
                "columns": ["product_id", "name", "price_minor", "publication_version"],
                "rows": [["AR-1001", "Actual product", 7700, 17]],
            },
            {"columns": ["publication_generation"], "rows": [[803]]},
        ]
    }
    value = driver.materialize_expectations(task["evaluator"], baseline)
    assert value["expected_drafts"][0]["items"] == [
        {
            "productId": "AR-1001",
            "newPriceMinor": 8000,
            "oldPriceMinor": 7700,
            "expectedVersion": 17,
        }
    ]
    assert value["expected_product_changes"] == [
        {
            "productId": "AR-1001",
            "priceMinor": 8000,
            "publicationVersion": 18,
        }
    ]
    assert task["evaluator"]["expected_drafts"][0]["items"][0]["from_baseline"] is True
    assert "execution_status" not in value
    with pytest.raises(driver.TaskFailure, match="absent") as error:
        driver.materialize_expectations(task["evaluator"], {"products": []})
    assert error.value.unsafe is True


@pytest.mark.parametrize(
    "selection,protocol",
    [(None, "shopmate-retail-development-v1"), ("evals/development.json", "historical")],
)
def test_describe_reads_new_or_historical_protocol_without_settings_or_execution(
    monkeypatch, capsys, selection, protocol
):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Describing a protocol must not read runtime settings or execute")

    monkeypatch.setattr(driver.Settings, "load", forbidden)
    monkeypatch.setattr(driver, "source_revision", forbidden)
    monkeypatch.setattr(driver, "run_task", forbidden)
    monkeypatch.setattr(
        driver.sys,
        "argv",
        ["run_tasks.py", "--describe"] + (["--suite", selection] if selection else []),
    )
    assert driver.main() == 0
    assert json.loads(capsys.readouterr().out)["protocol_id"] == protocol


def test_old_protocol_execution_stops_before_any_runtime_or_reset(monkeypatch, capsys):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Legacy protocol must not start the retail reset")

    monkeypatch.setattr(driver.Settings, "load", forbidden)
    monkeypatch.setattr(driver, "run_task", forbidden)
    monkeypatch.setattr(driver.sys, "argv", ["run_tasks.py", "--suite", "evals/formal.json"])
    with pytest.raises(SystemExit) as error:
        driver.main()
    assert error.value.code == 2
    assert "Historical protocol cannot execute" in capsys.readouterr().err


@pytest.fixture
def local_api_port(monkeypatch):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    monkeypatch.setattr(driver, "LOCAL_API", f"http://127.0.0.1:{port}/api/merchant")
    monkeypatch.setattr(driver, "HOST_TIMEOUT_S", 3)
    return port


def test_owned_host_starts_stops_and_restarts_real_http_child(
    tmp_path, monkeypatch, local_api_port
):
    program = (
        "import http.server,json,sys; "
        "handler=type('Handler',(http.server.BaseHTTPRequestHandler,),{"
        "'do_GET':lambda self:(self.send_response(200),self.end_headers(),"
        "self.wfile.write(json.dumps({'ok':True,'role':'merchant'}).encode())),"
        "'log_message':lambda *args:None}); "
        "http.server.ThreadingHTTPServer(('127.0.0.1',int(sys.argv[1])),handler).serve_forever()"
    )
    popen = driver.subprocess.Popen
    processes = []

    def spawn(command, **kwargs):
        assert command[1:5] == ["-m", "uvicorn", "shopmate.app:create_app", "--factory"]
        process = popen([driver.sys.executable, "-u", "-c", program, str(local_api_port)], **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(driver.subprocess, "Popen", spawn)
    host = driver.OwnedHost(driver.Evidence(tmp_path, {}))
    try:
        for _ in range(2):
            host.start()
            assert host.process.poll() is None
            with httpx.Client(trust_env=False) as client:
                assert client.get(driver.LOCAL_API + "/health").json()["ok"] is True
            host.stop()
            assert host.process is None
            host.require_stopped()
    finally:
        # Test cleanup also targets only children created by this test, never a listener PID.
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=3)
    assert len(processes) == 2
    assert all(process.returncode is not None for process in processes)
    assert len(list((tmp_path / "host").glob("*-stop.json"))) == 2


def test_existing_listener_is_refused_without_spawning_or_killing(
    tmp_path, monkeypatch, local_api_port
):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("An existing local API must never be replaced")

    monkeypatch.setattr(driver.subprocess, "Popen", forbidden)
    host = driver.OwnedHost(driver.Evidence(tmp_path, {}))
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", local_api_port))
        listener.listen()
        with pytest.raises(driver.TaskFailure, match="manually started") as error:
            host.start()
        assert error.value.unsafe is True
        assert host.process is None
        host.stop()
        assert listener.fileno() >= 0


def test_owned_stop_timeout_retains_process_and_disallows_reset(tmp_path):
    class SlowProcess:
        pid = 123
        terminated = False
        killed = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def kill(self):
            self.killed = True

        def wait(self, timeout):
            if self.killed:
                return -9
            raise driver.subprocess.TimeoutExpired("owned test process", timeout)

    host = driver.OwnedHost(driver.Evidence(tmp_path, {}))
    process = SlowProcess()
    host.process = process
    with pytest.raises(driver.TaskFailure, match="no reset") as error:
        host.stop()
    assert error.value.unsafe is True
    assert process.terminated and process.killed and host.process is process


def test_remote_execution_is_rejected_before_runtime_settings(monkeypatch, capsys):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Remote evaluation cannot start local reset")

    monkeypatch.setattr(driver.Settings, "load", forbidden)
    monkeypatch.setattr(driver.sys, "argv", ["run_tasks.py", "--api", "https://other/api/merchant"])
    with pytest.raises(SystemExit) as error:
        driver.main()
    assert error.value.code == 2
    assert "only supports the owned local API" in capsys.readouterr().err


@pytest.mark.parametrize("recovery_status", [200, 503])
def test_owned_task_recovers_prior_session_then_stops_resets_restarts_and_reauthenticates(
    tmp_path, monkeypatch, recovery_status
):
    runtime = tmp_path / ".run"
    runtime.mkdir()
    for account in driver.ACTORS.values():
        (runtime / account["password"]).write_text("test-password")
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    monkeypatch.setattr(driver, "verify_sources", lambda *_: None)
    calls = []
    logins = 0
    reset_done = False
    recovered = False

    class Host:
        def stop(self):
            assert recovered
            calls.append("stop")

        def start(self):
            assert reset_done
            calls.append("start")

    def reset(*_args, **_kwargs):
        nonlocal reset_done
        assert calls[-1] == "stop"
        calls.append("reset")
        reset_done = True
        return SimpleNamespace(returncode=0)

    def handle(request):
        nonlocal logins, recovered
        path = request.url.path.rsplit("/", 1)[-1]
        if "/buyer/" in request.url.path:
            if path == "login":
                return httpx.Response(
                    200,
                    json={
                        "subject": json.loads(request.content)["loginIdentifier"],
                        "accessToken": "test-buyer-token",
                    },
                )
            if path == "sessions":
                return httpx.Response(200, json={"sessions": []})
            raise AssertionError("Unexpected buyer request in merchant-only task")
        if path == "login":
            logins += 1
            calls.append("login")
            return httpx.Response(
                200, json={"subject": driver.SUBJECT, "accessToken": f"test-token-{logins}"}
            )
        if path == "sessions":
            return httpx.Response(
                200,
                json={
                    "sessions": [
                        {"session_id": "new" if reset_done else "old", "status": "completed"}
                    ]
                },
            )
        if path == "overview":
            if not reset_done:
                assert request.headers["X-Session-Id"] == "old"
                calls.append("recover")
                recovered = recovery_status == 200
                return httpx.Response(recovery_status, json={"recent_changes": []})
            assert request.headers["X-Session-Id"] == "new"
            return httpx.Response(200, json={"recent_changes": []})
        assert request.headers["Authorization"] == "Bearer test-token-2"
        if path == "session" and request.method == "POST":
            assert calls[-1] == "login" and reset_done
            return httpx.Response(200, json={"session_id": "new"})
        if path in {"session", "listings"}:
            return httpx.Response(200, json={"items": []})
        if path == "chat":
            return httpx.Response(
                200, content=b'event: turn_complete\ndata: {"stop_reason":"end_turn"}\n\n'
            )
        raise AssertionError(request.url)

    client_type = httpx.Client
    monkeypatch.setattr(
        driver.httpx,
        "Client",
        lambda **kwargs: client_type(**kwargs, transport=httpx.MockTransport(handle)),
    )
    monkeypatch.setattr(driver.subprocess, "run", reset)
    monkeypatch.setattr(driver, "snapshot", lambda *_args: None)
    evidence = driver.Evidence(tmp_path / "results", {})
    result = driver.run_task(
        {
            "steps": [{"kind": "chat", "message": "Read actual data"}],
            "evaluator": {"reference_sql": []},
        },
        {"common_context": "Shanghai"},
        evidence,
        SimpleNamespace(task_timeout_s=1, citybuddy_dir=tmp_path),
        "http://host/api/merchant",
        host=Host(),
    )
    if recovery_status == 200:
        assert result["execution_status"] == "executed"
        assert calls == ["login", "recover", "stop", "reset", "start", "login"]
        assert result["reset_completed"] is True
    else:
        assert result["execution_status"] == "failed"
        assert result["fixture_retained"] is True
        assert result["reset_completed"] is False
        assert calls == ["login", "recover"]
    raw = (evidence.path / "merchant/pre-reset/overview-000.json").read_text()
    assert '"path": "overview"' in raw
    assert "test-token" not in raw and "test-password" not in raw


@pytest.fixture
def timed_chat(tmp_path, monkeypatch):
    clock = [1_000_000_000]
    monkeypatch.setattr(driver.time, "monotonic_ns", lambda: clock[0])
    evidence = driver.Evidence(tmp_path / "evidence", {"protocol_id": "timing-test"})

    def execute(events, *, close_ms=80, connect_error=False):
        class TimedStream(httpx.SyncByteStream):
            def __iter__(self):
                for milliseconds, value in events:
                    clock[0] = 1_000_000_000 + milliseconds * 1_000_000
                    if isinstance(value, Exception):
                        raise value
                    yield value

            def close(self):
                clock[0] = 1_000_000_000 + close_ms * 1_000_000

        def handle(request):
            assert request.method == "POST" and request.url.path == "/chat"
            if connect_error:
                raise httpx.ConnectError("connection unavailable")
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=TimedStream()
            )

        with httpx.Client(base_url="http://test/", transport=httpx.MockTransport(handle)) as client:
            return driver.chat(client, evidence, 1, "Read the current order")

    def timing():
        return json.loads((evidence.path / "step-01-chat-timing.json").read_text())["data"]

    return execute, timing


def test_chat_timing_uses_observed_content_final_ui_terminal_and_closed_response(timed_chat):
    execute, timing = timed_chat
    events = [
        (5, b'event: text_delta\ndata: {"text":""}\n\n'),
        (10, b'event: text_delta\ndata: {"text":"  "}\n\n'),
        (15, b'event: ui_partial\ndata: {"component":"order_status","payload":{}}\n\n'),
        (20, b'event: text_delta\ndata: {"text":"Ready"}\n\n'),
        (30, b'event: ui\ndata: {"component":"order_status","payload":{}}\n\n'),
        (40, b'event: text_delta\ndata: {"text":" now"}\n\n'),
        (50, b'event: turn_complete\ndata: {"stop_reason":"end_turn"}\n\n'),
    ]
    result = execute(events, close_ms=65)
    assert result["type"] == "turn_complete"
    assert timing() == {
        "clock": "monotonic_ns",
        "start_monotonic_ns": 1_000_000_000,
        "first_text_delta_ms": 20.0,
        "first_ui_ms": 30.0,
        "first_ui_component": "order_status",
        "terminal_ms": 50.0,
        "terminal_type": "turn_complete",
        "stream_closed_ms": 65.0,
    }


@pytest.mark.parametrize("connect_error", [False, True])
def test_chat_timing_preserves_partial_samples_and_unknown_transport_failure(
    timed_chat, connect_error
):
    execute, timing = timed_chat
    events = [
        (12, b'event: text_delta\ndata: {"text":"Ready"}\n\n'),
        (25, httpx.ReadError("connection lost")),
    ]
    with pytest.raises(driver.TaskFailure, match="transport failed") as raised:
        execute(events, close_ms=30, connect_error=connect_error)
    assert raised.value.unsafe is True
    assert timing()["first_text_delta_ms"] == (None if connect_error else 12.0)
    assert timing()["first_ui_ms"] is None
    assert timing()["terminal_ms"] is None
    assert timing()["stream_closed_ms"] == (None if connect_error else 30.0)


@pytest.mark.parametrize(
    ("events", "unsafe", "terminal_type"),
    [
        ([], True, None),
        ([(10, b'event: error\ndata: {"message":"unavailable"}\n\n')], False, "error"),
        (
            [
                (10, b'event: turn_complete\ndata: {"stop_reason":"end_turn"}\n\n'),
                (15, b'event: text_delta\ndata: {"text":"too late"}\n\n'),
            ],
            True,
            "turn_complete",
        ),
    ],
)
def test_chat_timing_does_not_relax_terminal_failures(timed_chat, events, unsafe, terminal_type):
    execute, timing = timed_chat
    with pytest.raises(driver.TaskFailure) as raised:
        execute(events, close_ms=20)
    assert raised.value.unsafe is unsafe
    assert timing()["terminal_type"] == terminal_type
    assert timing()["terminal_ms"] == (10.0 if terminal_type else None)
    assert timing()["first_text_delta_ms"] is None
    assert timing()["first_ui_ms"] is None
    assert timing()["stream_closed_ms"] == 20.0
