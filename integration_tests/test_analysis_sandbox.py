"""Explicit Docker isolation checks; build shopmate-analysis:1 before running this module.

These tests launch bounded disposable containers, never model calls or a capacity workload.
"""

import asyncio
import json
import socket
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import test_business_boundaries as business
import uvicorn
from commerce_common.delegation import DelegationContext
from commerce_common.streaming import AgentEvent
from merchant_agent import AnalysisTable, MerchantSessionContext, MerchantSessionState

from shopmate.analysis_runner import RetailAnalysisRunner
from shopmate.analysis_sandbox import MAX_OUTPUT_BYTES, DockerSandbox
from shopmate.analysis_sql import AnalysisSQL
from shopmate.app import create_app
from shopmate.auth import AuthClient, RequestIdentity, bind_context
from shopmate.backend import CityBuddyMerchantBackend, ShopMateConfig
from shopmate.commerce_client import CommerceClient
from shopmate.provider import Provider
from shopmate.sessions import SessionStore
from shopmate.settings import Settings

settings = business.settings

TABLE = AnalysisTable(
    columns=["amount", "currency"], rows=[[Decimal("0.1"), "CNY"], [Decimal("0.2"), "CNY"]]
)


async def docker(*args):
    process = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    async with asyncio.timeout(10):
        stdout, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode(errors="replace")
    return stdout.decode().strip()


async def absent(names):
    for name in names:
        assert not await docker(
            "container", "ls", "--all", "--quiet", "--filter", f"name=^/{name}$"
        )


class ObservedSandbox(DockerSandbox):
    def __init__(self, *, pause_create=False, **kwargs):
        super().__init__("shopmate-analysis:1", **kwargs)
        self.names = set()
        self.pause_create = pause_create
        self.created = asyncio.Event()
        self.release_create = asyncio.Event()

    async def _capture(self, args, data=None, *, limit=MAX_OUTPUT_BYTES):
        if args[0] == "create":
            self.names.add(args[args.index("--name") + 1])
        result = await super()._capture(args, data, limit=limit)
        if args[0] == "create" and self.pause_create:
            self.created.set()
            await self.release_create.wait()
        return result


async def running(sandbox):
    async with asyncio.timeout(10):
        while True:
            if sandbox.names:
                name = next(iter(sandbox.names))
                ids = await docker("container", "ls", "--quiet", "--filter", f"name=^/{name}$")
                if ids:
                    return name
            await asyncio.sleep(0.05)


async def test_real_container_data_libraries_identity_filesystem_and_network():
    sandbox = ObservedSandbox()
    code = """
import json, os, socket
from decimal import Decimal
from pathlib import Path
import pandas as pd
import numpy as np
frame = pd.DataFrame(rows, columns=columns)
blocked = []
for path in ['/root-write', '/opt/analysis/rewrite']:
    try:
        Path(path).write_text('not allowed')
    except OSError:
        blocked.append(path)
network_blocked = False
try:
    socket.create_connection(('1.1.1.1', 443), timeout=0.5)
except OSError:
    network_blocked = True
print(json.dumps({'sum': str(sum(Decimal(value) for value in frame['amount'])),
                  'uid': os.getuid(), 'blocked': blocked, 'network_blocked': network_blocked,
                  'docker_socket': Path('/var/run/docker.sock').exists(),
                  'host_workspace': Path('/workspace').exists(),
                  'secrets': [key for key in os.environ if 'API_KEY' in key or 'SECRET' in key or 'PASSWORD' in key],
                  'pandas': pd.__version__, 'numpy': np.__version__}))
"""
    try:
        result = await sandbox.run(TABLE, code)
        assert result.status == "completed", result
        value = json.loads(result.stdout)
        assert value["sum"] == "0.3" and value["uid"] == 65532
        assert len(value["blocked"]) == 2 and value["network_blocked"]
        assert not value["docker_socket"] and not value["host_workspace"] and not value["secrets"]
        assert value["pandas"] == "2.3.3" and value["numpy"] == "2.3.3"
        await absent(sandbox.names)
    finally:
        await sandbox.close()


