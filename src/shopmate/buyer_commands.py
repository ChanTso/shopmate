"""Durable buyer commands registered before Java writes; receipts remain Java truth."""

from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from typing import Literal

from fastapi import HTTPException

from .sessions import SessionStore, dump, now


@dataclass(frozen=True)
class BuyerCommand:
    key: str
    session_id: str
    turn_id: str
    call_id: str
    kind: str
    operation: str
    arguments: dict
    body: dict
    result: dict | None
    rejection: str | None
    created_at: str

    def public(self) -> dict:
        return {
            "request_key": self.key,
            "session_id": self.session_id,
            "kind": self.kind,
            "operation": self.operation,
            "body": self.body,
            "state": "confirmed"
            if self.result is not None
            else "rejected"
            if self.rejection
            else "unknown",
            "result": self.result,
            "rejection": self.rejection,
            "created_at": self.created_at,
        }


class BuyerCommands:
    def __init__(self, sessions: SessionStore):
        self.sessions = sessions
        self.db = sessions.db
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS buyer_commands (
                  request_key TEXT PRIMARY KEY,
                  session_id TEXT NOT NULL REFERENCES sessions(id),
                  turn_id TEXT NOT NULL, call_id TEXT NOT NULL,
                  kind TEXT NOT NULL CHECK(kind IN ('cart','checkout','refund')),
                  operation TEXT NOT NULL, arguments TEXT NOT NULL, body TEXT NOT NULL,
                  result TEXT, rejection TEXT, created_at TEXT NOT NULL,
                  UNIQUE(session_id,turn_id,call_id));
                CREATE TABLE IF NOT EXISTS buyer_confirmations (
                  request_key TEXT PRIMARY KEY REFERENCES buyer_commands(request_key),
                  receipt TEXT NOT NULL);
            """)

    @staticmethod
    def _record(row) -> BuyerCommand:
        return BuyerCommand(
            row["request_key"],
            row["session_id"],
            row["turn_id"],
            row["call_id"],
            row["kind"],
            row["operation"],
            json.loads(row["arguments"]),
            json.loads(row["body"]),
            json.loads(row["result"]) if row["result"] is not None else None,
            row["rejection"],
            row["created_at"],
        )

    def by_call(
        self, session_id: str, owner: str, turn_id: str, call_id: str
    ) -> BuyerCommand | None:
        self.sessions.get(session_id, owner, role="buyer")
        row = self.db.execute(
            "SELECT * FROM buyer_commands WHERE session_id=? AND turn_id=? AND call_id=?",
            (session_id, turn_id, call_id),
        ).fetchone()
        return self._record(row) if row else None

    def get(self, key: str, session_id: str, owner: str) -> BuyerCommand:
        self.sessions.get(session_id, owner, role="buyer")
        row = self.db.execute(
            "SELECT * FROM buyer_commands WHERE request_key=? AND session_id=?", (key, session_id)
        ).fetchone()
        if row is None:
            raise HTTPException(404, "Buyer command not found")
        return self._record(row)

    def register(
        self,
        *,
        session_id: str,
        owner: str,
        turn_id: str,
        call_id: str,
        kind: Literal["cart", "checkout", "refund"],
        operation: str,
        arguments: dict,
        body: dict,
        key: str | None = None,
    ) -> BuyerCommand:
        self.sessions.get(session_id, owner, role="buyer")
        existing = self.by_call(session_id, owner, turn_id, call_id)
        if existing:
            self.require_same_call(existing, kind, operation, arguments)
            return existing
        key = key or secrets.token_urlsafe(24)
        other = self.db.execute(
            "SELECT session_id FROM buyer_commands WHERE request_key=?", (key,)
        ).fetchone()
        if other:
            if other["session_id"] != session_id:
                raise HTTPException(409, "Request key already used")
            existing = self.get(key, session_id, owner)
            self.require_same_call(existing, kind, operation, arguments)
            return existing
        if kind == "cart" and self.unknown_cart(owner):
            raise HTTPException(
                409,
                "A previous cart operation is unconfirmed; check or retry its original command first",
            )
        with self.db:
            self.db.execute(
                """INSERT INTO buyer_commands
                (request_key,session_id,turn_id,call_id,kind,operation,arguments,body,created_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    key,
                    session_id,
                    turn_id,
                    call_id,
                    kind,
                    operation,
                    dump(arguments),
                    dump(body),
                    now(),
                ),
            )
        return self.get(key, session_id, owner)

    @staticmethod
    def require_same_call(command: BuyerCommand, kind: str, operation: str, arguments: dict):
        if (command.kind, command.operation, dump(command.arguments)) != (
            kind,
            operation,
            dump(arguments),
        ):
            raise HTTPException(409, "Request key or tool call reused with different arguments")

    def complete(self, command: BuyerCommand, result: dict):
        with self.db:
            self.db.execute(
                "UPDATE buyer_commands SET result=?,rejection=NULL WHERE request_key=?",
                (dump(result), command.key),
            )

    def reject(self, command: BuyerCommand, category: str):
        # Only a definitive refusal from Java may settle a write without a receipt.
        with self.db:
            self.db.execute(
                "UPDATE buyer_commands SET rejection=? WHERE request_key=? AND result IS NULL",
                (category, command.key),
            )

    def list(self, session_id: str, owner: str, *, kind: str | None = None) -> list[BuyerCommand]:
        self.sessions.get(session_id, owner, role="buyer")
        rows = self.db.execute(
            """SELECT * FROM buyer_commands WHERE session_id=? AND (? IS NULL OR kind=?)
            ORDER BY created_at DESC""",
            (session_id, kind, kind),
        ).fetchall()
        return [self._record(row) for row in rows]

    def unknown_cart(self, owner: str) -> list[BuyerCommand]:
        rows = self.db.execute(
            """SELECT c.* FROM buyer_commands c JOIN sessions s ON s.id=c.session_id
            WHERE s.owner=? AND s.role='buyer' AND c.kind='cart'
            AND c.result IS NULL AND c.rejection IS NULL ORDER BY c.created_at""",
            (owner,),
        ).fetchall()
        return [self._record(row) for row in rows]

    def confirmation(self, command: BuyerCommand) -> dict | None:
        row = self.db.execute(
            "SELECT receipt FROM buyer_confirmations WHERE request_key=?", (command.key,)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def confirm(self, command: BuyerCommand, receipt: dict):
        with self.db:
            self.db.execute(
                """INSERT INTO buyer_confirmations VALUES(?,?)
                ON CONFLICT(request_key) DO UPDATE SET receipt=excluded.receipt""",
                (command.key, dump(receipt)),
            )
