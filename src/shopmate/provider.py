"""One provider client, with a shared main/delegate budget for each user turn."""

from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

from .providers.chat_to_messages import make_client
from .settings import Settings, provider_credentials


class TaskBudgetExceeded(RuntimeError):
    pass


@dataclass
class TaskBudget:
    max_calls: int
    timeout_s: float
    started: float = field(default_factory=time.monotonic)
    calls: int = 0
    stop_reason: str | None = None
    observations: list[dict[str, Any]] = field(default_factory=list)

    def consume(self, request: dict[str, Any]) -> None:
        if time.monotonic() - self.started >= self.timeout_s:
            self.stop_reason = "task_deadline"
            raise TaskBudgetExceeded("Task deadline reached")
        if self.calls >= self.max_calls:
            self.stop_reason = "model_call_limit"
            raise TaskBudgetExceeded("Model call limit reached")
        self.calls += 1

    def summary(self) -> dict[str, Any]:
        known = [item["usage"] for item in self.observations if item.get("usage_available")]
        known_cache_read = [
            item["usage"]
            for item in self.observations
            if item.get("usage_available") is True
            and item.get("cache_read_usage_available") is True
        ]
        complete = len(known) == self.calls
        return {
            "model_calls": self.calls,
            "elapsed_ms": round((time.monotonic() - self.started) * 1000),
            "stop_reason": self.stop_reason,
            "usage_complete": complete,
            "calls_with_usage": len(known),
            "cache_read_usage_complete": len(known_cache_read) == self.calls,
            "calls_with_cache_read_usage": len(known_cache_read),
            "known_input_tokens": sum(
                u["input_tokens"] + u["cache_read_input_tokens"] for u in known
            ),
            "known_output_tokens": sum(u["output_tokens"] for u in known),
            "known_cache_read_input_tokens": sum(
                u["cache_read_input_tokens"] for u in known_cache_read
            ),
            "model_observations": [
                {key: value for key, value in item.items() if key != "_started"}
                for item in self.observations
            ],
        }


_budget: ContextVar[TaskBudget | None] = ContextVar("shopmate_task_budget", default=None)


def current_budget() -> TaskBudget:
    value = _budget.get()
    if value is None:
        raise RuntimeError("Model calls require an active user-turn budget")
    return value


class Provider:
    def __init__(self, settings: Settings, *, client=None) -> None:
        self.settings = settings
        if client is None:
            root, key = provider_credentials(settings.citybuddy_dir)
            self.client = make_client(
                root,
                key,
                timeout_s=min(120, settings.task_timeout_s),
                before_request=lambda request: current_budget().consume(request),
                observe=lambda item: current_budget().observations.append(item),
            )
        else:
            self.client = client

    @asynccontextmanager
    async def task_budget(self):
        budget = TaskBudget(self.settings.max_model_calls, self.settings.task_timeout_s)
        token = _budget.set(budget)
        try:
            async with asyncio.timeout(budget.timeout_s):
                yield budget
        except TimeoutError:
            budget.stop_reason = "task_deadline"
            raise
        finally:
            _budget.reset(token)

    async def close(self) -> None:
        await self.client.close()


def build_agent(settings: Settings, backend, provider: Provider):
    from merchant_agent_runtime import MerchantAgent

    from .backend import ShopMateConfig
    from .settings import ROOT

    config = ShopMateConfig(
        model=settings.model,
        analysis_model=settings.analysis_model,
        thinking_effort=None,
        request_timeout_s=min(120, settings.task_timeout_s),
        analysis_timeout_s=min(180, settings.task_timeout_s),
        max_analysis_rows=settings.sql_max_rows,
        max_analysis_table_chars=settings.sql_max_bytes,
        analysis_query_timeout_s=settings.sql_timeout_ms / 1000 + 1,
    )
    return MerchantAgent(
        backend=backend, config=config, client=provider.client, skills_dir=ROOT / "skills"
    )
