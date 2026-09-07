import asyncio
import json
from datetime import UTC, datetime

import pytest
from commerce_common.delegation import DelegationContext
from commerce_common.testing import FakeCreateClient, tool_calls_message
from merchant_agent import (
    AnalysisResult,
    AnalysisTable,
    MerchantAgentConfig,
    MerchantSessionContext,
    MerchantSessionState,
)
from merchant_agent_runtime.analysis import AnalysisRunner, build_analysis_delegate

from shopmate.analysis_runner import RetailAnalysisRunner
from shopmate.analysis_sandbox import PythonResult, SandboxCleanupError
from shopmate.analysis_sql import validate_sql
from shopmate.provider import Provider, TaskBudgetExceeded
from shopmate.settings import Settings


class Backend:
    def __init__(self, *, truncated=False):
        self.table = AnalysisTable(columns=["n"], rows=[[2], [3]], row_count=2, truncated=truncated)
        self.queries = []
        self.wait = None

    async def execute_analysis_query(self, session, sql):
        validate_sql(sql)
        self.queries.append((session, sql))
        if self.wait is not None:
            await self.wait.wait()
        return self.table

    async def get_analysis_schema(self, session):
        return "merchant_products(product_id, price_minor)"


class Sandbox:
    def __init__(self, *, error=None):
        self.calls = []
        self.error = error

    async def run(self, table, code, *, deadline):
        self.calls.append((table, code, deadline))
        if self.error:
            raise self.error
        return PythonResult("completed", "5\n", "", 0)


def setup(backend=None, sandbox=None, client=None):
    backend = backend or Backend()
    sandbox = sandbox or Sandbox()
    config = MerchantAgentConfig(
        analysis_sql_only=True, analysis_use_code_execution=False, enable_analysis=True
    )
    session = MerchantSessionContext(
        session_id="analysis-session",
        merchant_id="citybuddy",
        operator="operator",
        now=datetime.now(UTC),
    )
    context = DelegationContext(
        backend=backend, config=config, session=session, state=MerchantSessionState()
    )
    runner = RetailAnalysisRunner(client or FakeCreateClient([]), backend, config, sandbox)
    return runner, context, backend, sandbox


def budget_provider():
    return Provider(Settings(), client=object())


async def test_python_uses_backend_authorized_table_and_records_separate_tool_usage():
    runner, context, backend, sandbox = setup()
    request = {
        "sql": "SELECT price_minor AS n FROM merchant_products",
        "code": "print(sum(row[0] for row in rows))",
    }
    async with budget_provider().task_budget() as budget:
        result, failed = await runner._execute(context, "execute_python", request, [], {})
        assert not failed and '"stdout": "5\\n"' in result
        assert budget.calls == 0 and budget.tool_calls == {"python": 1}
        assert budget.tool_observations[0]["status"] == "completed"
    assert backend.queries == [(context.session, request["sql"])]
    assert sandbox.calls[0][0] is backend.table and sandbox.calls[0][1] == request["code"]


@pytest.mark.parametrize("sql", ["DELETE FROM merchant_products", "SELECT * FROM mysql.user"])
async def test_write_and_ungranted_queries_never_reach_python(sql):
    runner, context, backend, sandbox = setup()
    async with budget_provider().task_budget():
        _, failed = await runner._execute(
            context, "execute_python", {"sql": sql, "code": "print(rows)"}, [], {}
        )
    assert failed and not backend.queries and not sandbox.calls


async def test_truncated_query_result_and_model_supplied_table_are_not_analyzable_inputs():
    runner, context, backend, sandbox = setup(Backend(truncated=True))
    request = {"sql": "SELECT price_minor AS n FROM merchant_products", "code": "print(rows)"}
    async with budget_provider().task_budget() as budget:
        assert (await runner._execute(context, "execute_python", request, [], {}))[1]
        assert (
            await runner._execute(
                context,
                "execute_python",
                request | {"table": {"rows": [[999999]]}},
                [],
                {},
            )
        )[1]
        assert budget.tool_calls == {"python": 1}
    assert len(backend.queries) == 1 and not sandbox.calls


