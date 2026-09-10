import importlib
import sqlite3
import sys
from pathlib import Path

from shopmate.sessions import SessionStore


def test_fixture_reset_backs_up_and_preserves_other_exact_owners(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    runtime = importlib.import_module("local_runtime")
    monkeypatch.setattr(runtime, "RUN", tmp_path)
    store = SessionStore(tmp_path / "sessions.sqlite3")
    own = store.create("shopmate-retail-buyer")
    other = store.create("Shopmate-retail-buyer")
    turn = store.begin_turn(own)
    intent = store.prepare_intent(
        own.session_id, turn, {"kind": "CAMPAIGN", "payload": {"name": "old"}}
    )
    store.attach_draft(intent.key, "change-1", {"state": "PREPARED"})
    store.finish_turn(own, "completed")
    store.close()
    runtime.reset_fixture_sessions()
    with sqlite3.connect(tmp_path / "sessions.sqlite3") as db:
        assert db.execute("SELECT id FROM sessions").fetchall() == [(other.session_id,)]
        assert db.execute("SELECT COUNT(*) FROM prepare_intents").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM draft_refs").fetchone()[0] == 0
    backup = next((tmp_path / "backups").glob("sessions-*.sqlite3"))
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 2
        assert db.execute("SELECT COUNT(*) FROM prepare_intents").fetchone()[0] == 1


async def test_retail_reset_removes_only_fixture_buyer_commands_and_memories(tmp_path, monkeypatch):
    from commerce_common.types import MemoryFact

    from shopmate.auth import RequestIdentity, bind_context
    from shopmate.buyer_commands import BuyerCommands
    from shopmate.memory import RetailMemoryStore

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    runtime = importlib.import_module("local_runtime")
    monkeypatch.setattr(runtime, "RUN", tmp_path)
    store = SessionStore(tmp_path / "sessions.sqlite3")
    commands, memory = BuyerCommands(store), RetailMemoryStore(store)
    records = [
        store.storefront(owner, role="buyer")
        for owner in ("shopmate-retail-buyer", "Shopmate-retail-buyer")
    ]
    for record in records:
        command = commands.register(
            session_id=record.session_id,
            owner=record.owner,
            turn_id="turn",
            call_id="call",
            kind="refund",
            operation="REFUND_REQUEST",
            arguments={"orderId": "order"},
            body={"orderId": "order"},
        )
        commands.complete(command, {"pendingActionId": "action-" + record.session_id})
        commands.confirm(command, {"status": "REQUESTED"})
        with bind_context(RequestIdentity(record.owner, "token"), record.session_id, role="buyer"):
            await memory.upsert_facts(
                record.owner, [MemoryFact(key="preference", value="cotton", category="preference")]
            )
    store.close()
    runtime.reset_fixture_sessions()
    with sqlite3.connect(tmp_path / "sessions.sqlite3") as db:
        assert db.execute("SELECT session_id FROM buyer_commands").fetchall() == [
            (records[1].session_id,)
        ]
        assert db.execute("SELECT COUNT(*) FROM buyer_confirmations").fetchone()[0] == 1
        assert db.execute("SELECT owner FROM memory_facts").fetchall() == [
            ("Shopmate-retail-buyer",)
        ]
        assert db.execute("SELECT owner FROM memory_generations").fetchall() == [
            ("Shopmate-retail-buyer",)
        ]


def test_command_diagnostics_do_not_pollute_returned_value(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    runtime = importlib.import_module("local_runtime")
    monkeypatch.setattr(runtime, "RUN", tmp_path)
    monkeypatch.setattr(runtime, "redactions", {"private-marker"})
    value = runtime.run(
        [
            sys.executable,
            "-c",
            "import sys; print('value'); print('diagnostic private-marker', file=sys.stderr)",
        ],
        cwd=tmp_path,
    )
    assert value == "value"
    log = (tmp_path / "runtime.log").read_text()
    assert "diagnostic [REDACTED]" in log
    assert "value" in log
    assert "private-marker" not in log
    before = log
    assert (
        runtime.run(
            [sys.executable, "-c", "import sys; print('secret'); print('detail', file=sys.stderr)"],
            cwd=tmp_path,
            log=False,
        )
        == "secret"
    )
    assert (tmp_path / "runtime.log").read_text() == before
