import asyncio
import json
import sqlite3
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from commerce_common.streaming import ToolOutcome
from commerce_common.turn import EagerDispatcher, current_tool_call
from commerce_common.types import MemoryFact
from fastapi import HTTPException
from merchant_agent import MerchantSessionState
from shopping_agent import Product, ShoppingSessionState

from shopmate.auth import RequestIdentity, bind_context
from shopmate.buyer_commands import BuyerCommands
from shopmate.memory import MemoryChanged, RetailMemoryStore
from shopmate.sessions import SessionStore


def test_legacy_running_merchant_and_new_buyer_survive_same_database(tmp_path):
    path = tmp_path / "sessions.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE sessions(id TEXT PRIMARY KEY,owner TEXT,state TEXT,messages TEXT,items TEXT,status TEXT,updated_at TEXT,turn_id TEXT,version INTEGER)"
        )
        db.execute(
            "INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?)",
            (
                "old",
                "Owner",
                MerchantSessionState().model_dump_json(),
                "[]",
                json.dumps([{"kind": "assistant", "segments": [], "pending": True}]),
                "running",
                datetime.now(UTC).isoformat(),
                "legacy-turn",
                4,
            ),
        )
    store = SessionStore(path)
    old = store.get("old", "Owner")
    assert old.role == "merchant" and old.status == "interrupted" and old.version == 5
    buyer = store.create("Owner", role="buyer")
    buyer.state.remember_products(
        [Product(product_id="sku", title="Cup", price=24, currency="CNY")]
    )
    store.save(buyer)
    with pytest.raises(HTTPException):
        store.get(buyer.session_id, "Owner")
    with pytest.raises(HTTPException):
        store.get("old", "Owner", role="buyer")
    store.close()
    store = SessionStore(path)
    assert isinstance(
        store.get(buyer.session_id, "Owner", role="buyer").state, ShoppingSessionState
    )
    assert (
        store.get(buyer.session_id, "Owner", role="buyer").state.seen_products["sku"].currency
        == "CNY"
    )
    assert len(store.list("Owner")) == len(store.list("Owner", role="buyer")) == 1
    assert store.list("owner", role="buyer") == []
    store.close()


def register(commands, record, call="call", **changes):
    return commands.register(
        **{
            "session_id": record.session_id,
            "owner": record.owner,
            "turn_id": "turn",
            "call_id": call,
            "kind": "cart",
            "operation": "ADD",
            "arguments": {"product_id": "sku", "quantity": 3},
            "body": {"productId": "sku", "quantity": 2},
        }
        | changes
    )


def test_unknown_write_freezes_body_across_restart_and_blocks_other_account_session(tmp_path):
    path = tmp_path / "sessions.sqlite3"
    store = SessionStore(path)
    first = store.create("Owner", role="buyer")
    second = store.create("Owner", role="buyer")
    commands = BuyerCommands(store)
    command = register(commands, first)
    store.close()
    store = SessionStore(path)
    commands = BuyerCommands(store)
    replay = register(commands, first, body={"productId": "sku", "quantity": 0})
    assert replay.key == command.key and replay.body["quantity"] == 2
    with pytest.raises(HTTPException) as error:
        register(commands, second)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException):
        register(commands, first, arguments={"product_id": "sku", "quantity": 4})
    commands.complete(command, {"receipt": {"afterQuantity": 10}})
    commands.reject(command, "too_late")
    assert commands.get(command.key, first.session_id, first.owner).rejection is None
    assert register(commands, first, call="new-call").key != command.key
    store.close()


def test_ui_request_key_cannot_cross_owner_or_role(tmp_path):
    store = SessionStore(tmp_path / "sessions.sqlite3")
    commands = BuyerCommands(store)
    buyer = store.create("Owner", role="buyer")
    other = store.create("other", role="buyer")
    merchant = store.create("Owner")
    command = register(commands, buyer, key="ui/?# key")
    for record in (other, merchant):
        with pytest.raises(HTTPException):
            commands.get(command.key, record.session_id, record.owner)
    with pytest.raises(HTTPException):
        register(commands, other, key=command.key)
    store.close()


@pytest.mark.parametrize("eager", [False, True])
async def test_actual_dispatch_preserves_parallel_tool_ids_and_cleans_context(eager):
    entered = []
    release = asyncio.Event()

    async def execute(name, arguments):
        entered.append(current_tool_call.get())
        if len(entered) == 2:
            release.set()
        await release.wait()
        assert current_tool_call.get().arguments == arguments
        return ToolOutcome(current_tool_call.get().tool_use_id)

    dispatcher = EagerDispatcher(execute, eager)
    blocks = [SimpleNamespace(id=f"id-{i}", name="cart", input={"quantity": i}) for i in (1, 2)]
    for block in blocks:
        dispatcher.dispatch(block.name, block.id, block.input)
    outcomes = await dispatcher.collect(blocks)
    assert [o.result_text for o in outcomes] == ["id-1", "id-2"]
    assert {v.tool_use_id for v in entered} == {"id-1", "id-2"}
    with pytest.raises(LookupError):
        current_tool_call.get()


