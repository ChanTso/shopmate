"""Bounded queries over granted merchant views; database privileges remain the write boundary."""

from __future__ import annotations

import asyncio
import time
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import aiomysql
import sqlglot
from merchant_agent.analysis import check_analysis_sql
from merchant_agent.types import AnalysisTable
from sqlglot import exp
from sqlglot.optimizer.scope import traverse_scope

VIEWS = frozenset(
    {
        "merchant_products",
        "merchant_paid_orders",
        "merchant_daily_sales",
        "merchant_listing_facts",
        "merchant_store_traffic_daily",
        "merchant_campaign_facts",
    }
)
SCHEMA = """MySQL 8; connections and all timestamps are UTC. Only these views are available:
merchant_products(product_id,name,price_minor,currency,publication_version,available,
 publication_state,stock_quantity,price_editable)
merchant_paid_orders(order_kind,order_id,product_id,product_name,quantity,total_price_minor,
 currency,succeeded_at)
merchant_daily_sales(sale_date,product_id,currency,amount_minor,order_count,units)
merchant_listing_facts(product_id,family_id,listing_id,name,currency,price_minor,stock_quantity,
 publication_state,available,publication_version,category,unit_cost_minor,low_stock_threshold,
 content_quality,missing_attributes,facts_version,observed_at,source_ref)
merchant_store_traffic_daily(local_date,visits,observed_at,source_ref,fixture_version)
merchant_campaign_facts(campaign_id,name,objective,channel,currency,budget_minor,starts_at,
 ends_at,state,version,spend_minor,revenue_minor,observation_start,observation_end,
 observation_source_kind,observation_source_ref,observed_at,fixture_version)
Reporting calendar is Asia/Shanghai. SQL timestamps remain UTC; convert requested local
boundaries to UTC before comparing succeeded_at. Group local days with
DATE(DATE_ADD(succeeded_at, INTERVAL 8 HOUR)). merchant_daily_sales.sale_date is the older UTC
aggregation, not a Shanghai daily rollup; use merchant_paid_orders for Shanghai day/week/month.
Explicit timestamps with offsets retain their actual instants. The host supplies a fixed
report_as_of and fixture coverage separately from the real current operation date.
Do not count periods outside the declared coverage as observed zero sales.
Resolve the requested product set against merchant_products and keep its actual product_id.
Names in the question may be shorthand, translated labels, or annotations: they are not join
keys. Read the name/id mapping when needed; do not invent a literal name list as a catalog.
Join views on product_id, and copy the observed name only for display. An unmatched name is
an unresolved product lookup, not zero sales. Confirm the catalog row before concluding
that the product has no paid rows. Whole-currency rankings derive their set from the views,
not from a hand-written list of names.
Paid sales are gross before refunds, based on succeeded_at in [start,end), using immutable
historical order amounts. These views already join successful payment to PAID order by both
order_kind and order_id; do not join payment again. Separate currencies; CNY and USD amounts
are integer minor units (divide by 100 for display). Do not use today's product price to
recalculate past sales. Products with no paid rows have zero recorded sales; a missing period
is not proof of why the business had no sales. Percentage change with a zero baseline is
undefined. price_editable requires published/available and no seckill association of any state.
Return every derived number as an explicit SQL column: percentage changes, differences,
shares, weighted averages, and displayed major-unit amounts. Return their source totals
beside them, with distinct aliases for each metric, currency, and period. For a comparable
nonzero baseline, percentage change is 100.0 * (current_value - prior_value) /
NULLIF(prior_value, 0). Never calculate these numbers mentally or copy another metric's
change. Query a missing calculation before submitting it; otherwise report it as unknown.
Traffic local_date is an observed Shanghai day, never derive visits from sales. Missing
observations are unknown, not zero; require every day of a complete-day window before
reporting its total or conversion. Conversion = paid order count / visits * 100; orders
are paid per-SKU child orders, not unique buyers or checkout headers. Sum numerators and
denominators before calculating weekly/monthly conversion, never average daily rates.
Category/family mappings in merchant_listing_facts are current catalog assignments; sales
amounts still come from historical paid orders. kids-room filters current category; there
is no category/SKU traffic denominator. Family id is display aggregation, product_id is SKU.
Unit cost and content quality are nullable observed facts. Gross margin (price-cost)/price
is an estimate at current price, not accounting profit or a cost-based hard price floor.
Campaign budget is a plan, spend/revenue are separately dated nullable attribution
observations. ROAS = revenue_minor / NULLIF(spend_minor,0), only when both observations
exist for the same campaign/window/currency. Never add campaign attributed revenue to
store paid sales, and never change observed spend when changing the budget.
No customer identities, acquisition attribution beyond those campaign observations,
physical-return rates, refund-net revenue, or unobserved profit metrics.
Use SELECT/CTE/joins/aggregates/window functions over these views. No writes, other schemas,
locking SELECTs, stored functions, system metadata, or comments. Keep results small; queries
have an execution deadline, row and byte caps. A truncated result is not a complete dataset.
"""


