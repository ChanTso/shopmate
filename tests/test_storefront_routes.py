import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from commerce_common.streaming import AgentEvent

from shopmate.app import create_app
from shopmate.auth import RequestIdentity, current_context
from shopmate.buyer_routes import ChatRequest
from shopmate.sessions import SessionStore
from shopmate.settings import Settings


class Auth:
    async def verify(self, token, *, role="merchant"):
        return RequestIdentity(token, token)


class Provider:
    @asynccontextmanager
    async def task_budget(self):
        yield SimpleNamespace(summary=dict)


class Agent:
    def __init__(self):
        self.started = asyncio.Queue()
        self.release = asyncio.Event()

    async def stream_turn(self, messages, context, state):
        self.started.put_nowait(current_context())
        await self.release.wait()
        yield AgentEvent.text_delta("Done")
        yield AgentEvent(type="turn_complete", data={})


class Backend:
    async def products_page(self, context, query, limit, offset):
        assert current_context().session_id == context.session_id
        return {"products": [], "next_offset": None}

    async def cart_mutation(self, context, operation, body, key):
        assert current_context().session_id == context.session_id
        return {"request_key": key, "operation": operation}

    async def recover_cart_commands(self, context):
        return []

    async def overview(self, context):
        assert current_context().session_id == context.session_id
        return {"operator": context.operator}


@pytest.fixture
async def portal(tmp_path):
    store = SessionStore(tmp_path / "state.sqlite3")
    agent = Agent()
    app = create_app(
        Settings(max_active_tasks=2, max_user_tasks=1),
        auth=Auth(),
        store=store,
        provider=Provider(),
        backend=Backend(),
        agent=agent,
        buyer_backend=Backend(),
        buyer_agent=agent,
        buyer_client=object(),
        transactions=object(),
    )
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client,
    ):
        yield SimpleNamespace(app=app, client=client, store=store, agent=agent)
    store.close()


def headers(owner="buyer"):
    return {"Authorization": "Bearer " + owner}


async def test_normal_shopping_and_merchant_reads_create_no_conversation(portal):
    p = portal
    assert (await p.client.get("/api/buyer/products", headers=headers())).status_code == 200
    assert (
        await p.client.post(
            "/api/buyer/cart/add",
            headers=headers(),
            json={
                "request_key": "add-1",
                "productId": "sku",
                "quantity": 1,
            },
        )
    ).status_code == 200
    assert (
        await p.client.get("/api/merchant/overview", headers=headers("operator"))
    ).status_code == 200
    assert p.store.db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
    assert (await p.client.get("/api/buyer/products")).status_code == 401
    first = p.store.storefront("buyer", role="buyer")
    assert first.session_id == p.store.storefront("buyer", role="buyer").session_id
    assert first.session_id != p.store.storefront("buyer", role="merchant").session_id


async def conversation(p, owner):
    result = await p.client.post("/api/buyer/conversations", headers=headers(owner))
    assert result.status_code == 200
    return result.json()["session_id"]


async def test_chat_limits_do_not_block_shopping_and_cancel_releases_capacity(portal):
    p = portal
    a1, a2, b, c = [await conversation(p, owner) for owner in ("a", "a", "b", "c")]

    def chat(identifier, owner):
        return p.client.post(
            f"/api/buyer/conversations/{identifier}/chat",
            headers=headers(owner),
            json={"message": "compare"},
        )

    tasks = []
    try:
        async with asyncio.timeout(5):
            tasks.append(asyncio.create_task(chat(a1, "a")))
            bound = await p.agent.started.get()
            assert bound.conversation_id == a1 and bound.session_id != a1
            assert (await chat(a1, "a")).status_code == 409
            assert (await chat(a2, "a")).status_code == 429
            assert (
                await p.client.post(
                    "/api/buyer/cart/add",
                    headers=headers("a"),
                    json={
                        "request_key": "add-while-chatting",
                        "productId": "sku",
                        "quantity": 1,
                    },
                )
            ).status_code == 200
            tasks.append(asyncio.create_task(chat(b, "b")))
            await p.agent.started.get()
            assert (await chat(c, "c")).status_code == 429
            assert (await chat(a1, "b")).status_code == 404
            tasks[0].cancel()
            with pytest.raises(asyncio.CancelledError):
                await tasks[0]
            tasks.append(asyncio.create_task(chat(c, "c")))
            await p.agent.started.get()
            p.agent.release.set()
            assert (await tasks[1]).status_code == 200
            assert (await tasks[2]).status_code == 200
    finally:
        p.agent.release.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    assert p.store.get(a1, "a", role="buyer").status == "interrupted"
    assert (await chat(a2, "a")).status_code == 200


def history_items(count):
    return [
        {"message_id": index, "kind": "user", "text": f"Message {index}"}
        if index % 2
        else {
            "message_id": index,
            "kind": "assistant",
            "turn": index // 2,
            "segments": [{"type": "text", "text": f"Answer {index}"}],
            "pending": False,
        }
        for index in range(1, count + 1)
    ]


