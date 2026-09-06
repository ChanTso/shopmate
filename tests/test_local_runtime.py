import importlib
import sqlite3
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
