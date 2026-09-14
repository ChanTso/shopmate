import json
import sqlite3

import pytest
from fastapi import HTTPException
from merchant_agent import Listing

from shopmate.sessions import SessionStore


def test_restart_preserves_provenance_history_and_ui_atomically(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = SessionStore(path)
    record = store.create("Owner")
    record.messages = [{"role": "user", "content": "read the mug"}]
    record.items = [{"kind": "user", "text": "read the mug"}]
    record.state.seen_listings["mug"] = Listing(
        listing_id="mug", title="Mug", status="active", price=3, stock=2
    )
    store.save(record)
    store.close()
    store = SessionStore(path)
    restored = store.get(record.session_id, "Owner")
    assert restored.messages == record.messages and restored.items == record.items
    assert restored.state.seen_listings["mug"].title == "Mug"
    with pytest.raises(HTTPException) as failure:
        store.get(record.session_id, "owner")
    assert failure.value.status_code == 404
    assert store.list("other") == []


def test_prepare_intent_survives_lost_response_and_canonical_item_order(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = SessionStore(path)
    record = store.create("owner")
    turn = store.begin_turn(record)
    body = {
        "currency": "CNY",
        "items": [
            {"productId": "b", "newPriceMinor": 200},
            {"productId": "a", "newPriceMinor": 100},
        ],
    }
    first = store.prepare_intent(record.session_id, turn, body)
    store.close()
    store = SessionStore(path)
    second = store.prepare_intent(
        record.session_id, turn, body | {"items": list(reversed(body["items"]))}
    )
    assert second == first
    assert second.draft_id is None
    store.attach_draft(first.key, "draft", {"state": "PREPARED"})
    assert store.draft_ids(record.session_id) == ["draft"]
    assert store.intent_rows(record.session_id)[0].draft_id == "draft"
    assert store.prepare_intent(record.session_id, "next-turn", body).key != first.key


def test_running_turn_becomes_interrupted_without_losing_ui(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = SessionStore(path)
    record = store.create("owner")
    record.items = [{"kind": "assistant", "segments": [], "pending": True}]
    store.begin_turn(record)
    store.close()
    store = SessionStore(path)
    recovered = store.get(record.session_id, "owner")
    assert recovered.status == "interrupted"
    assert recovered.items[-1]["pending"] is False
    assert recovered.items[-1]["segments"][-1]["type"] == "error"


def test_stale_writer_cannot_overwrite_history(tmp_path):
    store = SessionStore(tmp_path / "state.sqlite3")
    record = store.create("owner")
    stale = store.get(record.session_id, "owner")
    record.messages = [{"role": "user", "content": "winner"}]
    store.save(record)
    stale.items = [{"kind": "user", "text": "loser"}]
    with pytest.raises(HTTPException):
        store.save(stale)
    assert store.get(record.session_id, "owner").messages == record.messages
    assert store.get(record.session_id, "owner").items == []


def test_confirmed_prepare_refusal_survives_restart_without_rejecting_uncertain_requests(tmp_path):
    path = tmp_path / "state.sqlite3"
    store = SessionStore(path)
    record = store.create("owner")
    body = {"currency": "CNY", "items": [{"productId": "missing", "newPriceMinor": 100}]}
    refused = store.prepare_intent(record.session_id, "turn-one", body)
    uncertain = store.prepare_intent(record.session_id, "turn-two", body)
    store.reject_intent(refused.key, "NOT_FOUND")
    store.close()
    store = SessionStore(path)
    same = store.prepare_intent(record.session_id, "turn-one", body)
    assert same.key == refused.key and same.rejection == "NOT_FOUND"
    restored = {intent.key: intent for intent in store.intent_rows(record.session_id)}
    assert restored[uncertain.key].rejection is None
    assert restored[uncertain.key].draft_id is None
    new_request = store.prepare_intent(record.session_id, "turn-three", body)
    assert new_request.rejection is None and new_request.key != refused.key
    store.close()


def test_committed_prepare_response_takes_precedence_over_concurrent_refusal(tmp_path):
    store = SessionStore(tmp_path / "state.sqlite3")
    record = store.create("owner")
    body = {"currency": "CNY", "items": [{"productId": "mug", "newPriceMinor": 100}]}
    intent = store.prepare_intent(record.session_id, "turn", body)
    store.reject_intent(intent.key, "NOT_FOUND")
    store.attach_draft(intent.key, "draft", {"state": "PREPARED"})
    store.reject_intent(intent.key, "NOT_FOUND")
    recovered = store.prepare_intent(record.session_id, "turn", body)
    assert recovered.draft_id == "draft" and recovered.rejection is None
    assert store.draft_ids(record.session_id) == ["draft"]
    store.close()


def test_buyer_history_migration_preserves_content_ids_and_merchant_items(tmp_path):
    path = tmp_path / "history.sqlite3"
    store = SessionStore(path)
    buyer = store.create("owner", role="buyer")
    merchant = store.create("owner")
    legacy = [
        {"kind": "user", "text": "compare"},
        {
            "kind": "assistant",
            "turn": 1,
            "pending": False,
            "segments": [
                {"type": "text", "text": "A preserved answer"},
                {
                    "type": "ui",
                    "slotKey": "1:card",
                    "status": "final",
                    "block": {"component": "products", "payload": {"products": []}},
                },
            ],
        },
    ]
    raw = json.dumps(legacy, indent=2)
    with store.db:
        store.db.execute(
            "UPDATE sessions SET items=? WHERE id IN (?,?)",
            (raw, buyer.session_id, merchant.session_id),
        )
    store.close()

    for _ in range(2):
        store = SessionStore(path)
        restored = store.get(buyer.session_id, "owner", role="buyer")
        assert restored.items == [item | {"message_id": i} for i, item in enumerate(legacy, 1)]
        assert restored.version == 0
        assert (
            store.db.execute(
                "SELECT items FROM sessions WHERE id=?", (merchant.session_id,)
            ).fetchone()[0]
            == raw
        )
        store.close()


def test_assigned_buyer_ids_survive_interruption_and_stale_cas(tmp_path):
    path = tmp_path / "history.sqlite3"
    store = SessionStore(path)
    record = store.create("owner", role="buyer")
    record.items = [
        {"message_id": 11, "kind": "user", "text": "continue"},
        {"message_id": 12, "kind": "assistant", "segments": [], "pending": True},
    ]
    store.begin_turn(record)
    store.close()
    store = SessionStore(path)
    try:
        restored = store.get(record.session_id, "owner", role="buyer")
        assert restored.status == "interrupted"
        assert [item["message_id"] for item in restored.items] == [11, 12]
        assert restored.items[-1]["segments"][-1]["type"] == "error"
        assert restored.items[-1]["pending"] is False
        stale = store.get(record.session_id, "owner", role="buyer")
        restored.items.extend(
            [
                {"message_id": 13, "kind": "user", "text": "next"},
                {"message_id": 14, "kind": "assistant", "segments": [], "pending": True},
            ]
        )
        store.begin_turn(restored)
        with pytest.raises(HTTPException) as failure:
            store.save(stale)
        assert failure.value.status_code == 409
        assert [
            item["message_id"] for item in store.get(record.session_id, "owner", role="buyer").items
        ] == [11, 12, 13, 14]
    finally:
        store.close()


@pytest.mark.parametrize("identities", [[1, 1], [1, None]])
def test_migration_does_not_renumber_invalid_assigned_buyer_identity(tmp_path, identities):
    path = tmp_path / "history.sqlite3"
    store = SessionStore(path)
    record = store.create("owner", role="buyer")
    raw = json.dumps(
        [{"kind": "user", "text": "saved", "message_id": value} for value in identities]
    )
    with store.db:
        store.db.execute("UPDATE sessions SET items=? WHERE id=?", (raw, record.session_id))
    store.close()
    with pytest.raises(sqlite3.IntegrityError, match="message identity"):
        SessionStore(path)
    with sqlite3.connect(path) as db:
        assert (
            db.execute("SELECT items FROM sessions WHERE id=?", (record.session_id,)).fetchone()[0]
            == raw
        )
