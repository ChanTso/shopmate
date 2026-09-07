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
    tool_calls: dict[str, int] = field(default_factory=dict)
    tool_observations: list[dict[str, Any]] = field(default_factory=list)

    def consume(self, request: dict[str, Any]) -> None:
        if time.monotonic() - self.started >= self.timeout_s:
            self.stop_reason = "task_deadline"
            raise TaskBudgetExceeded("Task deadline reached")
        if self.calls >= self.max_calls:
            self.stop_reason = "model_call_limit"
            raise TaskBudgetExceeded("Model call limit reached")
        self.calls += 1

    def remaining_s(self) -> float:
        remaining = self.timeout_s - (time.monotonic() - self.started)
        if remaining <= 0:
            self.stop_reason = "task_deadline"
            raise TaskBudgetExceeded("Task deadline reached")
        return remaining

    def consume_tool(self, name: str, limit: int) -> None:
        self.remaining_s()
        if self.tool_calls.get(name, 0) >= limit:
            self.stop_reason = name + "_call_limit"
            raise TaskBudgetExceeded(name + " call limit reached")
        self.tool_calls[name] = self.tool_calls.get(name, 0) + 1

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
            "tool_attempts": dict(self.tool_calls),
            "tool_observations": list(self.tool_observations),
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
    def __init__(self, settings: Settings, *, client=None, web_search=None) -> None:
        self.settings = settings
        if client is None:
            from .web_search import ResponsesWebSearch

            root, key = provider_credentials(settings.citybuddy_dir)
            self.web_search = web_search or ResponsesWebSearch(root, key, model=settings.model)
            self.client = make_client(
                root,
                key,
                timeout_s=min(120, settings.task_timeout_s),
                before_request=lambda request: current_budget().consume(request),
                observe=lambda item: current_budget().observations.append(item),
            )
        else:
            self.client = client
            self.web_search = web_search

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
        try:
            await self.client.close()
        finally:
            if self.web_search is not None:
                await self.web_search.close()


def build_agent(
    settings: Settings, backend, provider: Provider, *, memory_store=None, sandbox=None
):
    from merchant_agent_runtime import MerchantAgent

    from .analysis_runner import RetailAnalysisRunner
    from .backend import ShopMateConfig
    from .merchant_executor import RECENT_ORDERS_TOOL, RetailMerchantExecutor
    from .settings import ROOT
    from .web_search import WEB_SEARCH_TOOL

    config = ShopMateConfig(
        model=settings.model,
        enable_memory=memory_store is not None,
        memory_model=settings.analysis_model,
        analysis_model=settings.analysis_model,
        thinking_effort=None,
        request_timeout_s=min(120, settings.task_timeout_s),
        analysis_timeout_s=min(180, settings.task_timeout_s),
        max_analysis_rows=settings.sql_max_rows,
        max_analysis_table_chars=settings.sql_max_bytes,
        analysis_query_timeout_s=settings.sql_timeout_ms / 1000 + 1,
    )
    return MerchantAgent(
        backend=backend,
        config=config,
        client=provider.client,
        skills_dir=ROOT / "skills",
        memory_store=memory_store,
        executor_class=RetailMerchantExecutor,
        extra_tools=[WEB_SEARCH_TOOL, RECENT_ORDERS_TOOL],
        analysis_runner=RetailAnalysisRunner(
            client=provider.client, backend=backend, config=config, sandbox=sandbox
        ),
    )


def build_buyer_agent(settings: Settings, backend, provider: Provider, *, memory_store):
    from shopping_agent import ShoppingAgentConfig
    from shopping_agent_runtime import ShoppingAgent

    from .buyer_executor import REFUND_TOOL, BuyerToolExecutor
    from .settings import ROOT
    from .web_search import WEB_SEARCH_TOOL

    config = ShoppingAgentConfig(
        brand_name="ShopMate",
        assistant_name="买家购物助手",
        brand_voice="使用中文，清楚区分商品事实、个人偏好、配送估算和实际订单状态",
        domain_search_notes=(
            "商品价格与库存以当前目录为准；多规格商品先选择具体规格。结账仅交接至用户确认页，"
            "配送报价仅供咨询，不计入商品支付金额。退款只准备确认卡片，不替用户确认。"
            "CNY 的展示价格 price、total 以元计；amount_minor 和所有以 Minor 结尾的金额字段以整数分计。"
            "用户明确说分时保留分数值，不再次乘100；只有明确说元时才换算为分。"
            "退款金额必须等于用户请求，不能擅自改成全额或可退上限；金额或单位不明确先询问。"
        ),
        model=settings.model,
        memory_model=settings.analysis_model,
        thinking_effort=None,
        enable_memory=True,
        max_quantity_per_item=24,
        max_cart_lines=100,
        max_tool_iterations=12,
        close_on_presentation=False,
        request_timeout_s=min(120, settings.task_timeout_s),
        policy_intent_terms=ShoppingAgentConfig.model_fields["policy_intent_terms"].default
        + ("退款", "退货", "政策", "运费", "保修"),
        policy_intent_cues=ShoppingAgentConfig.model_fields["policy_intent_cues"].default
        + ("怎么", "如何", "能否", "可以", "？"),
        order_intent_terms=ShoppingAgentConfig.model_fields["order_intent_terms"].default
        + ("订单", "物流", "包裹", "配送"),
        order_intent_cues=ShoppingAgentConfig.model_fields["order_intent_cues"].default
        + ("在哪", "状态", "什么时候", "退款", "延迟", "？"),
    )
    return ShoppingAgent(
        backend=backend,
        config=config,
        client=provider.client,
        skills_dir=ROOT / "vendor/commerce-agents/shopping-agent/skills",
        memory_store=memory_store,
        executor_class=BuyerToolExecutor,
        extra_tools=[REFUND_TOOL, WEB_SEARCH_TOOL],
    )
