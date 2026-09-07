"""Retail driver boundaries use HTTP doubles and the real local command store."""

import importlib.util
import json
import signal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from shopmate.buyer_commands import BuyerCommands
from shopmate.sessions import SessionStore


@pytest.fixture
def driver(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location("retail_runner_cases", scripts / "run_tasks.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def evidence(driver, tmp_path):
    return driver.Evidence(tmp_path / "evidence", {}, write_marker=tmp_path / "write.json")


@pytest.mark.parametrize("unknown_at", ["session", "commands"])
@pytest.mark.parametrize("kind", ["cart", "checkout", "refund"])
def test_completed_buyer_with_unknown_command_is_not_reset_safe(driver, evidence, unknown_at, kind):
    calls = []

    def respond(request):
        endpoint = request.url.path.rsplit("/", 1)[-1]
        calls.append((request.method, endpoint))
        commands = [{"kind": kind, "state": "unknown"}]
        values = {
            "session": {
                "run_status": "completed",
                "commands": commands if unknown_at == "session" else [],
            },
            "commands": {"commands": commands},
            "checkouts": {"checkouts": []},
            "actions": {"actions": []},
            "sessions": {"sessions": [{"session_id": "buyer-session", "status": "completed"}]},
        }
        return httpx.Response(200, json=values[endpoint])

    with httpx.Client(
        base_url="http://unit.test/api/buyer/", transport=httpx.MockTransport(respond)
    ) as client:
        client.headers["Authorization"] = "Bearer fake-buyer-token"
        with pytest.raises(driver.TaskFailure) as failed:
            driver.recover_actor(client, evidence, [{"session_id": "buyer-session"}], "buyer")
        assert failed.value.unsafe
        assert "X-Session-Id" not in client.headers
        assert client.headers["Authorization"] == "Bearer fake-buyer-token"
    assert all(method == "GET" for method, _ in calls)
    # Empty checkout/action lists cannot settle a registered command whose result is unknown.
    assert calls[-1][1] == unknown_at


def test_buyer_recovery_reads_all_terminal_views_without_retrying_writes(driver, evidence):
    calls = []

    def respond(request):
        endpoint = request.url.path.rsplit("/", 1)[-1]
        calls.append((request.method, endpoint, request.headers.get("X-Session-Id")))
        commands = [{"state": "confirmed"}, {"state": "rejected"}]
        return httpx.Response(
            200,
            json={
                "session": {"run_status": "completed", "commands": commands},
                "commands": {"commands": commands},
                "checkouts": {"checkouts": []},
                "actions": {"actions": []},
                "sessions": {"sessions": [{"session_id": "buyer-session", "status": "completed"}]},
            }[endpoint],
        )

    with httpx.Client(
        base_url="http://unit.test/api/buyer/", transport=httpx.MockTransport(respond)
    ) as client:
        driver.recover_actor(client, evidence, [{"session_id": "buyer-session"}], "buyer2")
        assert "X-Session-Id" not in client.headers
    assert [endpoint for _, endpoint, _ in calls] == [
        "session",
        "commands",
        "checkouts",
        "actions",
        "sessions",
    ]
    assert all(method == "GET" for method, _, _ in calls)
    assert all(session == "buyer-session" for _, _, session in calls[:4])


@pytest.fixture
def local_store(tmp_path):
    path = tmp_path / "sessions.sqlite3"
    store = SessionStore(path)
    commands = BuyerCommands(store)
    try:
        yield store, commands, SimpleNamespace(state_path=path)
    finally:
        store.close()


def register_unknown(store, commands, owner, kind="checkout"):
    session = store.create(owner, role="buyer")
    session.status = "completed"
    store.save(session)
    command = commands.register(
        session_id=session.session_id,
        owner=owner,
        turn_id="turn-1",
        call_id="call-1",
        kind=kind,
        operation="create" if kind == "checkout" else "prepare",
        arguments={},
        body={"request_key": "unit-test-command"},
    )
    return session, command


def test_local_reset_only_checks_exact_fixture_owners_and_does_not_mutate(driver, local_store):
    store, commands, settings = local_store
    owner = driver.ACTORS["buyer"]["subject"]
    inspected = store.create(owner, role="buyer")
    outsider, unknown = register_unknown(store, commands, owner + "-unrelated")
    outsider.status = "running"
    store.save(outsider)
    before = list(store.db.iterdump())
    driver.local_reset_preflight(settings, {(owner, "buyer", inspected.session_id)})
    assert list(store.db.iterdump()) == before
    assert commands.get(unknown.key, outsider.session_id, outsider.owner).result is None


@pytest.mark.parametrize("coverage", ["missing", "wrong_owner", "wrong_role", "wrong_session"])
def test_local_reset_rejects_fixture_session_without_exact_observation(
    driver, local_store, coverage
):
    store, _, settings = local_store
    owner = driver.ACTORS["buyer"]["subject"]
    session = store.create(owner, role="buyer")
    covered = {
        "missing": set(),
        "wrong_owner": {(owner + "-other", "buyer", session.session_id)},
        "wrong_role": {(owner, "merchant", session.session_id)},
        "wrong_session": {(owner, "buyer", "other-session")},
    }[coverage]
    with pytest.raises(driver.TaskFailure) as failed:
        driver.local_reset_preflight(settings, covered)
    assert failed.value.unsafe
    assert store.get(session.session_id, owner, role="buyer").session_id == session.session_id


@pytest.mark.parametrize("kind", ["cart", "checkout", "refund"])
def test_local_reset_rejects_unknown_durable_write_even_after_http_inspection(
    driver, local_store, kind
):
    store, commands, settings = local_store
    owner = driver.ACTORS["buyer"]["subject"]
    session, command = register_unknown(store, commands, owner, kind)
    covered = {(owner, "buyer", session.session_id)}
    with pytest.raises(driver.TaskFailure) as failed:
        driver.local_reset_preflight(settings, covered)
    assert failed.value.unsafe
    commands.reject(command, "VERSION_CONFLICT")
    driver.local_reset_preflight(settings, covered)


def test_local_reset_keeps_merchant_prepare_and_nonlogin_fixture_owner_protection(
    driver, local_store
):
    from retail_fixture import fixture_owners

    store, _, settings = local_store
    login_owners = {actor["subject"] for actor in driver.ACTORS.values()}
    history_owner = next(owner for owner in fixture_owners() if owner not in login_owners)
    history_session = store.create(history_owner, role="buyer")
    with pytest.raises(driver.TaskFailure) as failed:
        driver.local_reset_preflight(settings, set())
    assert failed.value.unsafe
    merchant = store.create(driver.SUBJECT)
    intent = store.prepare_intent(merchant.session_id, "turn-1", {"currency": "CNY", "items": []})
    covered = {
        (history_owner, "buyer", history_session.session_id),
        (driver.SUBJECT, "merchant", merchant.session_id),
    }
    with pytest.raises(driver.TaskFailure) as failed:
        driver.local_reset_preflight(settings, covered)
    assert failed.value.unsafe
    store.reject_intent(intent.key, "VERSION_CONFLICT")
    driver.local_reset_preflight(settings, covered)


@pytest.mark.parametrize(
    "status,body,unsafe",
    [
        (409, {"detail": {"category": "INDETERMINATE"}}, True),
        (409, {"detail": {"category": "RETRYABLE_CONCURRENCY"}}, True),
        (429, {"detail": "Rate limited"}, True),
        (409, {"detail": "Unknown transaction status"}, True),
        (400, {}, True),
        (503, {"detail": "Unavailable"}, True),
        (400, {"detail": "Invalid request"}, False),
        (409, {"detail": {"category": "VERSION_CONFLICT"}}, False),
    ],
)
def test_write_marker_precedes_request_and_only_known_rejection_clears_it(
    driver, evidence, status, body, unsafe
):
    def respond(request):
        assert json.loads(evidence.write_marker.read_text())["path"] == "checkouts"
        recorded = json.loads((evidence.path / "checkout-request.json").read_text())["data"]
        assert recorded["body"] == {"request_key": "original-key"}
        assert json.loads(request.content) == recorded["body"]
        return httpx.Response(status, json=body)

    with (
        httpx.Client(
            base_url="http://unit.test/api/buyer/", transport=httpx.MockTransport(respond)
        ) as client,
        pytest.raises(driver.TaskFailure) as failed,
    ):
        driver.request_json(
            client,
            evidence,
            "checkout.json",
            "POST",
            "checkouts",
            body={"request_key": "original-key"},
            write=True,
        )
    assert failed.value.unsafe is unsafe
    assert evidence.write_marker.exists() is unsafe
    response = json.loads((evidence.path / "checkout.json").read_text())["data"]
    assert response["status_code"] == status
    assert json.loads(response["response_body"]) == body


@pytest.mark.parametrize("outcome", ["lost", "malformed_json", "nonobject_json"])
def test_unknown_write_response_persists_marker_without_retry(driver, evidence, outcome):
    calls = []

    def respond(request):
        calls.append(request)
        assert evidence.write_marker.exists()
        if outcome == "lost":
            raise httpx.ReadError("Response lost", request=request)
        if outcome == "malformed_json":
            return httpx.Response(200, content=b"not JSON")
        return httpx.Response(200, json=[])

    with (
        httpx.Client(
            base_url="http://unit.test/api/buyer/", transport=httpx.MockTransport(respond)
        ) as client,
        pytest.raises(driver.TaskFailure) as failed,
    ):
        driver.request_json(
            client, evidence, "confirm.json", "POST", "actions/id/confirm", write=True
        )
    assert failed.value.unsafe
    assert evidence.write_marker.exists()
    assert len(calls) == 1


def test_existing_unknown_write_blocks_next_http_write_and_preserves_original_marker(
    driver, evidence
):
    evidence.write_marker.write_text('{"path":"previous-request"}')

    def respond(request):
        pytest.fail("A second write must not be dispatched")

    with (
        httpx.Client(
            base_url="http://unit.test/api/buyer/", transport=httpx.MockTransport(respond)
        ) as client,
        pytest.raises(driver.TaskFailure) as failed,
    ):
        driver.request_json(client, evidence, "next.json", "POST", "checkouts", write=True)
    assert failed.value.unsafe
    assert json.loads(evidence.write_marker.read_text()) == {"path": "previous-request"}


def test_three_actor_task_keeps_tokens_sessions_separate_and_resets_only_once(
    driver, evidence, tmp_path, monkeypatch
):
    runtime = tmp_path / ".run"
    runtime.mkdir()
    for actor in driver.ACTORS.values():
        (runtime / actor["password"]).write_text("test-password")
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    monkeypatch.setattr(driver, "verify_sources", lambda *_: None)
    snapshots = []

    def snapshot(*args):
        snapshots.append(dict(args[4]))
        return {}

    monkeypatch.setattr(driver, "snapshot", snapshot)
    resets, lifecycle, requests, clients = [], [], [], []
    logins, sessions = {}, {}
    by_subject = {account["subject"]: actor for actor, account in driver.ACTORS.items()}

    def reset(*args, **kwargs):
        resets.append(args[0])
        assert lifecycle == ["stop"]
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(driver.subprocess, "run", reset)

    def respond(request):
        endpoint = request.url.path.rsplit("/", 1)[-1]
        if endpoint == "login":
            subject = json.loads(request.content)["loginIdentifier"]
            actor = by_subject[subject]
            assert "Authorization" not in request.headers
            assert "X-Session-Id" not in request.headers
            logins[actor] = logins.get(actor, 0) + 1
            token = "fake-token-" + actor
            return httpx.Response(200, json={"subject": subject, "accessToken": token})
        actor = request.headers["Authorization"].removeprefix("Bearer fake-token-")
        assert actor in driver.ACTORS
        assert request.url.path.startswith("/api/" + driver.ACTORS[actor]["role"] + "/")
        supplied_session = request.headers.get("X-Session-Id")
        if supplied_session is not None:
            assert supplied_session == "session-" + actor
        requests.append((actor, endpoint, supplied_session))
        if endpoint == "session" and request.method == "POST":
            assert len(resets) == 1 and lifecycle == ["stop", "start"]
            sessions[actor] = "session-" + actor
            return httpx.Response(200, json={"session_id": sessions[actor]})
        if endpoint == "sessions":
            return httpx.Response(
                200,
                json={
                    "sessions": [{"session_id": sessions[actor], "status": "completed"}]
                    if actor in sessions
                    else []
                },
            )
        if endpoint == "session":
            return httpx.Response(
                200, json={"run_status": "completed", "commands": [], "items": []}
            )
        if endpoint == "chat":
            return httpx.Response(
                200,
                content=b'event: turn_complete\ndata: {"stop_reason":"end_turn"}\n\n',
                headers={"content-type": "text/event-stream"},
            )
        assert endpoint in {"cart", "listings", "overview"}
        return httpx.Response(200, json={})

    client_type = httpx.Client

    def client_factory(**kwargs):
        client = client_type(**kwargs, transport=httpx.MockTransport(respond))
        clients.append(client)
        return client

    monkeypatch.setattr(driver.httpx, "Client", client_factory)
    settings = SimpleNamespace(
        task_timeout_s=1, citybuddy_dir=tmp_path, state_path=tmp_path / "absent.sqlite3"
    )
    task = {
        "steps": [
            {"kind": "chat", "actor": actor, "message": "test request"}
            for actor in ("buyer", "buyer2", "merchant", "buyer")
        ],
        "evaluator": {"reference_sql": []},
    }
    host = SimpleNamespace(
        stop=lambda: lifecycle.append("stop"), start=lambda: lifecycle.append("start")
    )
    result = driver.run_task(
        task, {"common_sql": []}, evidence, settings, driver.LOCAL_API, host=host
    )
    assert result["execution_status"] == "executed"
    assert result["reset_completed"] is True
    assert result["sessions"] == {actor: "session-" + actor for actor in driver.ACTORS}
    assert logins == {actor: 2 for actor in driver.ACTORS}
    assert len(resets) == 1
    assert snapshots
    for bindings in snapshots:
        for actor, account in driver.ACTORS.items():
            assert bindings[actor + "_subject"] == account["subject"]
            assert bindings[actor + "_session_id"] == "session-" + actor
    assert lifecycle == ["stop", "start"]
    assert [actor for actor, endpoint, _ in requests if endpoint == "chat"] == [
        "buyer",
        "buyer2",
        "merchant",
        "buyer",
    ]
    assert len({id(client.headers) for client in clients}) == 3
    assert all(client.is_closed for client in clients)
    assert not evidence.write_marker.exists()


def test_sigterm_unwinds_main_and_stops_only_its_owned_host(driver, tmp_path, monkeypatch):
    (tmp_path / ".run").mkdir()
    monkeypatch.setattr(driver, "ROOT", tmp_path)
    monkeypatch.setattr(driver.sys, "argv", ["run_tasks.py"])
    suite = {
        "_source_path": str(tmp_path / "evals/retail/development.json"),
        "schema_version": 2,
        "fixture_version": "shopmate-retail-v1",
        "protocol_id": "unit-test",
        "suite": "unit-test",
        "as_of": "2026-09-01T00:00:00+00:00",
        "timezone": "Asia/Shanghai",
        "repetitions": 1,
        "tasks": [{"id": "one"}],
    }
    settings = SimpleNamespace(
        citybuddy_dir=tmp_path,
        as_of=suite["as_of"],
        model="fake",
        analysis_model="fake",
        task_timeout_s=1,
        max_model_calls=2,
    )
    monkeypatch.setattr(driver, "load_suite", lambda _: suite)
    monkeypatch.setattr(driver.Settings, "load", lambda: settings)
    monkeypatch.setattr(driver, "source_revision", lambda *_: "a" * 40)
    monkeypatch.setattr(driver, "verify_sources", lambda *_: None)
    handlers, lifecycle = {}, []
    monkeypatch.setattr(
        driver.signal, "signal", lambda number, handler: handlers.__setitem__(number, handler)
    )
    host = SimpleNamespace(
        start=lambda: lifecycle.append("start"), stop=lambda: lifecycle.append("stop")
    )
    monkeypatch.setattr(driver, "OwnedHost", lambda _: host)

    def interrupted_task(*args, **kwargs):
        assert kwargs["host"] is host
        handlers[signal.SIGTERM](signal.SIGTERM, None)

    monkeypatch.setattr(driver, "run_task", interrupted_task)
    with pytest.raises(InterruptedError, match="Evaluation interrupted"):
        driver.main()
    assert handlers[signal.SIGTERM] is signal.SIG_IGN
    assert lifecycle == ["start", "stop"]
    outputs = list((tmp_path / "evals/results").glob("*/run.json"))
    assert len(outputs) == 1
    record = json.loads(outputs[0].read_text())["data"]
    assert record["stop_reason"] == "Execution stopped: InterruptedError"
    assert record["executions"][0]["execution_status"] == "not_run"
