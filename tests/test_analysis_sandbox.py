import asyncio
import json
import time
from datetime import date
from decimal import Decimal

import pytest
from merchant_agent import AnalysisTable

from shopmate.analysis_sandbox import (
    MAX_OUTPUT_BYTES,
    Capture,
    DockerSandbox,
    SandboxCleanupError,
    SandboxError,
    input_payload,
)


def table():
    return AnalysisTable(columns=["amount", "day"], rows=[[Decimal("1.25"), date(2026, 9, 7)]])


def test_only_actual_table_is_serialized_with_exact_decimals_and_dates():
    value = json.loads(input_payload(table(), "print(rows)"))
    assert value == {
        "code": "print(rows)",
        "table": {"columns": ["amount", "day"], "rows": [["1.25", "2026-09-07"]]},
    }


@pytest.mark.parametrize(
    "value",
    [
        AnalysisTable(columns=["x"], rows=[[1]], truncated=True),
        AnalysisTable(columns=["x", "x"], rows=[[1, 2]]),
        AnalysisTable(columns=["x", "y"], rows=[[1]]),
    ],
)
def test_incomplete_or_ambiguous_tables_are_refused_before_a_container(value):
    with pytest.raises(ValueError):
        input_payload(value, "print(rows)")


@pytest.mark.parametrize("code", ["", "x" * 32769, "分" * 12000])
def test_code_size_is_bounded_in_bytes(code):
    with pytest.raises(ValueError):
        input_payload(table(), code)


class FakeDocker(DockerSandbox):
    def __init__(self, *, hold=None, timeout_s=20):
        super().__init__("shopmate-analysis:1", timeout_s=timeout_s)
        self.calls = []
        self.hold = hold
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.created = set()
        self.active = 0
        self.peak = 0
        self.two_started = asyncio.Event()
        self.fail_cleanup = False

    async def _capture(self, args, data=None, *, limit=MAX_OUTPUT_BYTES):
        self.calls.append((args, data))
        if args[0] == "create":
            self.created.add(args[args.index("--name") + 1])
            if self.hold == "create":
                self.entered.set()
                await self.release.wait()
            return Capture(0, b"container-id", b"")
        if args[0] == "start":
            self.active += 1
            self.peak = max(self.peak, self.active)
            if self.active == 2:
                self.two_started.set()
            try:
                if self.hold == "start":
                    self.entered.set()
                    await self.release.wait()
                return Capture(0, b"1.25\n", b"")
            finally:
                self.active -= 1
        if args[0] == "inspect":
            return Capture(
                0, b'{"Status":"exited","Running":false,"ExitCode":0,"OOMKilled":false}', b""
            )
        if args[0] == "rm":
            if self.fail_cleanup:
                return Capture(1, b"", b"daemon unavailable")
            self.created.discard(args[-1])
            return Capture(0, args[-1].encode(), b"")
        if args[0] == "container":
            return Capture(1 if self.fail_cleanup else 0, b"", b"")
        raise AssertionError(args)


async def test_create_hardens_container_and_only_start_receives_the_table():
    docker = FakeDocker()
    result = await docker.run(table(), "print(rows[0][0])")
    assert result.status == "completed" and result.stdout == "1.25\n"
    args = docker.calls[0][0]
    for flag in [
        "--pull=never",
        "--network=none",
        "--user=65532:65532",
        "--read-only",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges",
        "--cpus=1",
        "--memory=512m",
        "--memory-swap=512m",
        "--pids-limit=64",
        "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777",
    ]:
        assert flag in args
    assert not any(arg.startswith(("--mount", "--volume", "--env")) for arg in args)
    sent = [(args, data) for args, data in docker.calls if data is not None]
    assert len(sent) == 1 and sent[0][0][:3] == ["start", "--attach", "--interactive"]
    assert json.loads(sent[0][1])["table"]["rows"] == [["1.25", "2026-09-07"]]
    assert not docker.created and not docker._containers


@pytest.mark.parametrize("phase", ["create", "start"])
async def test_cancellation_waits_for_creation_and_removes_the_named_container(phase):
    docker = FakeDocker(hold=phase)
    task = asyncio.create_task(docker.run(table(), "while True: pass"))
    await docker.entered.wait()
    task.cancel()
    # A create reply can arrive after cancellation; it must settle before rm.
    docker.release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not docker.created and not docker._containers
    assert any(args[0] == "rm" for args, _ in docker.calls)


async def test_two_slot_limit_includes_pending_create_and_cleanup_and_close_cancels_waiters():
    docker = FakeDocker(hold="start")
    tasks = [asyncio.create_task(docker.run(table(), "while True: pass")) for _ in range(3)]
    await docker.two_started.wait()
    assert len(docker.created) == 2 and docker.peak == 2
    await docker.close()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert all(isinstance(value, asyncio.CancelledError) for value in results)
    assert not docker.created and not docker._containers


async def test_execution_timeout_is_distinct_from_shared_task_deadline():
    local = FakeDocker(hold="start", timeout_s=0.02)
    assert (await local.run(table(), "while True: pass")).status == "timeout"
    assert not local.created
    shared = FakeDocker(hold="start")
    with pytest.raises(TimeoutError):
        await shared.run(table(), "while True: pass", deadline=time.monotonic() + 0.02)
    assert not shared.created


async def test_failed_cleanup_is_not_success_or_permission_to_start_more_containers():
    docker = FakeDocker()
    docker.fail_cleanup = True
    with pytest.raises(SandboxCleanupError):
        await docker.run(table(), "print(1)")
    with pytest.raises(SandboxError, match="closed"):
        await docker.run(table(), "print(2)")
    docker.fail_cleanup = False
    await docker.close()
    assert not docker.created


async def test_capture_limits_stdout_and_stderr_while_they_are_read(monkeypatch):
    class Process:
        returncode = None
        stdin = None

        def __init__(self):
            self.stdout, self.stderr = asyncio.StreamReader(), asyncio.StreamReader()
            self.stdout.feed_data(b"x" * (MAX_OUTPUT_BYTES + 8192))
            self.stdout.feed_eof()
            self.stderr.feed_data(b"e" * 8192)
            self.stderr.feed_eof()

        def kill(self):
            self.returncode = -9

        async def wait(self):
            self.returncode = self.returncode if self.returncode is not None else 0
            return self.returncode

    async def spawn(*args, **kwargs):
        return Process()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    result = await DockerSandbox("fixed")._capture(["start", "owned"])
    assert result.limited and len(result.stdout) + len(result.stderr) == MAX_OUTPUT_BYTES


async def test_already_queued_call_does_not_create_after_cleanup_failure_closes_sandbox():
    docker = FakeDocker(hold="start")
    tasks = [asyncio.create_task(docker.run(table(), "print(1)")) for _ in range(3)]
    await docker.two_started.wait()
    docker.fail_cleanup = True
    docker.release.set()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert all(isinstance(value, SandboxError) for value in results)
    assert sum(args[0] == "create" for args, _ in docker.calls) == 2
    docker.fail_cleanup = False
    await docker.close()
