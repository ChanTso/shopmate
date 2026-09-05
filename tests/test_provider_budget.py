import asyncio

import httpx
import pytest

from shopmate.provider import Provider, TaskBudget, TaskBudgetExceeded, current_budget
from shopmate.settings import Settings


def test_one_counter_covers_main_and_delegate_and_rejects_before_extra_request():
    budget = TaskBudget(max_calls=2, timeout_s=10)
    budget.consume({"model": "main"})
    budget.consume({"model": "analysis"})
    with pytest.raises(TaskBudgetExceeded):
        budget.consume({"model": "main"})
    assert budget.calls == 2
    assert budget.stop_reason == "model_call_limit"


async def test_deadline_cancels_work_and_context_does_not_leak_between_turns():
    client = httpx.AsyncClient()
    provider = Provider(Settings(task_timeout_s=0.02), client=client)
    with pytest.raises(TimeoutError):
        async with provider.task_budget() as budget:
            assert current_budget() is budget
            await asyncio.sleep(1)
    assert budget.stop_reason == "task_deadline"
    with pytest.raises(RuntimeError):
        current_budget()
    async with provider.task_budget() as other:
        assert other.calls == 0
    await client.aclose()


def test_missing_usage_stays_unknown_while_reported_cached_tokens_are_counted_once():
    budget = TaskBudget(max_calls=3, timeout_s=10, calls=2)
    budget.observations = [
        {
            "usage_available": True,
            "usage": {"input_tokens": 80, "output_tokens": 3, "cache_read_input_tokens": 20},
        },
        {"usage_available": False, "completed": False},
    ]
    result = budget.summary()
    assert result["usage_complete"] is False
    assert result["calls_with_usage"] == 1
    assert result["known_input_tokens"] == 100
    assert result["known_cache_read_input_tokens"] == 20
