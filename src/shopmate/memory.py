"""Role and owner scoped memory on the host database, with revocation during model turns."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar

from commerce_common.memory import extract_and_store, match_facts
from commerce_common.turn import latest_exchange, transcript_text
from commerce_common.types import MemoryFact

from .auth import current_context
from .sessions import SessionStore

_generation: ContextVar[tuple[str, str, int] | None] = ContextVar(
    "shopmate_memory_generation", default=None
)


class MemoryChanged(RuntimeError):
    pass


class RetailMemoryStore:
    def __init__(self, sessions: SessionStore):
        self.db = sessions.db
        with self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS memory_facts (
                  role TEXT NOT NULL, owner TEXT NOT NULL, fact_key TEXT NOT NULL, fact TEXT NOT NULL,
                  PRIMARY KEY(role,owner,fact_key));
                CREATE TABLE IF NOT EXISTS memory_generations (
                  role TEXT NOT NULL, owner TEXT NOT NULL, generation INTEGER NOT NULL,
                  PRIMARY KEY(role,owner));
            """)

    @staticmethod
    def _identity(subject_id: str) -> tuple[str, str]:
        bound = current_context()
        expected = bound.identity.subject if bound.role == "buyer" else "citybuddy"
        if subject_id != expected:
            raise ValueError("Memory subject does not match authenticated role")
        return bound.role, bound.identity.subject

    def _generation(self, role: str, owner: str) -> int:
        row = self.db.execute(
            "SELECT generation FROM memory_generations WHERE role=? AND owner=?", (role, owner)
        ).fetchone()
        return row[0] if row else 0

    def _advance(self, role: str, owner: str):
        self.db.execute(
            """INSERT INTO memory_generations VALUES(?,?,1) ON CONFLICT(role,owner)
            DO UPDATE SET generation=generation+1""",
            (role, owner),
        )

    @contextmanager
    def turn(self):
        bound = current_context()
        role, owner = bound.role, bound.identity.subject
        token = _generation.set((role, owner, self._generation(role, owner)))
        try:
            yield
        finally:
            _generation.reset(token)

    async def get_facts(self, subject_id: str) -> list[MemoryFact]:
        role, owner = self._identity(subject_id)
        return [
            MemoryFact.model_validate_json(row[0])
            for row in self.db.execute(
                "SELECT fact FROM memory_facts WHERE role=? AND owner=? ORDER BY fact_key",
                (role, owner),
            )
        ]

    async def upsert_facts(self, subject_id: str, facts: list[MemoryFact]) -> None:
        role, owner = self._identity(subject_id)
        generation = _generation.get()
        # Synchronous SQLite mutation makes the check and write one event-loop operation.
        if generation is not None and generation != (role, owner, self._generation(role, owner)):
            raise MemoryChanged("Memory changed while this turn was running; no facts were saved")
        with self.db:
            if generation is None:
                self._advance(role, owner)
            self.db.executemany(
                """INSERT INTO memory_facts VALUES(?,?,?,?) ON CONFLICT(role,owner,fact_key)
                DO UPDATE SET fact=excluded.fact""",
                [(role, owner, fact.key, fact.model_dump_json()) for fact in facts],
            )

    async def search_facts(self, subject_id: str, query: str) -> list[MemoryFact]:
        return match_facts(await self.get_facts(subject_id), query)

    async def delete_fact(self, subject_id: str, key: str) -> bool:
        role, owner = self._identity(subject_id)
        with self.db:
            self._advance(role, owner)
            result = self.db.execute(
                "DELETE FROM memory_facts WHERE role=? AND owner=? AND fact_key=?",
                (role, owner, key),
            )
        return result.rowcount > 0

    async def clear(self, subject_id: str) -> None:
        role, owner = self._identity(subject_id)
        with self.db:
            self._advance(role, owner)
            self.db.execute("DELETE FROM memory_facts WHERE role=? AND owner=?", (role, owner))

    async def purge_generation(self, subject_id: str) -> int:
        return self._generation(*self._identity(subject_id))


async def extract_memory(agent, messages, session) -> str:
    """One bounded extraction under the active task budget; never log provider bodies."""
    from .provider import TaskBudgetExceeded

    memory = agent.memory
    if not memory.enabled:
        return "disabled"
    subject = session.user_id if hasattr(session, "user_id") else session.merchant_id
    transcript = transcript_text(latest_exchange(messages))
    if not transcript:
        return "unchanged"
    try:
        async with asyncio.timeout(20):
            facts = await extract_and_store(
                memory.store,
                subject,
                agent.client,
                memory.model,
                transcript,
                extraction_prompt=(
                    memory.extraction_prompt
                    + "\nThe saved fact value is displayed directly to the user. "
                    "Write it in the language of the user's statement; preserve product names "
                    "and keep the existing key/category schema."
                ),
                fence=memory.fence,
                write_filter=memory.write_filter,
                source_session_id=session.session_id,
            )
        return "saved" if facts else "unchanged"
    except TaskBudgetExceeded:
        raise
    except MemoryChanged:
        return "revoked"
    except Exception:  # noqa: BLE001 -- model boundary, no provider bodies in logs
        return "unavailable"
