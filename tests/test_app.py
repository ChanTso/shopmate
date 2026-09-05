import asyncio
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from commerce_common.streaming import AgentEvent
from fastapi import HTTPException
from merchant_agent import StagedChange

from shopmate.app import create_app
from shopmate.auth import RequestIdentity, current_context
from shopmate.sessions import SessionStore


class Auth:
    async def verify(self, token):
        return RequestIdentity(token, token)


class Provider:
    @asynccontextmanager
    async def task_budget(self):
        yield SimpleNamespace(
            summary=lambda: {"model_calls": 1, "usage_complete": False, "calls_with_usage": 0}
        )


class Agent:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.wait = False
        self.fail = False

    async def stream_turn(self, messages, session, state):
        assert current_context().identity.subject == session.operator
        assert current_context().turn_id
        self.started.set()
        if self.wait:
            await self.release.wait()
        if self.fail:
            raise RuntimeError("private upstream error containing test-secret")
        messages.append({"role": "assistant", "content": "Hello"})
        yield AgentEvent.text_delta("Hello")
        yield AgentEvent(
            type="ui", data={"component": "metrics", "payload": {"heading": "Revenue"}}
        )
        yield AgentEvent(type="turn_complete", data={"stop_reason": "end_turn"})


class Backend:
    def __init__(self, store):
        self.store = store
        self.calls = []
        self.status = "staged"

    async def get_change(self, session, change_id):
        if not self.store.owns_draft(session.session_id, change_id):
            raise HTTPException(404, "Draft not found")
        return StagedChange(
            change_id=change_id,
            kind="price_update",
            status=self.status,
            summary="Mug price",
            created_at=datetime.now(UTC),
            created_by=session.operator,
            receipt={
                "draftId": change_id,
                "state": "APPLIED" if self.status == "applied" else "PREPARED",
            },
        )

    async def apply_by_operator(self, session, change_id):
        self.calls.append(current_context())
        self.status = "applied"
        change = await self.get_change(session, change_id)
        return {"ok": True, "change": change, "receipt": change.receipt}


