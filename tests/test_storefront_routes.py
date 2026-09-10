import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace

import httpx
import pytest
from commerce_common.streaming import AgentEvent

from shopmate.app import create_app
from shopmate.auth import RequestIdentity, current_context
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
        yield SimpleNamespace(client=client, store=store, agent=agent)
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