@pytest.mark.parametrize("edit", [False, True])
async def test_user_memory_revision_invalidates_older_turn_write_and_isolates_roles(tmp_path, edit):
    path = tmp_path / "sessions.sqlite3"
    store = SessionStore(path)
    memory = RetailMemoryStore(store)
    user = RequestIdentity("Owner", "private-token")
    fact = MemoryFact(key="material", value="cotton", category="preference")
    old_ready, edited = asyncio.Event(), asyncio.Event()

    async def old_turn():
        with bind_context(user, "buyer-session", role="buyer"), memory.turn():
            old_ready.set()
            await edited.wait()
            with pytest.raises(MemoryChanged):
                await memory.upsert_facts("Owner", [fact])

    with bind_context(user, "buyer-session", role="buyer"):
        await memory.upsert_facts("Owner", [fact])
    task = asyncio.create_task(old_turn())
    await old_ready.wait()
    with bind_context(user, "buyer-session", role="buyer"):
        if edit:
            await memory.upsert_facts("Owner", [fact.model_copy(update={"value": "wool"})])
        else:
            await memory.delete_fact("Owner", "material")
    edited.set()
    await task
    with bind_context(user, "merchant-session"):
        assert await memory.get_facts("citybuddy") == []
    with bind_context(RequestIdentity("owner", "token"), "other", role="buyer"):
        assert await memory.get_facts("owner") == []
    store.close()
    store = SessionStore(path)
    with bind_context(user, "buyer-session", role="buyer"):
        facts = await RetailMemoryStore(store).get_facts("Owner")
        assert [f.value for f in facts] == (["wool"] if edit else [])
    store.close()


def test_legacy_binding_migration_retains_commands_confirmations_and_prepares(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as db:
        db.executescript("""
            PRAGMA foreign_keys=ON;
            CREATE TABLE sessions (
                id TEXT PRIMARY KEY, owner TEXT NOT NULL, state TEXT NOT NULL,
                messages TEXT NOT NULL, items TEXT NOT NULL, status TEXT NOT NULL,
                updated_at TEXT NOT NULL, turn_id TEXT, version INTEGER NOT NULL, role TEXT NOT NULL);
            CREATE TABLE buyer_commands (
                request_key TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                turn_id TEXT NOT NULL, call_id TEXT NOT NULL, kind TEXT NOT NULL,
                operation TEXT NOT NULL, arguments TEXT NOT NULL, body TEXT NOT NULL,
                result TEXT, rejection TEXT, created_at TEXT NOT NULL,
                UNIQUE(session_id,turn_id,call_id));
            CREATE TABLE buyer_confirmations (
                request_key TEXT PRIMARY KEY REFERENCES buyer_commands(request_key),
                receipt TEXT NOT NULL);
            CREATE TABLE prepare_intents (
                request_key TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
                turn_id TEXT NOT NULL, intent_hash TEXT NOT NULL, body TEXT NOT NULL,
                draft_id TEXT, rejection TEXT, UNIQUE(session_id,turn_id,intent_hash));
            CREATE TABLE draft_refs (
                session_id TEXT NOT NULL REFERENCES sessions(id), draft_id TEXT NOT NULL,
                receipt TEXT NOT NULL, PRIMARY KEY(session_id,draft_id));
        """)
        for identifier, role in (("shop-legacy", "buyer"), ("merchant-legacy", "merchant")):
            db.execute(
                "INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    "owner",
                    "{}",
                    "[]",
                    "[]",
                    "idle",
                    "2026-09-01",
                    None,
                    0,
                    role,
                ),
            )
        body = '{"trace_id":"original-trace","action_turn_id":"original-turn","request":{}}'
        db.execute(
            "INSERT INTO buyer_commands VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (
                "refund-key",
                "shop-legacy",
                "t",
                "c",
                "refund",
                "REFUND_REQUEST",
                "{}",
                body,
                '{"pendingActionId":"action-1"}',
                None,
                "2026-09-01",
            ),
        )
        db.execute(
            "INSERT INTO buyer_confirmations VALUES(?,?)", ("refund-key", '{"receiptId":"r1"}')
        )
        db.execute(
            "INSERT INTO prepare_intents VALUES(?,?,?,?,?,?,?)",
            (
                "prepare-key",
                "merchant-legacy",
                "t",
                "hash",
                '{"items":[]}',
                "draft-1",
                None,
            ),
        )
        db.execute("INSERT INTO draft_refs VALUES(?,?,?)", ("merchant-legacy", "draft-1", "{}"))
    for _ in range(2):
        store = SessionStore(path)
        commands = BuyerCommands(store)
        binding = store.storefront("owner", role="buyer")
        saved = commands.get("refund-key", binding.session_id, "owner")
        assert saved.session_id == "shop-legacy" and saved.body["trace_id"] == "original-trace"
        assert saved.source_conversation == "shop-legacy"
        assert commands.confirmation(saved) == {"receiptId": "r1"}
        assert commands.list(binding.session_id, "owner", kind="refund") == [saved]
        assert store.get("shop-legacy", "owner", role="buyer").authorization_id == "shop-legacy"
        assert store.intent_rows("merchant-legacy")[0].key == "prepare-key"
        assert store.draft_binding("owner", "draft-1") == "merchant-legacy"
        assert store.draft_binding("other", "draft-1") is None
        assert not store.db.execute("PRAGMA foreign_key_check").fetchall()
        assert store.db.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert store.db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2
        store.close()