async def test_real_docker_limits_and_disconnect_while_running_leave_no_container():
    sandbox = ObservedSandbox()
    task = asyncio.create_task(sandbox.run(TABLE, "while True: pass"))
    try:
        name = await running(sandbox)
        config = json.loads(await docker("inspect", name))[0]
        host = config["HostConfig"]
        assert (
            host["NanoCpus"] == 1000000000
            and host["Memory"] == host["MemorySwap"] == 512 * 1024 * 1024
        )
        assert host["PidsLimit"] == 64 and host["ReadonlyRootfs"] and host["NetworkMode"] == "none"
        assert host["LogConfig"]["Type"] == "none" and host["IpcMode"] == "none"
        assert host["CapDrop"] == ["ALL"] and "no-new-privileges" in host["SecurityOpt"]
        assert "size=32m" in host["Tmpfs"]["/tmp"] and not host["Binds"]
        assert config["Config"]["User"] == "65532:65532"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await absent(sandbox.names)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await sandbox.close()


async def test_real_cancel_after_create_commit_before_reply_is_observed():
    sandbox = ObservedSandbox(pause_create=True)
    task = asyncio.create_task(sandbox.run(TABLE, "print('must not start')"))
    try:
        await asyncio.wait_for(sandbox.created.wait(), 10)
        task.cancel()
        sandbox.release_create.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await absent(sandbox.names)
    finally:
        sandbox.release_create.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        await sandbox.close()


@pytest.mark.parametrize(
    ("code", "status", "timeout"),
    [
        ("while True: pass", "timeout", 1),
        ("while True: print('x' * 4096)", "output_limit", 20),
        ("values = bytearray(1024 * 1024 * 1024)", "oom", 20),
    ],
)
async def test_real_time_output_and_memory_failures_are_terminal_and_cleaned(code, status, timeout):
    sandbox = ObservedSandbox(timeout_s=timeout)
    try:
        result = await sandbox.run(TABLE, code)
        assert result.status == status, result
        assert len(result.stdout.encode()) + len(result.stderr.encode()) <= MAX_OUTPUT_BYTES
        await absent(sandbox.names)
    finally:
        await sandbox.close()


async def test_real_pid_limit_and_fresh_tmpfs_between_calls():
    sandbox = ObservedSandbox()
    code = """
import json, subprocess
from pathlib import Path
children = []
blocked = False
try:
    for i in range(100):
        children.append(subprocess.Popen(['sleep', '2']))
except OSError:
    blocked = True
finally:
    for child in children:
        child.terminate()
    for child in children:
        child.wait()
Path('/tmp/analysis-marker').write_text('temporary')
print(json.dumps({'blocked': blocked, 'children': len(children)}))
"""
    try:
        result = await sandbox.run(TABLE, code)
        assert result.status == "completed", result
        value = json.loads(result.stdout)
        assert value["blocked"] and 0 < value["children"] < 64
        second = await sandbox.run(
            TABLE, "from pathlib import Path; print(Path('/tmp/analysis-marker').exists())"
        )
        assert second.status == "completed" and second.stdout.strip() == "False"
        await absent(sandbox.names)
    finally:
        await sandbox.close()


async def test_real_sse_disconnect_cancels_sandbox_and_persists_interrupted_session(tmp_path):
    sandbox = ObservedSandbox()
    store = SessionStore(tmp_path / "sse.sqlite3")

    class Auth:
        async def verify(self, token, **kwargs):
            return RequestIdentity("sandbox-operator", token)

    class Agent:
        async def stream_turn(self, messages, session, state):
            yield AgentEvent(
                type="tool_call", data={"tool": "execute_python", "id": "sandbox-call", "input": {}}
            )
            await sandbox.run(TABLE, "while True: pass")
            yield AgentEvent(type="turn_complete", data={"stop_reason": "end_turn"})

    app = create_app(
        Settings(),
        auth=Auth(),
        store=store,
        backend=object(),
        agent=Agent(),
        provider=Provider(Settings(), client=object()),
        buyer_agent=object(),
        sandbox=sandbox,
    )
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app, log_level="critical", access_log=False, lifespan="on", timeout_graceful_shutdown=5
        )
    )
    serving = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if serving.done():
                    await serving
                    raise AssertionError("Test server did not start")
                await asyncio.sleep(0.01)
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", timeout=15, trust_env=False
        ) as client:
            headers = {"Authorization": "Bearer synthetic-local-test"}
            response = await client.post("/api/merchant/session", headers=headers)
            assert response.status_code == 200
            session_id = response.json()["session_id"]
            headers["X-Session-Id"] = session_id
            async with client.stream(
                "POST",
                "/api/merchant/chat",
                headers=headers,
                json={"message": "Sandbox cancellation boundary"},
            ) as response:
                assert response.status_code == 200
                async for line in response.aiter_lines():
                    if line == "event: tool_call":
                        await running(sandbox)
                        break
            async with asyncio.timeout(15):
                while store.get(session_id, "sandbox-operator").status == "running":
                    await asyncio.sleep(0.05)
            record = store.get(session_id, "sandbox-operator")
            assert record.status == "interrupted" and not record.items[-1]["pending"]
            await absent(sandbox.names)
            assert not sandbox._containers
    finally:
        server.should_exit = True
        await asyncio.wait_for(serving, 10)
        listener.close()
        await sandbox.close()
        store.close()


