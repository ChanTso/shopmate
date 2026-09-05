import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from types import SimpleNamespace

import aiomysql
import pytest

from shopmate.analysis_sql import (
    AnalysisQueryError,
    AnalysisSQL,
    capture_analysis_queries,
    validate_sql,
)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT currency, SUM(total_price_minor) FROM merchant_paid_orders GROUP BY currency",
        (
            "WITH paid AS (SELECT product_id, SUM(quantity) AS n FROM merchant_paid_orders GROUP BY product_id) "
            "SELECT p.name, paid.n FROM paid JOIN merchant_products p ON p.product_id = paid.product_id"
        ),
    ],
)
def test_select_and_cte_only_use_granted_views(sql):
    assert validate_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM merchant_products",
        "SELECT * FROM merchant_products; SELECT 1",
        "SELECT * FROM standard_order",
        "WITH x AS (SELECT * FROM mysql.user) SELECT * FROM x",
        "SELECT * FROM commerce_db.merchant_products",
        "SELECT * FROM merchant_products FOR UPDATE",
        "SELECT SLEEP(5)",
        "SELECT @@version",
        "SELECT 1 # comment",
    ],
)
def test_query_guard_rejects_other_sources_and_non_read_behavior(sql):
    with pytest.raises(AnalysisQueryError):
        validate_sql(sql)


class Cursor:
    description = (("amount_minor",),)

    def __init__(self, rows, wait=False, error=None):
        self.rows = iter(rows)
        self.wait, self.error = wait, error
        self.close_calls = 0
        self.fetches = 0
        self.started = asyncio.Event()
        self.executed_sql = None

    async def execute(self, sql):
        self.executed_sql = sql
        self.started.set()
        if self.error:
            raise self.error
        if self.wait:
            await asyncio.Event().wait()

    async def fetchone(self):
        self.fetches += 1
        return next(self.rows, None)

    async def close(self):
        self.close_calls += 1


class Connection:
    def __init__(self, cursor):
        self.value = cursor
        self.closed = False

    async def cursor(self, cursor_class):
        assert cursor_class is aiomysql.SSCursor
        return self.value

    def close(self):
        self.closed = True


class Pool:
    def __init__(self, connection):
        self.connection = connection

    @asynccontextmanager
    async def acquire(self):
        yield self.connection


def connection_for(cursor, *, rows=2, max_bytes=1024, timeout_ms=100):
    connection = Connection(cursor)
    sql = AnalysisSQL(
        SimpleNamespace(sql_max_rows=rows, sql_max_bytes=max_bytes, sql_timeout_ms=timeout_ms)
    )
    sql.pool = Pool(connection)
    return sql, connection


async def test_row_cap_closes_unread_result_instead_of_draining_it():
    cursor = Cursor([(Decimal(23),), (Decimal(45),), (Decimal(67),), (Decimal(89),)])
    sql, connection = connection_for(cursor)
    result = await sql.query("SELECT amount_minor FROM merchant_daily_sales")
    assert result.rows == [[23], [45]] and result.truncated
    assert result.row_count == 2 and "unknown" in result.note
    assert connection.closed and cursor.close_calls == 0 and cursor.fetches == 3


async def test_byte_cap_counts_encoded_unicode_and_metadata():
    cursor = Cursor([("好" * 1000,)])
    sql, connection = connection_for(cursor, max_bytes=512)
    result = await sql.query("SELECT name FROM merchant_products")
    assert result.truncated and result.rows == []
    assert len(result.model_dump_json().encode()) <= 512
    assert connection.closed


async def test_timeout_removes_connection_from_reuse():
    cursor = Cursor([], wait=True)
    sql, connection = connection_for(cursor, timeout_ms=5)
    with pytest.raises(AnalysisQueryError, match="deadline"):
        await sql.query("SELECT name FROM merchant_products")
    assert connection.closed and cursor.close_calls == 0


async def test_query_errors_do_not_expose_driver_connection_details():
    cursor = Cursor([], error=aiomysql.OperationalError(2003, "private-host upstream-secret"))
    sql, connection = connection_for(cursor)
    with pytest.raises(AnalysisQueryError) as failure:
        await sql.query("SELECT name FROM merchant_products")
    assert "upstream-secret" not in str(failure.value)
    assert "private-host" not in str(failure.value)
    assert connection.closed


async def test_query_trace_keeps_executed_sql_and_bounded_return_values():
    cursor = Cursor([(Decimal("23.75"),), (Decimal(45),), (Decimal(67),)])
    sql, _ = connection_for(cursor)
    with capture_analysis_queries() as records:
        result = await sql.query("select amount_minor from merchant_daily_sales")
    assert records[0]["sql"] == cursor.executed_sql
    assert records[0]["status"] == "success"
    assert records[0]["result"] == result.model_dump(mode="json")
    assert records[0]["result"]["rows"] == [["23.75"], [45]]
    assert records[0]["result"]["truncated"] is True
    assert records[0]["duration_ms"] >= 0


async def test_rejected_query_has_no_executed_sql():
    cursor = Cursor([])
    sql, _ = connection_for(cursor)
    with capture_analysis_queries() as records, pytest.raises(AnalysisQueryError):
        await sql.query("DELETE FROM merchant_products")
    assert cursor.executed_sql is None
    assert records[0]["sql"] is None
    assert records[0]["status"] == "rejected"
    assert records[0]["error_category"] == "validation"


@pytest.mark.parametrize(
    ("error", "raised", "category"),
    [
        (aiomysql.OperationalError(2003, "private-host secret"), AnalysisQueryError, "query"),
        (RuntimeError("private configuration secret"), RuntimeError, "unexpected"),
    ],
)
async def test_query_trace_records_failure_without_exception_body(error, raised, category):
    sql, _ = connection_for(Cursor([], error=error))
    with capture_analysis_queries() as records, pytest.raises(raised):
        await sql.query("SELECT name FROM merchant_products")
    assert records[0]["status"] == "error"
    assert records[0]["error_category"] == category
    assert "secret" not in str(records) and "private" not in str(records)


async def test_cancelled_query_retains_status_and_removes_connection():
    cursor = Cursor([], wait=True)
    sql, connection = connection_for(cursor, timeout_ms=5000)
    with capture_analysis_queries() as records:
        task = asyncio.create_task(sql.query("SELECT name FROM merchant_products"))
        await cursor.started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert records[0]["status"] == "cancelled"
    assert "result" not in records[0]
    assert connection.closed


async def test_concurrent_turn_query_traces_do_not_leak_or_retain_outside_queries():
    async def turn(value):
        sql, _ = connection_for(Cursor([(value,)]))
        with capture_analysis_queries() as records:
            await asyncio.sleep(0)
            await sql.query("SELECT amount_minor FROM merchant_daily_sales")
            await asyncio.sleep(0)
        outside, _ = connection_for(Cursor([(999,)]))
        await outside.query("SELECT amount_minor FROM merchant_daily_sales")
        return records

    first, second = await asyncio.gather(turn(12), turn(34))
    assert len(first) == len(second) == 1
    assert first[0]["result"]["rows"] == [[12]]
    assert second[0]["result"]["rows"] == [[34]]