async def test_three_attempt_cap_and_task_deadline_propagate_without_more_sql_or_python():
    runner, context, backend, sandbox = setup()
    request = {"sql": "SELECT price_minor AS n FROM merchant_products", "code": "print(rows)"}
    async with budget_provider().task_budget() as budget:
        for _ in range(3):
            await runner._execute(context, "execute_python", request, [], {})
        with pytest.raises(TaskBudgetExceeded, match="python call limit"):
            await runner._execute(context, "execute_python", request, [], {})
        assert len(backend.queries) == len(sandbox.calls) == 3
        budget.started -= 1000
        with pytest.raises(TaskBudgetExceeded, match="deadline"):
            await runner._execute(context, "execute_python", request, [], {})
        assert len(backend.queries) == 3


async def test_cancelled_sql_and_uncertain_cleanup_are_not_converted_to_recoverable_results():
    backend = Backend()
    backend.wait = asyncio.Event()
    runner, context, _, sandbox = setup(backend)
    request = {"sql": "SELECT price_minor AS n FROM merchant_products", "code": "print(rows)"}
    async with budget_provider().task_budget() as budget:
        task = asyncio.create_task(runner._execute(context, "execute_python", request, [], {}))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert budget.tool_observations[0]["status"] == "cancelled" and not sandbox.calls
    runner, context, _, _ = setup(sandbox=Sandbox(error=SandboxCleanupError("uncertain cleanup")))
    async with budget_provider().task_budget() as budget:
        with pytest.raises(SandboxCleanupError):
            await runner._execute(context, "execute_python", request, [], {})
        assert budget.stop_reason == "sandbox_cleanup_failed"


async def test_injected_runner_uses_original_loop_tool_pairing_and_analysis_result():
    request = {
        "sql": "SELECT price_minor AS n FROM merchant_products",
        "code": "print(sum(row[0] for row in rows))",
    }
    submitted = {
        "question": "sum",
        "headline": "The requested sum is 5",
        "figures": [{"label": "sum", "value": 5}],
    }
    client = FakeCreateClient(
        [
            tool_calls_message(("execute_python", request)),
            tool_calls_message(("submit_analysis", submitted)),
        ]
    )
    runner, context, backend, sandbox = setup(client=client)
    delegate = build_analysis_delegate(client, backend, context.config, runner=runner)
    async with budget_provider().task_budget():
        result = await delegate.run(context, {"question": "sum the returned values"})
    assert isinstance(result, AnalysisResult) and result.figures[0].value == 5
    assert RetailAnalysisRunner._run_loop is AnalysisRunner._run_loop
    assert len(client.calls) == 2 and len(sandbox.calls) == 1
    tools = client.calls[0]["tools"]
    assert "execute_python" in {tool["name"] for tool in tools}
    assert sum("cache_control" in tool for tool in tools) == 1
    assert not any(
        "allowed_callers" in tool or tool.get("type", "").startswith("code_execution")
        for tool in tools
    )
    content = client.calls[1]["messages"][-1]["content"]
    assert content[0]["type"] == "tool_result" and content[0]["tool_use_id"] == "tu-1"
    assert not content[0]["is_error"]
    payload = json.loads(
        content[0]["content"].split("<merchant_data>\n")[1].split("\n</merchant_data>")[0]
    )
    assert payload["stdout"] == "5\n"


async def test_host_sql_delegate_returns_original_table_attachment():
    from merchant_agent.fencing import MERCHANT_FENCE

    submission = {"question": "show rows", "headline": "Two rows", "findings": []}

    async def select_table(index):
        if index == 1:
            text = client.calls[-1]["messages"][-1]["content"][0]["content"]
            body = json.loads(
                text.strip().removeprefix(MERCHANT_FENCE.open).removesuffix(MERCHANT_FENCE.close)
            )
            submission["table_ref"] = body["table_ref"]

    client = FakeCreateClient(
        [
            tool_calls_message(
                (
                    "execute_analysis_query",
                    {"sql": "SELECT price_minor AS n FROM merchant_products"},
                )
            ),
            tool_calls_message(("submit_analysis", submission)),
        ],
        before_call=select_table,
    )
    runner, context, backend, sandbox = setup(client=client)
    result = await runner.run(context, {"question": "show rows"})
    assert result.table.rows == backend.table.rows
    assert result.table is not backend.table
    assert len(backend.queries) == 1 and not sandbox.calls
