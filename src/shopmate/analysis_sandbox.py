"""Per-call Docker containers for bounded analysis over already-authorized SQL results."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from uuid import uuid4

from merchant_agent import AnalysisTable

from .analysis_sql import cell

MAX_CODE_BYTES = 32 * 1024
MAX_INPUT_BYTES = 1024 * 1024
MAX_OUTPUT_BYTES = 64 * 1024
CLEANUP_TIMEOUT_S = 10


class SandboxError(RuntimeError):
    pass


class SandboxCleanupError(SandboxError):
    pass


@dataclass(frozen=True)
class PythonResult:
    status: str
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None


@dataclass(frozen=True)
class Capture:
    returncode: int
    stdout: bytes
    stderr: bytes
    limited: bool = False


def input_payload(table: AnalysisTable, code: str) -> bytes:
    if not isinstance(code, str) or not code.strip() or len(code.encode()) > MAX_CODE_BYTES:
        raise ValueError("Python code must contain 1 to 32768 UTF-8 bytes")
    if table.truncated:
        raise ValueError("Python requires a complete SQL result; narrow or aggregate the query")
    if len(set(table.columns)) != len(table.columns):
        raise ValueError("SQL columns must have distinct aliases before Python analysis")
    if any(len(row) != len(table.columns) for row in table.rows):
        raise ValueError("SQL row width does not match the returned columns")
    payload = json.dumps(
        {
            "table": {
                "columns": table.columns,
                "rows": [[cell(v) for v in row] for row in table.rows],
            },
            "code": code,
        },
        ensure_ascii=False,
        allow_nan=False,
    ).encode()
    if len(payload) > MAX_INPUT_BYTES:
        raise ValueError("Python input exceeds 1 MiB; narrow or aggregate the SQL query")
    return payload


class DockerSandbox:
    def __init__(self, image: str, *, docker_bin="docker", timeout_s=20):
        if not image or image.startswith("-"):
            raise ValueError("A fixed analysis image is required")
        if timeout_s <= 0 or timeout_s > 20:
            raise ValueError("Sandbox timeout must be positive and at most 20 seconds")
        self.image, self.docker_bin, self.timeout_s = image, docker_bin, timeout_s
        self._slots = asyncio.Semaphore(2)
        self._runs: set[asyncio.Task] = set()
        self._containers: set[str] = set()
        self._closed = False

    async def run(self, table: AnalysisTable, code: str, *, deadline: float | None = None):
        payload = input_payload(table, code)
        if self._closed:
            raise SandboxError("Analysis sandbox is closed")
        task = asyncio.create_task(self._run(payload, deadline))
        self._runs.add(task)
        try:
            return await task
        finally:
            self._runs.discard(task)

    def _create_args(self, name):
        return [
            "create",
            "--pull=never",
            "--name",
            name,
            "--label",
            "shopmate.analysis=true",
            "--network=none",
            "--ipc=none",
            "--log-driver=none",
            "--user=65532:65532",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--cpus=1",
            "--memory=512m",
            "--memory-swap=512m",
            "--pids-limit=64",
            "--ulimit=nofile=128:128",
            "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=32m,mode=1777",
            "--init",
            "--interactive",
            self.image,
        ]

    async def _run(self, payload, deadline):
        own_deadline = time.monotonic() + self.timeout_s
        ends_at = min(own_deadline, deadline) if deadline is not None else own_deadline
        name, create = None, None
        acquired = False
        try:
            async with asyncio.timeout_at(ends_at):
                await self._slots.acquire()
                acquired = True
                if self._closed:
                    raise SandboxError("Analysis sandbox is closed")
                name = "shopmate-analysis-" + uuid4().hex
                self._containers.add(name)
                # The daemon may commit creation before the CLI receives its reply. Keep that
                # request alive through cancellation, then remove the exact host-chosen name.
                create = asyncio.create_task(self._capture(self._create_args(name), limit=8192))
                created = await asyncio.shield(create)
                if created.returncode != 0 or created.limited:
                    raise SandboxError(
                        "Analysis container could not be created; check the fixed image and Docker"
                    )
                output = await self._capture(["start", "--attach", "--interactive", name], payload)
                if output.limited:
                    return PythonResult(
                        "output_limit",
                        output.stdout.decode(errors="replace"),
                        output.stderr.decode(errors="replace"),
                    )
                inspected = await self._capture(
                    ["inspect", "--format", "{{json .State}}", name], limit=8192
                )
                if inspected.returncode != 0:
                    raise SandboxError("Analysis container completion could not be inspected")
                state = json.loads(inspected.stdout)
                if (
                    state.get("Status") != "exited"
                    or state.get("Running")
                    or type(state.get("ExitCode")) is not int
                ):
                    raise SandboxError("Analysis container did not reach a readable terminal state")
                status = (
                    "oom"
                    if state.get("OOMKilled")
                    else "completed"
                    if state["ExitCode"] == 0
                    else "error"
                )
                return PythonResult(
                    status,
                    output.stdout.decode(errors="replace"),
                    output.stderr.decode(errors="replace"),
                    state["ExitCode"],
                )
        except TimeoutError:
            if deadline is not None and deadline <= own_deadline:
                raise
            return PythonResult("timeout")
        finally:
            try:
                if name is not None:
                    await self._finish_cleanup(name, create)
            except SandboxCleanupError:
                self._closed = True
                raise
            finally:
                if acquired:
                    self._slots.release()

    async def _capture(self, args, data=None, *, limit=MAX_OUTPUT_BYTES):
        spawning = asyncio.create_task(
            asyncio.create_subprocess_exec(
                self.docker_bin,
                *args,
                stdin=asyncio.subprocess.PIPE if data is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        )
        cancelled = False
        while not spawning.done():
            try:
                await asyncio.shield(spawning)
            except asyncio.CancelledError:
                cancelled = True
        process = spawning.result()

        def kill():
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass  # The other output reader or the OS may have already observed exit.

        if cancelled:
            kill()
            await process.wait()
            raise asyncio.CancelledError
        buffers = [bytearray(), bytearray()]
        limited = False

        async def read(stream, index):
            nonlocal limited
            while chunk := await stream.read(4096):
                remaining = limit - sum(map(len, buffers))
                buffers[index].extend(chunk[:remaining])
                if len(chunk) > remaining:
                    limited = True
                    kill()
                    return

        async def feed():
            if data is not None:
                try:
                    process.stdin.write(data)
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass  # A failing container may exit before consuming its entire bounded input.
                finally:
                    process.stdin.close()

        jobs = [
            asyncio.create_task(read(process.stdout, 0)),
            asyncio.create_task(read(process.stderr, 1)),
            asyncio.create_task(feed()),
        ]
        try:
            await asyncio.gather(*jobs)
            await process.wait()
            return Capture(process.returncode, bytes(buffers[0]), bytes(buffers[1]), limited)
        finally:
            for job in jobs:
                job.cancel()
            kill()
            await process.wait()
            await asyncio.gather(*jobs, return_exceptions=True)

    async def _cleanup(self, name, create):
        try:
            async with asyncio.timeout(CLEANUP_TIMEOUT_S):
                if create is not None:
                    await asyncio.shield(create)
                removed = await self._capture(["rm", "--force", name], limit=8192)
                if removed.returncode != 0:
                    # A rejected create has no object to remove. Verify absence rather than
                    # treating an unreachable daemon as a successful cleanup.
                    listed = await self._capture(
                        ["container", "ls", "--all", "--quiet", "--filter", f"name=^/{name}$"],
                        limit=8192,
                    )
                    if listed.returncode != 0 or listed.stdout.strip() or listed.limited:
                        raise SandboxCleanupError(
                            "Analysis container cleanup could not be verified"
                        )
                self._containers.discard(name)
        except TimeoutError:
            if create is not None and not create.done():
                create.cancel()
                await asyncio.gather(create, return_exceptions=True)
            raise SandboxCleanupError(
                "Analysis container cleanup timed out; inspect the owned container before continuing"
            ) from None

    async def _finish_cleanup(self, name, create):
        cleanup = asyncio.create_task(self._cleanup(name, create))
        cancelled = False
        while not cleanup.done():
            try:
                await asyncio.shield(cleanup)
            except asyncio.CancelledError:
                cancelled = True
        cleanup.result()
        if cancelled:
            raise asyncio.CancelledError

    async def close(self):
        self._closed = True
        running = list(self._runs)
        for task in running:
            task.cancel()
        results = await asyncio.gather(*running, return_exceptions=True)
        for name in tuple(self._containers):
            await self._finish_cleanup(name, None)
        for result in results:
            if isinstance(result, SandboxCleanupError):
                raise result
