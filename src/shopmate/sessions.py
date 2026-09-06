"""Single-process session persistence; Java remains authoritative for price drafts."""

from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from fastapi import HTTPException
from merchant_agent import MerchantSessionState
from shopping_agent import ShoppingSessionState


def now() -> str:
    return datetime.now(UTC).isoformat()


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


@dataclass
class SessionRecord:
    session_id: str
    owner: str
    state: MerchantSessionState | ShoppingSessionState = field(default_factory=MerchantSessionState)
    messages: list[dict] = field(default_factory=list)
    items: list[dict] = field(default_factory=list)
    status: str = "idle"
    updated_at: str = field(default_factory=now)
    turn_id: str | None = None
    version: int = 0
    role: Literal["merchant", "buyer"] = "merchant"


@dataclass(frozen=True)
class PrepareIntent:
    key: str
    body: dict
    draft_id: str | None
    rejection: str | None = None


class SessionStore:
    def __init__(self, path: str | Path):
        path = str(path)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
              id TEXT PRIMARY KEY, owner TEXT NOT NULL, state TEXT NOT NULL,
              messages TEXT NOT NULL, items TEXT NOT NULL, status TEXT NOT NULL,
              updated_at TEXT NOT NULL, turn_id TEXT, version INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS prepare_intents (
              request_key TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(id),
              turn_id TEXT NOT NULL, intent_hash TEXT NOT NULL, body TEXT NOT NULL, draft_id TEXT,
              rejection TEXT, UNIQUE(session_id,turn_id,intent_hash));
            CREATE TABLE IF NOT EXISTS draft_refs (
              session_id TEXT NOT NULL REFERENCES sessions(id), draft_id TEXT NOT NULL,
              receipt TEXT NOT NULL, PRIMARY KEY(session_id,draft_id));
        """)
        columns = {row["name"] for row in self.db.execute("PRAGMA table_info(prepare_intents)")}
        if "rejection" not in columns:
            with self.db:
                self.db.execute("ALTER TABLE prepare_intents ADD COLUMN rejection TEXT")
        session_columns = {row["name"] for row in self.db.execute("PRAGMA table_info(sessions)")}
        if "role" not in session_columns:
            with self.db:
                self.db.execute(
                    "ALTER TABLE sessions ADD COLUMN role TEXT NOT NULL DEFAULT 'merchant'"
                )
        # A restarted process cannot resume an in-flight model stream.
        with self.db:
            rows = self.db.execute("SELECT * FROM sessions WHERE status='running'").fetchall()
            for row in rows:
                record = self._record(row)
                self._terminate_ui(record, "The previous turn was interrupted. You can continue.")
                self.finish_turn(record, "interrupted")

    def close(self):
        self.db.close()

    def _record(self, row) -> SessionRecord:
        state_type = {"merchant": MerchantSessionState, "buyer": ShoppingSessionState}[row["role"]]
        return SessionRecord(
            row["id"],
            row["owner"],
            state_type.model_validate_json(row["state"]),
            json.loads(row["messages"]),
            json.loads(row["items"]),
            row["status"],
            row["updated_at"],
            row["turn_id"],
            row["version"],
            row["role"],
        )

    def create(
        self, owner: str, *, role: Literal["merchant", "buyer"] = "merchant"
    ) -> SessionRecord:
        state_type = {"merchant": MerchantSessionState, "buyer": ShoppingSessionState}[role]
        session_id = "shop-" + str(uuid4()) if role == "buyer" else secrets.token_urlsafe(24)
        record = SessionRecord(session_id, owner, state=state_type(), role=role)
        with self.db:
            self.db.execute(
                """INSERT INTO sessions
                (id,owner,state,messages,items,status,updated_at,turn_id,version,role)
                VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    record.session_id,
                    owner,
                    record.state.model_dump_json(),
                    "[]",
                    "[]",
                    record.status,
                    record.updated_at,
                    None,
                    0,
                    role,
                ),
            )
        return record

    def get(self, session_id: str, owner: str, *, role: str = "merchant") -> SessionRecord:
        row = self.db.execute(
            "SELECT * FROM sessions WHERE id=? AND owner=? AND role=?", (session_id, owner, role)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Session not found")
        return self._record(row)

    def list(self, owner: str, *, role: str = "merchant") -> list[dict]:
        rows = self.db.execute(
            "SELECT * FROM sessions WHERE owner=? AND role=? ORDER BY updated_at DESC",
            (owner, role),
        ).fetchall()
        return [
            {
                "session_id": row["id"],
                "operator": row["owner"],
                "updated_at": row["updated_at"],
                "status": row["status"],
                "title": next(
                    (
                        i.get("text", "")[:60]
                        for i in json.loads(row["items"])
                        if i.get("kind") == "user"
                    ),
                    "New conversation",
                ),
            }
            for row in rows
        ]

    def save(self, record: SessionRecord):
        record.updated_at = now()
        with self.db:
            result = self.db.execute(
                """UPDATE sessions SET state=?,messages=?,items=?,status=?,updated_at=?,
                turn_id=?,version=version+1 WHERE id=? AND owner=? AND version=? AND role=?""",
                (
                    record.state.model_dump_json(),
                    dump(record.messages),
                    dump(record.items),
                    record.status,
                    record.updated_at,
                    record.turn_id,
                    record.session_id,
                    record.owner,
                    record.version,
                    record.role,
                ),
            )
            if result.rowcount != 1:
                raise HTTPException(409, "Session changed; reload it")
        record.version += 1

    def begin_turn(self, record: SessionRecord) -> str:
        if record.status == "running":
            raise HTTPException(409, "Session is busy")
        record.status, record.turn_id = "running", str(uuid4())
        self.save(record)
        return record.turn_id

    def finish_turn(self, record: SessionRecord, status: str):
        record.status = status
        if record.items and record.items[-1].get("kind") == "assistant":
            record.items[-1]["pending"] = False
            record.items[-1].pop("activity", None)
        self.save(record)

    @staticmethod
    def _terminate_ui(record: SessionRecord, message: str):
        if record.items and record.items[-1].get("kind") == "assistant":
            record.items[-1]["segments"].append({"type": "error", "text": message})
            record.items[-1]["pending"] = False

    def prepare_intent(self, session_id: str, turn_id: str, body: dict) -> PrepareIntent:
        canonical = dict(body)
        if isinstance(canonical.get("items"), list):
            canonical["items"] = sorted(canonical["items"], key=lambda item: item["productId"])
        encoded = dump(canonical)
        digest = hashlib.sha256(encoded.encode()).hexdigest()
        with self.db:
            self.db.execute(
                """INSERT OR IGNORE INTO prepare_intents
                (request_key,session_id,turn_id,intent_hash,body) VALUES(?,?,?,?,?)""",
                (secrets.token_urlsafe(24), session_id, turn_id, digest, encoded),
            )
        row = self.db.execute(
            "SELECT * FROM prepare_intents WHERE session_id=? AND turn_id=? AND intent_hash=?",
            (session_id, turn_id, digest),
        ).fetchone()
        return PrepareIntent(
            row["request_key"], json.loads(row["body"]), row["draft_id"], row["rejection"]
        )

    def reject_intent(self, intent_key: str, category: str):
        """Record only a confirmed business refusal, supplied by the Java client boundary."""
        with self.db:
            # A committed Java result takes precedence over another request's earlier refusal.
            self.db.execute(
                "UPDATE prepare_intents SET rejection=? WHERE request_key=? AND draft_id IS NULL",
                (category, intent_key),
            )

    def attach_draft(self, intent_key: str, draft_id: str, receipt: dict):
        with self.db:
            row = self.db.execute(
                "SELECT session_id,draft_id FROM prepare_intents WHERE request_key=?", (intent_key,)
            ).fetchone()
            if row is None or row["draft_id"] not in (None, draft_id):
                raise ValueError("Prepare intent does not match draft")
            self.db.execute(
                "UPDATE prepare_intents SET draft_id=?,rejection=NULL WHERE request_key=?",
                (draft_id, intent_key),
            )
            self.db.execute(
                "INSERT INTO draft_refs VALUES(?,?,?) ON CONFLICT(session_id,draft_id) DO UPDATE SET receipt=excluded.receipt",
                (row["session_id"], draft_id, dump(receipt)),
            )

    def remember_draft(self, session_id: str, draft_id: str, receipt: dict):
        with self.db:
            self.db.execute(
                "INSERT INTO draft_refs VALUES(?,?,?) ON CONFLICT(session_id,draft_id) DO UPDATE SET receipt=excluded.receipt",
                (session_id, draft_id, dump(receipt)),
            )

    def draft_ids(self, session_id: str) -> list[str]:
        return [
            r[0]
            for r in self.db.execute(
                "SELECT draft_id FROM draft_refs WHERE session_id=?", (session_id,)
            )
        ]

    def owns_draft(self, session_id: str, draft_id: str) -> bool:
        return (
            self.db.execute(
                "SELECT 1 FROM draft_refs WHERE session_id=? AND draft_id=?", (session_id, draft_id)
            ).fetchone()
            is not None
        )

    def intent_rows(self, session_id: str) -> list[PrepareIntent]:
        return [
            PrepareIntent(r["request_key"], json.loads(r["body"]), r["draft_id"], r["rejection"])
            for r in self.db.execute(
                "SELECT * FROM prepare_intents WHERE session_id=?", (session_id,)
            )
        ]