class AnalysisQueryError(ValueError):
    def __init__(self, message: str, *, mysql_error_code: int | None = None):
        super().__init__(message)
        self.mysql_error_code = mysql_error_code


_query_records: ContextVar[list[dict[str, Any]] | None] = ContextVar(
    "shopmate_analysis_queries", default=None
)


@contextmanager
def capture_analysis_queries():
    records: list[dict[str, Any]] = []
    token = _query_records.set(records)
    try:
        yield records
    finally:
        _query_records.reset(token)


def validate_sql(sql: str) -> str:
    if not isinstance(sql, str) or len(sql) > 8000:
        raise AnalysisQueryError("Analysis SQL must be a string of at most 8000 characters")
    if reason := check_analysis_sql(sql):
        raise AnalysisQueryError(reason)
    try:
        statements = sqlglot.parse(sql, read="mysql")
        if len(statements) != 1 or not isinstance(
            statements[0], (exp.Select, exp.Union, exp.Intersect, exp.Except)
        ):
            raise AnalysisQueryError("One read-only SELECT or WITH query is required")
        statement = statements[0]
        if any(node.comments for node in statement.walk()):
            raise AnalysisQueryError("SQL comments are not supported")
        if statement.find(exp.Into) or statement.find(exp.Lock):
            raise AnalysisQueryError("SELECT output files and locks are not allowed")
        if any(node.args.get("recursive") for node in statement.find_all(exp.With)):
            raise AnalysisQueryError("Recursive queries are not supported")
        forbidden_functions = {
            "SLEEP",
            "BENCHMARK",
            "GET_LOCK",
            "RELEASE_LOCK",
            "LOAD_FILE",
            "IS_FREE_LOCK",
            "IS_USED_LOCK",
            "RELEASE_ALL_LOCKS",
            "CURRENT_USER",
            "SESSION_USER",
            "SYSTEM_USER",
            "USER",
            "DATABASE",
            "SCHEMA",
            "VERSION",
            "CONNECTION_ID",
        }
        if statement.find(exp.Parameter) or statement.find(exp.SessionParameter):
            raise AnalysisQueryError("Session and system variables are not available")
        for function in statement.find_all(exp.Func):
            name = (
                function.name.upper()
                if isinstance(function, exp.Anonymous)
                else function.sql_name().upper()
            )
            if name in forbidden_functions:
                raise AnalysisQueryError("Side-effect and blocking functions are not supported")
        for scope in traverse_scope(statement):
            for _, source in scope.selected_sources.values():
                if isinstance(source, exp.Table) and (
                    source.db or source.catalog or source.name.lower() not in VIEWS
                ):
                    raise AnalysisQueryError("Queries may read only granted merchant views")
        return statement.sql(dialect="mysql")
    except sqlglot.errors.SqlglotError:
        raise AnalysisQueryError("Invalid MySQL SELECT; consult the provided schema") from None


def cell(value: Any) -> Any:
    if isinstance(value, Decimal):
        return int(value) if value == value.to_integral_value() else str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


