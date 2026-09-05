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