async def test_buyer_history_pages_are_exclusive_and_unchanged_by_tail_append(portal):
    p = portal
    identifier = await conversation(p, "owner")
    record = p.store.get(identifier, "owner", role="buyer")
    record.items = history_items(74)
    p.store.save(record)
    path = f"/api/buyer/conversations/{identifier}/messages"
    response = await p.client.get(path, headers=headers("owner"))
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    latest = response.json()
    assert latest["session_id"] == identifier and latest["status"] == "idle"
    assert latest["items"] == record.items[-30:]
    assert latest["next_before"] == 45
    first_older = (
        await p.client.get(path, params={"before": 45, "limit": 20}, headers=headers("owner"))
    ).json()
    assert first_older["items"] == record.items[24:44]
    assert first_older["next_before"] == 25
    record.items = history_items(76)
    p.store.save(record)
    assert (
        await p.client.get(path, params={"before": 45, "limit": 20}, headers=headers("owner"))
    ).json() == first_older
    collected = first_older["items"] + latest["items"]
    before = first_older["next_before"]
    while before is not None:
        page = (
            await p.client.get(
                path, params={"before": before, "limit": 20}, headers=headers("owner")
            )
        ).json()
        assert all(item["message_id"] < before for item in page["items"])
        collected = page["items"] + collected
        before = page["next_before"]
    assert collected == history_items(74)
    empty = (await p.client.get(path, params={"before": 1}, headers=headers("owner"))).json()
    assert empty["items"] == [] and empty["next_before"] is None
    all_items = (await p.client.get(path, params={"limit": 100}, headers=headers("owner"))).json()
    assert all_items["items"] == history_items(76) and all_items["next_before"] is None


async def test_buyer_history_is_pure_read_and_legacy_restore_keeps_recovery(portal):
    p = portal
    identifier = await conversation(p, "owner")
    record = p.store.get(identifier, "owner", role="buyer")
    record.items = history_items(40)
    p.store.save(record)
    calls = []

    async def recover(context):
        calls.append("recover")
        return []

    async def checkouts(context):
        calls.append("checkouts")
        return []

    def actions(context):
        calls.append("actions")
        return []

    resources = p.app.state.resources
    resources["buyer_backend"].recover_cart_commands = recover
    resources["transactions"] = SimpleNamespace(checkouts=checkouts, actions=actions)
    recent = await p.client.get(
        f"/api/buyer/conversations/{identifier}/messages", headers=headers("owner")
    )
    assert recent.status_code == 200 and len(recent.json()["items"]) == 30
    assert calls == []
    for path, extra in [
        (f"/api/buyer/conversations/{identifier}", {}),
        ("/api/buyer/session", {"X-Session-Id": identifier}),
    ]:
        legacy = await p.client.get(path, headers=headers("owner") | extra)
        assert legacy.status_code == 200
        assert legacy.json()["items"] == record.items
        assert {"commands", "checkouts", "actions"} <= legacy.json().keys()
    assert calls == ["recover", "checkouts", "actions"] * 2


async def test_buyer_history_owner_role_and_query_boundaries(portal):
    p = portal
    identifier = await conversation(p, "owner")
    path = f"/api/buyer/conversations/{identifier}/messages"
    empty = await p.client.get(path, headers=headers("owner"))
    assert empty.json()["items"] == [] and empty.json()["next_before"] is None
    assert (await p.client.get(path)).status_code == 401
    assert (await p.client.get(path, headers=headers("other"))).status_code == 404
    merchant = p.store.create("owner")
    assert (
        await p.client.get(
            f"/api/buyer/conversations/{merchant.session_id}/messages", headers=headers("owner")
        )
    ).status_code == 404
    for params in [
        {"limit": 0},
        {"limit": 101},
        {"before": 0},
        {"before": "broken"},
        {"before": 2**63},
    ]:
        assert (
            await p.client.get(path, params=params, headers=headers("owner"))
        ).status_code == 422


async def test_buyer_start_ids_are_persisted_before_model_and_survive_early_close(portal):
    p = portal
    identifier = await conversation(p, "owner")
    endpoint = next(
        route.endpoint
        for route in p.app.routes
        if getattr(route, "path", None) == "/api/buyer/conversations/{conversation_id}/chat"
    )
    response = await endpoint(
        identifier, ChatRequest(message="first"), RequestIdentity("owner", "owner")
    )
    stream = response.body_iterator
    first = await anext(stream)
    assert first.startswith("event: turn_started\n")
    metadata = json.loads(first.split("data: ", 1)[1])
    assert metadata == {"session_id": identifier, "user_message_id": 1, "assistant_message_id": 2}
    saved = p.store.get(identifier, "owner", role="buyer")
    assert [item["message_id"] for item in saved.items] == [1, 2]
    assert saved.status == "running" and saved.items[-1]["pending"]
    assert p.agent.started.empty()
    recent = (
        await p.client.get(
            f"/api/buyer/conversations/{identifier}/messages", headers=headers("owner")
        )
    ).json()
    assert recent["status"] == "running" and recent["items"] == saved.items
    await stream.aclose()
    await response.background()
    saved = p.store.get(identifier, "owner", role="buyer")
    assert saved.status == "interrupted" and not saved.items[-1]["pending"]
    assert saved.items[-1]["message_id"] == 2
    assert saved.items[-1]["segments"][-1]["type"] == "error"
    assert p.agent.started.empty()
    p.agent.release.set()
    second = await p.client.post(
        f"/api/buyer/conversations/{identifier}/chat",
        json={"message": "second"},
        headers=headers("owner"),
    )
    assert second.status_code == 200
    frames = second.text.strip().split("\n\n")
    assert [frame.splitlines()[0] for frame in frames] == [
        "event: turn_started",
        "event: text_delta",
        "event: turn_complete",
    ]
    assert json.loads(frames[0].split("data: ", 1)[1]) == {
        "session_id": identifier,
        "user_message_id": 3,
        "assistant_message_id": 4,
    }
    saved = p.store.get(identifier, "owner", role="buyer")
    assert [item["message_id"] for item in saved.items] == [1, 2, 3, 4]
    assert saved.status == "completed" and saved.items[-1]["pending"] is False