class AnalysisSQL:
    def __init__(self, settings):
        self.settings = settings
        self.pool = None
        self.last_query: dict[str, Any] | None = None

    async def start(self):
        if self.pool is None:
            self.pool = await aiomysql.create_pool(
                host=self.settings.sql_host,
                port=self.settings.sql_port,
                user=self.settings.sql_user,
                password=self.settings.sql_password,
                db=self.settings.sql_database,
                minsize=1,
                maxsize=4,
                autocommit=True,
                connect_timeout=5,
                charset="utf8mb4",
                init_command=(
                    "SET SESSION time_zone = '+00:00', transaction_read_only = 1, "
                    f"max_execution_time = {int(self.settings.sql_timeout_ms)}"
                ),
            )

    async def close(self):
        if self.pool is not None:
            self.pool.close()
            await self.pool.wait_closed()
            self.pool = None

    async def query(self, sql: str) -> AnalysisTable:
        records = _query_records.get()
        if records is None:
            return await self._query(validate_sql(sql))

        started = time.monotonic()
        observation: dict[str, Any] = {"sql": None, "status": "started"}
        records.append(observation)
        try:
            statement = validate_sql(sql)
            observation["sql"] = statement
            result = await self._query(statement)
            observation.update(status="success", result=result.model_dump(mode="json"))
            return result
        except asyncio.CancelledError:
            observation["status"] = "cancelled"
            raise
        except AnalysisQueryError as error:
            observation["status"] = "rejected" if observation["sql"] is None else "error"
            observation["error_category"] = "validation" if observation["sql"] is None else "query"
            if error.mysql_error_code is not None:
                observation["mysql_error_code"] = error.mysql_error_code
            raise
        except Exception:
            observation.update(status="error", error_category="unexpected")
            raise
        finally:
            observation["duration_ms"] = round((time.monotonic() - started) * 1000, 1)

    async def _query(self, statement: str) -> AnalysisTable:
        if self.pool is None:
            raise RuntimeError("Analysis SQL pool is not initialized")
        started = time.monotonic()
        try:
            async with asyncio.timeout(self.settings.sql_timeout_ms / 1000):
                async with self.pool.acquire() as connection:
                    cursor = await connection.cursor(aiomysql.SSCursor)
                    try:
                        await cursor.execute(statement)
                        columns = [item[0] for item in cursor.description or ()]
                        rows: list[list[Any]] = []
                        truncated = False
                        truncation_note = "Result truncated; refine or aggregate the query. Total row count is unknown."
                        result = AnalysisTable(columns=columns)
                        if len(result.model_dump_json().encode()) > self.settings.sql_max_bytes:
                            raise AnalysisQueryError(
                                "Selected column names exceed the result byte limit"
                            )
                        while True:
                            raw = await cursor.fetchone()
                            if raw is None:
                                break
                            row = [cell(value) for value in raw]
                            candidate = AnalysisTable(
                                columns=columns,
                                rows=rows + [row],
                                row_count=len(rows) + 1,
                                truncated=True,
                                note=truncation_note,
                            )
                            if (
                                len(rows) >= self.settings.sql_max_rows
                                or len(candidate.model_dump_json().encode())
                                > self.settings.sql_max_bytes
                            ):
                                truncated = True
                                break
                            rows.append(row)
                        if truncated:
                            # SSCursor.close drains unread rows; closing the socket keeps truncation bounded.
                            connection.close()
                        result = AnalysisTable(
                            columns=columns,
                            rows=rows,
                            row_count=len(rows),
                            truncated=truncated,
                            note=truncation_note if truncated else None,
                        )
                        if len(result.model_dump_json().encode()) > self.settings.sql_max_bytes:
                            raise AnalysisQueryError(
                                "Result metadata exceeds the configured byte limit"
                            )
                    except BaseException:
                        # A cancelled MySQL command must never return to the pool as a reusable connection.
                        connection.close()
                        raise
                    finally:
                        if not connection.closed:
                            await cursor.close()
            self.last_query = {
                "duration_ms": round((time.monotonic() - started) * 1000, 1),
                "rows": len(result.rows),
                "truncated": result.truncated,
            }
            return result
        except TimeoutError:
            raise AnalysisQueryError(
                "Analysis query deadline exceeded; narrow or simplify the query"
            ) from None
        except aiomysql.Error as error:
            raw_code = error.args[0] if error.args else None
            code = raw_code if type(raw_code) is int and 0 < raw_code <= 65535 else None
            detail = {
                1054: "Unknown column; consult the merchant view schema",
                1064: "Invalid MySQL syntax; consult the merchant view schema",
                1142: "Only SELECT access to merchant views is available",
                1146: "Unknown view; consult the merchant view schema",
                1690: (
                    "Numeric value out of range (MySQL 1690); unsigned arithmetic, including "
                    "RANK() subtraction, may underflow. Cast operands to SIGNED or DECIMAL "
                    "before subtracting, then retry."
                ),
                3024: "Analysis query deadline exceeded; simplify the query",
            }.get(code, "Analysis database unavailable or query rejected")
            raise AnalysisQueryError(detail, mysql_error_code=code) from None
