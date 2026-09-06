import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest
from commerce_common.streaming import ToolOutcome

from shopmate.provider import Provider, TaskBudgetExceeded
from shopmate.search_tool import execute_search
from shopmate.settings import Settings
from shopmate.web_search import ResponsesWebSearch, SearchUnavailable


def answer(*, citations=True, usage=True, sources=None):
    result = {
        "status": "completed",
        "output": [
            {
                "type": "web_search_call",
                "status": "completed",
                "action": {"type": "search", "sources": sources or []},
            },
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Source finding.",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "url": "https://example.org/article",
                                "title": "Research",
                                "start_index": 0,
                                "end_index": 15,
                            }
                        ]
                        if citations
                        else [],
                    }
                ],
            },
        ],
    }
    if usage:
        result["usage"] = {
            "input_tokens": 100,
            "input_tokens_details": {"cached_tokens": 30},
            "output_tokens": 20,
        }
    return result


class MainClient:
    async def close(self):
        pass


@pytest.mark.parametrize("root", ["https://provider.test", "https://provider.test/v1/"])
async def test_cited_search_uses_shared_budget_and_counts_actual_cache_once(root):
    requests = []

    async def upstream(request):
        requests.append(request)
        return httpx.Response(200, json=answer())

    search = ResponsesWebSearch(
        root, "private-key", model="search-model", transport=httpx.MockTransport(upstream)
    )
    provider = Provider(Settings(max_model_calls=3), client=MainClient(), web_search=search)
    try:
        async with provider.task_budget() as budget:
            result = await search.search("public product research")
            assert result["citations"] == [
                {"url": "https://example.org/article", "title": "Research"}
            ]
            assert result["consulted_sources"] == [] and result["sources_available"]
            assert result["summary"].endswith("[1]")
            summary = budget.summary()
            assert summary["model_calls"] == 1 and summary["known_input_tokens"] == 100
            assert summary["known_cache_read_input_tokens"] == 30
            assert summary["known_output_tokens"] == 20 and summary["usage_complete"]
            assert summary["model_observations"][0]["protocol"] == "responses"
        assert requests[0].url.path == "/v1/responses"
        sent = json.loads(requests[0].content)
        assert sent["store"] is False and sent["input"] == "public product research"
        assert sent["tools"] == [{"type": "web_search"}]
        assert "max_tool_calls" not in sent
        assert sent["include"] == ["web_search_call.action.sources"]
        assert "private-key" not in json.dumps(result)
    finally:
        await provider.close()


async def test_parallel_last_model_budget_allows_only_one_search_request():
    requests = []

    async def upstream(request):
        requests.append(request)
        await asyncio.sleep(0)
        return httpx.Response(200, json=answer())

    search = ResponsesWebSearch(
        "https://provider.test", "key", model="test", transport=httpx.MockTransport(upstream)
    )
    provider = Provider(Settings(max_model_calls=2), client=MainClient(), web_search=search)
    try:
        async with provider.task_budget() as budget:
            budget.consume({"model": "main"})
            results = await asyncio.gather(
                search.search("one"), search.search("two"), return_exceptions=True
            )
            assert len(requests) == 1 and budget.calls == 2
            assert sum(isinstance(r, TaskBudgetExceeded) for r in results) == 1
            assert budget.stop_reason == "model_call_limit"
    finally:
        await provider.close()


@pytest.mark.parametrize("failure", [429, 503, "incomplete", "bad_json", "oversized"])
async def test_provider_failures_are_bounded_without_exposing_response_or_credentials(failure):
    def upstream(_):
        if isinstance(failure, int):
            return httpx.Response(failure, text="private-provider-diagnostics")
        if failure == "bad_json":
            return httpx.Response(200, text="private-provider-diagnostics")
        if failure == "oversized":
            return httpx.Response(200, content=b"x" * 1_000_001)
        result = answer()
        result["status"] = "incomplete"
        return httpx.Response(200, json=result)

    search = ResponsesWebSearch(
        "https://provider.test", "key", model="test", transport=httpx.MockTransport(upstream)
    )
    provider = Provider(Settings(), client=MainClient(), web_search=search)
    try:
        async with provider.task_budget() as budget:
            with pytest.raises(SearchUnavailable) as failure_info:
                await search.search("public query")
            assert "private-provider-diagnostics" not in str(failure_info.value)
            assert budget.calls == 1 and not budget.observations[0]["completed"]
    finally:
        await provider.close()


async def test_missing_usage_and_missing_source_metadata_are_not_fabricated():
    body = answer(citations=False, usage=False)
    body["output"][1]["content"][0]["text"] = "See https://example.org/claimed citehidden"
    search = ResponsesWebSearch(
        "https://provider.test",
        "key",
        model="test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    )
    provider = Provider(Settings(), client=MainClient(), web_search=search)
    try:
        async with provider.task_budget() as budget:
            result = await search.search("public query")
            assert not result["sources_available"] and result["citations"] == []
            assert "hidden" not in result["summary"]
            assert budget.summary()["usage_complete"] is False
            assert budget.summary()["cache_read_usage_complete"] is False
            assert "usage" not in budget.observations[0]
    finally:
        await provider.close()


async def test_sources_are_separate_and_unsafe_links_are_not_rendered():
    body = answer(sources=[{"url": "https://example.org/consulted"}])
    body["output"][1]["content"][0]["annotations"].extend(
        [
            {"type": "url_citation", "url": u, "title": "unsafe"}
            for u in [
                "javascript:alert(1)",
                "https://user:secret@example.org",
                "file:///private/tmp/x",
            ]
        ]
    )
    search = ResponsesWebSearch(
        "https://provider.test",
        "key",
        model="test",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=body)),
    )
    provider = Provider(Settings(), client=MainClient(), web_search=search)
    try:
        async with provider.task_budget():
            result = await search.search("public query")
            assert len(result["citations"]) == 1
            assert result["consulted_sources"][0]["url"] == "https://example.org/consulted"
    finally:
        await provider.close()


