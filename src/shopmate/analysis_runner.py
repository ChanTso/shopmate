"""Host Python tool in the existing analysis delegate; SQL remains its only data input."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import asdict

from commerce_common.prompt_assembly import with_tool_cache_control
from merchant_agent import AnalysisTable
from merchant_agent_runtime.analysis import AnalysisRunner
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .analysis_sandbox import SandboxCleanupError, SandboxError
from .analysis_sql import AnalysisQueryError
from .provider import current_budget


class PythonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    sql: str = Field(min_length=1, max_length=16000)
    code: str = Field(min_length=1, max_length=32768)


PYTHON_TOOL = {
    "name": "execute_python",
    "description": (
        "Compute over a complete result of an actual read-only SQL query against the granted "
        "merchant views. The host executes sql first and passes ONLY that table to isolated "
        "Python 3.11 with pandas 2.3.3, numpy 2.3.3 and the standard library. Use table['columns'] "
        "and table['rows'] (also columns and rows); e.g. pd.DataFrame(rows, columns=columns). "
        "Nonintegral SQL Decimal values remain exact strings; dates/timestamps are ISO strings. "
        "Use Decimal for exact money, respect currencies and missing values. Do not invent, "
        "replace or manually retype data. Print the computed figures and their source totals. "
        "No network, host files, credentials or database connection is available. /tmp is "
        "temporary and starts empty for each call; do not install packages. Maximum 20 seconds, "
        "512 MiB, 64 KiB combined output, and three Python attempts per user turn. Truncated "
        "SQL tables are refused; aggregate or narrow the query. A nonzero exit, timeout or "
        "output limit is a failure, not a completed calculation."
    ),
    "input_schema": PythonRequest.model_json_schema(),
}


class RetailAnalysisRunner(AnalysisRunner):
    def __init__(self, client, backend, config, sandbox):
        if config.analysis_use_code_execution:
            raise ValueError("The host Python runner requires native code execution to be disabled")
        self.sandbox = sandbox
        super().__init__(client=client, backend=backend, config=config)
        if not self._sql_supported:
            raise ValueError("The host Python runner requires the existing read-only SQL backend")

    def _build_tools(self):
        tools = [dict(tool) for tool in super()._build_tools()]
        for tool in tools:
            tool.pop("cache_control", None)
        return with_tool_cache_control([*tools, PYTHON_TOOL])

    async def _execute(self, context, name, tool_input, series_names, tables):
        if name != "execute_python":
            return await super()._execute(context, name, tool_input, series_names, tables)
        try:
            request = PythonRequest.model_validate(tool_input)
        except ValidationError:
            return (
                "execute_python requires only a nonempty sql string and a bounded code string.",
                True,
            )
        budget = current_budget()
        budget.consume_tool("python", 3)
        observation = {"tool": "python", "status": "started"}
        budget.tool_observations.append(observation)
        started = time.monotonic()
        try:
            async with asyncio.timeout(
                min(self._config.analysis_query_timeout_s, budget.remaining_s())
            ):
                table = await self._backend.execute_analysis_query(context.session, request.sql)
            if table is None:
                return "Read-only SQL is unavailable for this analysis.", True
            table = (
                table if isinstance(table, AnalysisTable) else AnalysisTable.model_validate(table)
            )
            observation["rows"] = len(table.rows)
            if table.truncated:
                observation["status"] = "rejected"
                return (
                    "Python requires a complete SQL result; narrow or aggregate the query and retry.",
                    True,
                )
            result = await self.sandbox.run(
                table, request.code, deadline=time.monotonic() + budget.remaining_s()
            )
            budget.remaining_s()
            observation.update(status=result.status, exit_code=result.exit_code)
            payload = asdict(result)
            if len(json.dumps(payload, ensure_ascii=False)) > self._config.max_fenced_chars - 100:
                observation["status"] = "output_limit"
                return (
                    "Python output exceeds the analysis context; print only the requested aggregates.",
                    True,
                )
            return self._fence(payload), result.status != "completed"
        except asyncio.CancelledError:
            observation["status"] = "cancelled"
            raise
        except TimeoutError:
            budget.remaining_s()
            observation["status"] = "timeout"
            return "The SQL/Python attempt timed out; narrow the calculation.", True
        except SandboxCleanupError:
            budget.stop_reason = "sandbox_cleanup_failed"
            observation["status"] = "cleanup_failed"
            raise
        except (AnalysisQueryError, SandboxError, ValueError) as error:
            observation["status"] = "error"
            return f"execute_python failed: {self._sanitize(str(error), 240)}", True
        finally:
            observation["elapsed_ms"] = round((time.monotonic() - started) * 1000)