@pytest.fixture
async def rig(tmp_path):
    store = SessionStore(tmp_path / "state.sqlite3")
    agent = Agent()
    backend = Backend(store)
    app = create_app(
        SimpleNamespace(),
        auth=Auth(),
        store=store,
        backend=backend,
        agent=agent,
        provider=Provider(),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        response = await client.post(
            "/api/merchant/session", headers={"Authorization": "Bearer owner"}
        )
        session_id = response.json()["session_id"]
        headers = {"Authorization": "Bearer owner", "X-Session-Id": session_id}
        yield SimpleNamespace(
            client=client,
            store=store,
            agent=agent,
            backend=backend,
            headers=headers,
            session_id=session_id,
        )
    store.close()


async def test_cross_owner_session_and_list_do_not_leak(rig):
    response = await rig.client.get(
        "/api/merchant/session", headers=rig.headers | {"Authorization": "Bearer other"}
    )
    assert response.status_code == 404
    response = await rig.client.get(
        "/api/merchant/sessions", headers={"Authorization": "Bearer other"}
    )
    assert response.json() == {"sessions": []}


async def test_completed_turn_restores_ui_and_runtime_history(rig):
    response = await rig.client.post(
        "/api/merchant/chat", headers=rig.headers, json={"message": "Analyze revenue"}
    )
    assert response.status_code == 200 and "turn_complete" in response.text
    restored = (await rig.client.get("/api/merchant/session", headers=rig.headers)).json()
    assert restored["status"] == "completed"
    assert restored["items"][-1]["provider_usage"]["usage_complete"] is False
    assert '"provider_usage"' in response.text
    assert restored["items"][-1]["pending"] is False
    assert restored["items"][-1]["segments"][-1]["block"]["payload"] == {"heading": "Revenue"}
    assert rig.store.get(rig.session_id, "owner").messages[-1]["content"] == "Hello"


async def test_busy_blocks_second_chat_and_apply_but_keeps_reads(rig):
    rig.agent.wait = True
    task = asyncio.create_task(
        rig.client.post("/api/merchant/chat", headers=rig.headers, json={"message": "Analyze"})
    )
    await rig.agent.started.wait()
    try:
        assert (
            await rig.client.post(
                "/api/merchant/chat", headers=rig.headers, json={"message": "Again"}
            )
        ).status_code == 409
        assert (
            await rig.client.post("/api/merchant/changes/draft/apply", headers=rig.headers)
        ).status_code == 409
        assert (
            await rig.client.get("/api/merchant/session", headers=rig.headers)
        ).status_code == 200
    finally:
        rig.agent.release.set()
        await task


async def test_model_error_is_terminal_and_does_not_expose_exception(rig):
    rig.agent.fail = True
    response = await rig.client.post(
        "/api/merchant/chat", headers=rig.headers, json={"message": "Analyze"}
    )
    assert "test-secret" not in response.text
    record = rig.store.get(rig.session_id, "owner")
    assert record.status == "failed" and record.items[-1]["pending"] is False
    rig.agent.fail = False
    assert (
        await rig.client.post("/api/merchant/chat", headers=rig.headers, json={"message": "Retry"})
    ).status_code == 200


async def test_cancelled_stream_becomes_interrupted_and_unblocks_session(rig):
    rig.agent.wait = True
    task = asyncio.create_task(
        rig.client.post("/api/merchant/chat", headers=rig.headers, json={"message": "Analyze"})
    )
    await rig.agent.started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    record = rig.store.get(rig.session_id, "owner")
    assert record.status == "interrupted" and record.items[-1]["pending"] is False
    rig.agent.wait = False
    assert (
        await rig.client.post("/api/merchant/chat", headers=rig.headers, json={"message": "Retry"})
    ).status_code == 200


async def test_operator_approval_uses_current_direct_identity_and_receipt_recovery(rig):
    rig.store.remember_draft(rig.session_id, "draft", {"state": "PREPARED"})
    response = await rig.client.post("/api/merchant/changes/draft/apply", headers=rig.headers)
    assert response.json()["receipt"]["state"] == "APPLIED"
    assert rig.backend.calls[-1].identity.token == "owner"
    assert rig.backend.calls[-1].turn_id is None
    assert rig.store.get(rig.session_id, "owner").state.seen_changes["draft"].status == "applied"
    again = await rig.client.get("/api/merchant/changes/draft", headers=rig.headers)
    assert again.json()["receipt"]["state"] == "APPLIED"


async def test_previous_stream_cleanup_cannot_touch_next_operator_action(rig, monkeypatch):
    from starlette.background import BackgroundTask

    background_ready = asyncio.Event()
    background_release = asyncio.Event()
    approval_ready = asyncio.Event()
    approval_release = asyncio.Event()
    original_background = BackgroundTask.__call__
    original_apply = rig.backend.apply_by_operator

    async def delayed_background(task):
        background_ready.set()
        await background_release.wait()
        await original_background(task)

    async def delayed_apply(session, change_id):
        approval_ready.set()
        await approval_release.wait()
        return await original_apply(session, change_id)

    monkeypatch.setattr(BackgroundTask, "__call__", delayed_background)
    monkeypatch.setattr(rig.backend, "apply_by_operator", delayed_apply)
    rig.store.remember_draft(rig.session_id, "draft", {"state": "PREPARED"})
    chat = asyncio.create_task(
        rig.client.post("/api/merchant/chat", headers=rig.headers, json={"message": "Analyze"})
    )
    approval = None
    try:
        async with asyncio.timeout(5):
            await background_ready.wait()
            approval = asyncio.create_task(
                rig.client.post("/api/merchant/changes/draft/apply", headers=rig.headers)
            )
            await approval_ready.wait()
            background_release.set()
            assert (await chat).status_code == 200
            assert rig.store.get(rig.session_id, "owner").status == "completed"
            blocked = await rig.client.post(
                "/api/merchant/chat", headers=rig.headers, json={"message": "Another task"}
            )
            assert blocked.status_code == 409
            approval_release.set()
            result = await approval
            assert result.status_code == 200
            assert result.json()["receipt"]["state"] == "APPLIED"
            assert (
                rig.store.get(rig.session_id, "owner").state.seen_changes["draft"].status
                == "applied"
            )
    finally:
        background_release.set()
        approval_release.set()
        await asyncio.gather(chat, *([approval] if approval else []), return_exceptions=True)