async def test_search_limit_is_per_task_and_rejects_before_request():
    requests = []

    def upstream(request):
        requests.append(request)
        return httpx.Response(200, json=answer())

    search = ResponsesWebSearch(
        "https://provider.test", "key", model="test", transport=httpx.MockTransport(upstream)
    )
    provider = Provider(Settings(), client=MainClient(), web_search=search)
    try:
        async with provider.task_budget():
            for _ in range(3):
                await search.search("public query")
            with pytest.raises(TaskBudgetExceeded):
                await search.search("excess")
            assert len(requests) == 3
        async with provider.task_budget():
            await search.search("next task")
            assert len(requests) == 4
    finally:
        await provider.close()


async def test_task_deadline_cancels_inflight_search_without_hiding_cancellation():
    async def upstream(_):
        await asyncio.sleep(10)

    search = ResponsesWebSearch(
        "https://provider.test", "key", model="test", transport=httpx.MockTransport(upstream)
    )
    provider = Provider(Settings(task_timeout_s=0.02), client=MainClient(), web_search=search)
    try:
        with pytest.raises(TimeoutError):
            async with provider.task_budget() as budget:
                await search.search("public query")
        assert budget.stop_reason == "task_deadline" and not budget.observations[0]["completed"]
    finally:
        await provider.close()


async def test_extra_model_fields_cannot_select_endpoint_or_credentials():
    executor = SimpleNamespace()
    outcome = await execute_search(executor, {"query": "public", "api_key": "model-input"})
    assert isinstance(outcome, ToolOutcome) and outcome.is_error


@pytest.mark.parametrize("role", ["buyer", "merchant"])
async def test_role_executor_emits_sources_and_does_not_swallow_budget_exhaustion(role):
    from commerce_common.skills import SkillRegistry
    from merchant_agent import MerchantAgentConfig, MerchantSessionContext, MerchantSessionState
    from shopping_agent import ShoppingAgentConfig, ShoppingSessionContext, ShoppingSessionState

    from shopmate.buyer_executor import BuyerToolExecutor
    from shopmate.merchant_executor import RetailMerchantExecutor

    class Research:
        exhausted = False

        async def search(self, query):
            if self.exhausted:
                raise TaskBudgetExceeded("Model call limit reached")
            return {
                "query": query,
                "summary": "Public source [1]",
                "citations": [{"url": "https://example.org/article", "title": "Research"}],
                "consulted_sources": [],
                "sources_available": True,
                "search_calls": 1,
            }

    checked = []
    research = Research()
    backend = SimpleNamespace(web_search=research, _bound=lambda session: checked.append(session))
    if role == "buyer":
        cls, config, state = BuyerToolExecutor, ShoppingAgentConfig(), ShoppingSessionState()
        session = ShoppingSessionContext(session_id="session", user_id="buyer")
    else:
        cls, config, state = RetailMerchantExecutor, MerchantAgentConfig(), MerchantSessionState()
        session = MerchantSessionContext(
            session_id="session", merchant_id="citybuddy", operator="operator"
        )
    executor = cls(
        backend=backend, config=config, state=state, session=session, skills=SkillRegistry([])
    )
    outcome = await executor.execute("web_search", {"query": "public research"})
    assert not outcome.is_error and checked == [session]
    assert outcome.events[0].data["component"] == "web_sources"
    research.exhausted = True
    with pytest.raises(TaskBudgetExceeded):
        await executor.execute("web_search", {"query": "public research"})


async def test_merchant_executor_does_not_turn_unknown_sandbox_cleanup_into_retryable_result():
    from commerce_common.skills import SkillRegistry
    from merchant_agent import MerchantAgentConfig, MerchantSessionContext, MerchantSessionState

    from shopmate.analysis_sandbox import SandboxCleanupError
    from shopmate.merchant_executor import RetailMerchantExecutor

    class CleanupFailureExecutor(RetailMerchantExecutor):
        def handlers(self):
            return super().handlers() | {"test_analysis": self.fail}

        async def fail(self, arguments):
            raise SandboxCleanupError("Cleanup could not be verified")

    executor = CleanupFailureExecutor(
        backend=object(),
        config=MerchantAgentConfig(),
        skills=SkillRegistry([]),
        session=MerchantSessionContext(
            session_id="session", merchant_id="citybuddy", operator="operator"
        ),
        state=MerchantSessionState(),
    )
    with pytest.raises(SandboxCleanupError):
        await executor.execute("test_analysis", {})