async def test_real_authorized_sql_to_python_matches_reference_sql_and_refuses_incomplete_input(
    settings, tmp_path
):
    auth = AuthClient(settings)
    store = SessionStore(tmp_path / "sql-python.sqlite3")
    client = CommerceClient(settings.commerce_url)
    sql = AnalysisSQL(settings)
    limited = AnalysisSQL(replace(settings, sql_max_rows=1))
    sandbox = ObservedSandbox()
    await sql.start()
    await limited.start()
    try:
        login = await auth.login("shopmate-fixture-operator", business._password())
        identity = RequestIdentity(login["subject"], login["accessToken"])
        record = store.create(identity.subject)
        session = MerchantSessionContext(
            session_id=record.session_id,
            merchant_id="citybuddy",
            operator=identity.subject,
            now=datetime.now(UTC),
        )
        backend = CityBuddyMerchantBackend(auth, store, client, sql)
        config = ShopMateConfig()
        context = DelegationContext(backend, config, session, MerchantSessionState())
        runner = RetailAnalysisRunner(object(), backend, config, sandbox)
        request = {
            "sql": "SELECT SUM(total_price_minor) AS gross_minor,COUNT(*) AS orders FROM merchant_paid_orders WHERE currency='CNY'",
            "code": """
import json
from decimal import Decimal, ROUND_HALF_UP
import pandas as pd
frame = pd.DataFrame(rows, columns=columns)
gross = Decimal(str(frame.loc[0, 'gross_minor']))
orders = int(frame.loc[0, 'orders'])
print(json.dumps({'gross_minor': str(gross), 'orders': orders,
                  'aov_minor': str((gross / orders).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP))}))
""",
        }
        with bind_context(identity, session.session_id, "real-sql-python", role="merchant"):
            async with Provider(settings, client=object()).task_budget() as budget:
                result, failed = await runner._execute(context, "execute_python", request, [], {})
                assert not failed, result
                payload = json.loads(
                    result.split("<merchant_data>\n")[1].split("\n</merchant_data>")[0]
                )
                calculated = json.loads(payload["stdout"])
                reference = await backend.execute_analysis_query(
                    session,
                    "SELECT SUM(total_price_minor),COUNT(*),ROUND(SUM(total_price_minor)/COUNT(*),4) FROM merchant_paid_orders WHERE currency='CNY'",
                )
                gross, orders, average = reference.rows[0]
                assert orders > 0
                assert Decimal(calculated["gross_minor"]) == Decimal(str(gross))
                assert calculated["orders"] == orders
                assert Decimal(calculated["aov_minor"]) == Decimal(str(average))
                names_after_success = set(sandbox.names)
                assert (
                    await runner._execute(
                        context,
                        "execute_python",
                        request | {"sql": "DELETE FROM merchant_products"},
                        [],
                        {},
                    )
                )[1]
                truncated_backend = CityBuddyMerchantBackend(auth, store, client, limited)
                truncated_runner = RetailAnalysisRunner(
                    object(), truncated_backend, config, sandbox
                )
                assert (
                    await truncated_runner._execute(
                        context,
                        "execute_python",
                        request
                        | {
                            "sql": "SELECT product_id,price_minor FROM merchant_products ORDER BY product_id LIMIT 2"
                        },
                        [],
                        {},
                    )
                )[1]
                assert sandbox.names == names_after_success
                assert budget.tool_calls == {"python": 3}
        await absent(sandbox.names)
    finally:
        await sandbox.close()
        await sql.close()
        await limited.close()
        await client.close()
        await auth.close()
        store.close()
