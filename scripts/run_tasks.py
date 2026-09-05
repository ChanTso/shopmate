#!/usr/bin/env python3
"""Execute the checked-in task tables against the real host; preserve evidence for human review."""

from __future__ import annotations

import argparse
import codecs
import fcntl
import json
import os
import subprocess
import sys
import time
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import quote

import httpx
import pymysql
from pymysql.constants import CLIENT

from shopmate.settings import Settings

ROOT = Path(__file__).resolve().parents[1]
SUBJECT = "shopmate-fixture-operator"
COMMON_SQL = ("products.sql", "history.sql", "scope.sql", "drafts.sql", "events.sql")


class TaskFailure(RuntimeError):
    def __init__(self, reason: str, *, provider: bool = False, unsafe: bool = False):
        super().__init__(reason)
        self.provider, self.unsafe = provider, unsafe


def now() -> str:
    return datetime.now(UTC).isoformat()


def source_revision(path: Path, generated: str) -> str:
    def git(*args: str) -> str:
        return subprocess.check_output(["git", *args], cwd=path, text=True).strip()

    # Excluding generated evidence still checks staged, unstaged and untracked source files.
    dirty = git(
        "status", "--porcelain", "--untracked-files=all", "--", ".", f":(exclude){generated}"
    )
    if dirty:
        raise TaskFailure(f"Source is not committed and clean: {path}", unsafe=True)
    revision = git("rev-parse", "HEAD")
    if len(revision) != 40:
        raise TaskFailure(f"Expected a full commit SHA: {path}", unsafe=True)
    return revision


def verify_sources(settings: Settings, revisions: dict) -> None:
    for path, generated, key in (
        (settings.citybuddy_dir, "bench/results/", "citybuddy_commit"),
        (ROOT, "evals/results/", "shopmate_commit"),
    ):
        if source_revision(path, generated) != revisions[key]:
            raise TaskFailure("Source revision changed during execution", unsafe=True)


def iter_sse(chunks: Iterable[bytes], sink: BinaryIO) -> Iterator[dict[str, Any]]:
    """Persist bytes before parsing; TCP chunks need not align with UTF-8, lines or events."""
    decoder = codecs.getincrementaldecoder("utf-8")()
    pending = ""
    event_type = "message"
    data: list[str] = []

    def lines(final: bool = False):
        nonlocal pending, event_type, data
        while "\n" in pending or (final and pending):
            line, separator, pending = pending.partition("\n")
            if not separator:
                pending = ""
            line = line.removesuffix("\r")
            if not line:
                if data:
                    try:
                        value = json.loads("\n".join(data))
                    except json.JSONDecodeError as error:
                        raise TaskFailure("Invalid SSE JSON") from error
                    if not isinstance(value, dict):
                        raise TaskFailure("SSE payload must be an object")
                    yield {"type": event_type, "data": value}
                event_type, data = "message", []
            elif not line.startswith(":"):
                name, separator, value = line.partition(":")
                if separator and value.startswith(" "):
                    value = value[1:]
                if name == "event":
                    event_type = value
                elif name == "data":
                    data.append(value)

    try:
        for chunk in chunks:
            sink.write(chunk)
            sink.flush()
            pending += decoder.decode(chunk)
            yield from lines()
        pending += decoder.decode(b"", final=True)
        yield from lines(final=True)
    except UnicodeDecodeError as error:
        raise TaskFailure("Invalid SSE UTF-8") from error
    if data:
        raise TaskFailure("SSE ended inside an event")


def item_prices(items: Any) -> dict[str, int]:
    if not isinstance(items, list) or not items:
        raise TaskFailure("Draft items are missing")
    result = {}
    for item in items:
        if not isinstance(item, dict):
            raise TaskFailure("Invalid draft item")
        product, price = item.get("productId"), item.get("newPriceMinor")
        if not isinstance(product, str) or not product or type(price) is not int or price <= 0:
            raise TaskFailure("Invalid draft product or integer price")
        if product in result:
            raise TaskFailure("Duplicate product in draft")
        result[product] = price
    return result


def unique_draft(receipts: list[dict], match: dict) -> str:
    """Only the explicit operator step authorizes currency and the complete target-price set."""
    wanted = item_prices(match["items"])
    candidates: set[str] = set()
    seen: set[str] = set()
    for receipt in receipts:
        draft_id = receipt.get("draftId")
        if not isinstance(draft_id, str) or not draft_id or draft_id in seen:
            raise TaskFailure("Missing or duplicate authoritative draft ID")
        seen.add(draft_id)
        prices = item_prices(receipt.get("items"))
        currency = receipt.get("currency")
        if any(item.get("currency") != currency for item in receipt["items"]):
            raise TaskFailure("Draft item currency differs from its receipt")
        if (
            receipt.get("state") == match["state"] == "PREPARED"
            and currency == match["currency"]
            and prices == wanted
        ):
            candidates.add(draft_id)
    if len(candidates) != 1:
        raise TaskFailure("No unique exact draft match; no operator write attempted")
    return candidates.pop()


def provider_failure(data: dict) -> bool:
    usage = data.get("provider_usage", {})
    if usage.get("stop_reason") in {"model_call_limit", "task_deadline"}:
        return False
    return any(
        item.get("error_category") in {"provider_http", "provider_transport", "provider_protocol"}
        for item in usage.get("model_observations", [])
    )


class Evidence:
    def __init__(self, path: Path, metadata: dict):
        self.path, self.metadata = path, metadata
        path.mkdir(parents=True, exist_ok=True)

    def json(self, name: str, data: Any) -> None:
        target = self.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps({"metadata": self.metadata, "data": data}, ensure_ascii=False, indent=2)
            + "\n"
        )

    def stream(self, name: str, *, sse: bool = False) -> BinaryIO:
        target = self.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        stream = target.open("wb")
        prefix = ": " if sse else "" if name.endswith(".jsonl") else "# "
        header = json.dumps({"metadata": self.metadata}, ensure_ascii=False)
        stream.write((prefix + header + "\n" + ("\n" if sse else "")).encode())
        stream.flush()
        return stream


def snapshot(evidence: Evidence, stage: str, paths: list[Path], session_id: str) -> None:
    config = json.loads((ROOT / ".run/truth-settings.json").read_text())
    with (
        pymysql.connect(
            host=config["sql_host"],
            port=config["sql_port"],
            user=config["sql_user"],
            password=config["sql_password"],
            database=config["sql_database"],
            charset="utf8mb4",
            autocommit=True,
            connect_timeout=10,
            read_timeout=30,
            client_flag=CLIENT.MULTI_STATEMENTS,
        ) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SET @session_id=%s", (session_id,))
        for path in paths:
            source = path.read_text()
            # Execute the committed reference verbatim with the restricted truth account.
            with evidence.stream(f"sql/{stage}/{path.stem}.jsonl") as stream:
                stream.write((json.dumps({"sql": source}, ensure_ascii=False) + "\n").encode())
                stream.flush()
                cursor.execute(source)
                while True:
                    if cursor.description:
                        result = {
                            "columns": [column[0] for column in cursor.description],
                            "rows": cursor.fetchall(),
                        }
                        stream.write(
                            (json.dumps(result, ensure_ascii=False, default=str) + "\n").encode()
                        )
                        stream.flush()
                    if not cursor.nextset():
                        break


def request_json(
    client: httpx.Client,
    evidence: Evidence,
    name: str,
    method: str,
    path: str,
    *,
    body: dict | None = None,
    write: bool = False,
) -> dict:
    try:
        response = client.request(method, path, json=body)
    except httpx.HTTPError as error:
        raise TaskFailure(f"HTTP transport failed: {method} {path}", unsafe=write) from error
    evidence.json(
        name,
        {
            "method": method,
            "path": path,
            "request_body": body,
            "status_code": response.status_code,
            "response_body": response.text,
        },
    )
    if not response.is_success:
        raise TaskFailure(
            f"HTTP {response.status_code}: {method} {path}",
            unsafe=write and response.status_code >= 500,
        )
    try:
        result = response.json()
    except ValueError as error:
        raise TaskFailure(f"Invalid HTTP JSON: {method} {path}", unsafe=write) from error
    if not isinstance(result, dict):
        raise TaskFailure(f"Expected HTTP object: {method} {path}", unsafe=write)
    return result


def wait_quiet(client: httpx.Client, evidence: Evidence, name: str) -> None:
    deadline = time.monotonic() + 20
    while True:
        value = request_json(client, evidence, name, "GET", "sessions")
        sessions = value.get("sessions")
        if not isinstance(sessions, list) or any(
            not isinstance(s, dict)
            or s.get("status") not in {"idle", "running", "completed", "failed", "interrupted"}
            for s in sessions
        ):
            raise TaskFailure("Session execution state is unknown; fixture retained", unsafe=True)
        if all(s["status"] != "running" for s in sessions):
            return
        if time.monotonic() >= deadline:
            raise TaskFailure("A session is still running; fixture retained", unsafe=True)
        time.sleep(0.5)


def chat(client: httpx.Client, evidence: Evidence, number: int, message: str) -> dict:
    evidence.json(f"step-{number:02d}-chat-request.json", {"message": message})
    terminal = None
    try:
        with client.stream("POST", "chat", json={"message": message}) as response:
            evidence.json(
                f"step-{number:02d}-chat-response.json",
                {
                    "status_code": response.status_code,
                    "content_type": response.headers.get("content-type"),
                },
            )
            with evidence.stream(f"step-{number:02d}.sse", sse=True) as stream:
                if not response.is_success:
                    for chunk in response.iter_bytes():
                        stream.write(chunk)
                        stream.flush()
                    raise TaskFailure(f"Chat HTTP {response.status_code}")
                try:
                    for event in iter_sse(response.iter_bytes(), stream):
                        if terminal is not None:
                            raise TaskFailure("SSE event received after terminal event")
                        if event["type"] in {"turn_complete", "error"}:
                            terminal = event
                except TaskFailure as error:
                    error.unsafe = True
                    raise
    except httpx.HTTPError as error:
        raise TaskFailure(
            "Chat HTTP transport failed; turn outcome is unknown", unsafe=True
        ) from error
    if terminal is None:
        raise TaskFailure("SSE closed without a terminal event", unsafe=True)
    evidence.json(f"step-{number:02d}-terminal.json", terminal)
    if terminal["type"] == "error":
        raise TaskFailure("Host reported turn failure", provider=provider_failure(terminal["data"]))
    return terminal


def operator(
    client: httpx.Client,
    evidence: Evidence,
    number: int,
    step: dict,
    sql_paths: list[Path],
    session_id: str,
) -> None:
    snapshot(evidence, f"step-{number:02d}-before", sql_paths, session_id)
    overview = request_json(
        client,
        evidence,
        f"step-{number:02d}-overview.json",
        "GET",
        "overview",
        write=True,  # Overview can recover an uncertain prepare intent through Java.
    )
    changes = overview["needs_attention"]["pending_changes"] + overview["recent_changes"]
    ids = list(dict.fromkeys(change["change_id"] for change in changes))
    receipts = []
    for index, draft_id in enumerate(ids):
        value = request_json(
            client,
            evidence,
            f"step-{number:02d}-candidate-{index:02d}.json",
            "GET",
            "changes/" + quote(draft_id, safe=""),
        )
        receipt = value["receipt"]
        if receipt.get("draftId") != draft_id:
            raise TaskFailure("GET receipt returned a different draft ID")
        receipts.append(receipt)
    draft_id = unique_draft(receipts, step["draft_match"])
    path = "changes/" + quote(draft_id, safe="")
    # No retry: a lost response to a business write must be resolved before any fixture reset.
    result = request_json(
        client,
        evidence,
        f"step-{number:02d}-operator.json",
        "POST",
        path + "/" + step["action"],
        write=True,
    )
    request_json(client, evidence, f"step-{number:02d}-receipt.json", "GET", path)
    snapshot(evidence, f"step-{number:02d}-after", sql_paths, session_id)
    if result.get("ok") is not True:
        raise TaskFailure("Operator endpoint did not accept the requested action")


def run_task(task: dict, suite: dict, evidence: Evidence, settings: Settings, api: str) -> dict:
    record = {"execution_status": "failed", "started_at": now(), "session_id": None}
    session_id = None
    reset_done = False
    failure: TaskFailure | None = None
    unknown: BaseException | None = None
    paths = [ROOT / "evals/sql" / name for name in COMMON_SQL]
    paths += [ROOT / "evals" / name for name in task["evaluator"]["reference_sql"]]
    paths = list(dict.fromkeys(paths))
    with httpx.Client(
        base_url=api.rstrip("/") + "/",
        follow_redirects=False,
        trust_env=False,
        timeout=httpx.Timeout(settings.task_timeout_s + 30, connect=10),
    ) as client:
        try:
            # Neither the login response nor an Authorization header enters an evidence file.
            password = (ROOT / ".run/operator_password").read_text().strip()
            response = client.post("login", json={"loginIdentifier": SUBJECT, "password": password})
            if not response.is_success:
                raise TaskFailure(f"Login HTTP {response.status_code}", unsafe=True)
            login = response.json()
            if login.get("subject") != SUBJECT or not isinstance(login.get("accessToken"), str):
                raise TaskFailure("Login returned an unexpected identity", unsafe=True)
            client.headers["Authorization"] = "Bearer " + login["accessToken"]
            del login, response, password
            wait_quiet(client, evidence, "sessions-before-reset.json")
            with evidence.stream("reset.log") as stream:
                process = subprocess.run(
                    [sys.executable, str(ROOT / "scripts/reset_fixture.py")],
                    cwd=ROOT,
                    env=os.environ | {"CITYBUDDY_DIR": str(settings.citybuddy_dir)},
                    stdout=stream,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            if process.returncode:
                raise TaskFailure("Fixture reset failed; inspect reset.log", unsafe=True)
            reset_done = True
            value = request_json(client, evidence, "new-session.json", "POST", "session")
            session_id = value["session_id"]
            record["session_id"] = session_id
            client.headers["X-Session-Id"] = session_id
            snapshot(evidence, "before", paths, session_id)
            request_json(client, evidence, "visible-listings.json", "GET", "listings")
            first_chat = True
            for number, step in enumerate(task["steps"], 1):
                if step["kind"] == "chat":
                    message = step["message"]
                    if first_chat:
                        message = suite["common_context"] + "\n\n" + message
                    first_chat = False
                    chat(client, evidence, number, message)
                    wait_quiet(client, evidence, f"step-{number:02d}-sessions.json")
                elif step["kind"] == "operator" and step["action"] in {"apply", "discard"}:
                    operator(client, evidence, number, step, paths, session_id)
                else:
                    raise ValueError("Unsupported task step")
            record["execution_status"] = "executed"
        except TaskFailure as error:
            failure = error
        except httpx.HTTPError as error:
            failure = TaskFailure("Host unavailable during login", unsafe=True)
            failure.__cause__ = error
        except BaseException as error:  # noqa: BLE001 -- recorded, then re-raised below
            # Preserve the record, then surface programmer/configuration failures to the caller.
            unknown = error
        finally:
            if session_id is not None:
                try:
                    wait_quiet(client, evidence, "sessions-after.json")
                    # A completed turn can still contain a prepare whose Java response was lost.
                    request_json(
                        client, evidence, "recovered-overview.json", "GET", "overview", write=True
                    )
                    request_json(client, evidence, "saved-session.json", "GET", "session")
                except TaskFailure as error:
                    if failure is None:
                        failure = error
                    failure.unsafe = True
                except BaseException as error:  # noqa: BLE001 -- re-raised after evidence is saved
                    unknown = unknown or error
                try:
                    snapshot(evidence, "after", paths, session_id)
                except BaseException as error:  # noqa: BLE001 -- re-raised after evidence is saved
                    unknown = unknown or error
            try:
                verify_sources(settings, evidence.metadata)
            except TaskFailure as error:
                failure = error
            except BaseException as error:  # noqa: BLE001 -- re-raised after evidence is saved
                unknown = unknown or error
            record["finished_at"] = now()
            if failure is not None:
                record.update(
                    execution_status="failed",
                    reason=str(failure),
                    provider_system_failure=failure.provider,
                    fixture_retained=failure.unsafe,
                )
            if unknown is not None:
                record.update(
                    execution_status="failed",
                    reason="Unexpected " + type(unknown).__name__,
                    fixture_retained=True,
                )
            record["reset_completed"] = reset_done
            evidence.json("execution.json", record)
    if unknown is not None:
        raise unknown
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=("development", "formal"), default="development")
    parser.add_argument("--tasks", help="Comma-separated task IDs; omitted means the full suite")
    parser.add_argument("--repetitions", type=int)
    parser.add_argument("--api", default="http://127.0.0.1:8101/api/merchant")
    args = parser.parse_args()
    settings = Settings.load()  # Does not call provider_credentials or read the model key.
    revisions = {
        "citybuddy_commit": source_revision(settings.citybuddy_dir, "bench/results/"),
        "shopmate_commit": source_revision(ROOT, "evals/results/"),
    }
    suite = json.loads((ROOT / "evals" / (args.suite + ".json")).read_text())
    if not settings.as_of or datetime.fromisoformat(settings.as_of) != datetime.fromisoformat(
        suite["as_of"]
    ):
        parser.error("Configured as_of must equal the suite's fixed UTC cutoff")
    repetitions = args.repetitions if args.repetitions is not None else suite["repetitions"]
    if repetitions < 1:
        parser.error("repetitions must be positive")
    wanted = set(args.tasks.split(",")) if args.tasks else {task["id"] for task in suite["tasks"]}
    if not wanted or wanted - {task["id"] for task in suite["tasks"]}:
        parser.error("Unknown task ID in --tasks")
    selected = [task for task in suite["tasks"] if task["id"] in wanted]
    metadata = revisions | {
        "suite": args.suite,
        "as_of": suite["as_of"],
        "timezone": suite["timezone"],
        "fixture_source_revision": revisions["citybuddy_commit"],
        "main_model": settings.model,
        "analysis_model": settings.analysis_model,
        "provider": "CLIPROXY /v1/chat/completions via Messages adapter",
        "task_timeout_s": settings.task_timeout_s,
        "max_model_calls": settings.max_model_calls,
        "budget_scope": "per chat turn, shared main and analysis calls",
        "api": args.api,
        "repetitions": repetitions,
    }
    entries = [
        {"task_id": task["id"], "repetition": repetition, "execution_status": "not_run"}
        for task in selected
        for repetition in range(1, repetitions + 1)
    ]
    directory = ROOT / "evals/results" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S.%fZ")
    with (ROOT / ".run/evaluation.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            parser.error("Another evaluation driver holds the runtime lock")
        evidence = Evidence(directory, metadata)
        started_at = now()
        evidence.json("run.json", {"started_at": started_at, "executions": entries})
        consecutive_provider_failures = 0
        stop_reason = None
        try:
            for entry in entries:
                verify_sources(settings, revisions)
                task = next(task for task in selected if task["id"] == entry["task_id"])
                task_evidence = Evidence(
                    directory / f"{entry['task_id']}-r{entry['repetition']}",
                    metadata | {"task_id": entry["task_id"], "repetition": entry["repetition"]},
                )
                try:
                    entry.update(run_task(task, suite, task_evidence, settings, args.api))
                except BaseException:
                    # The per-task record is written before unexpected errors are re-raised.
                    saved = task_evidence.path / "execution.json"
                    if saved.exists():
                        entry.update(json.loads(saved.read_text())["data"])
                    raise
                evidence.json("run.json", {"started_at": started_at, "executions": entries})
                print(
                    f"{entry['task_id']} r{entry['repetition']}: {entry['execution_status']}",
                    flush=True,
                )
                if entry.get("provider_system_failure"):
                    consecutive_provider_failures += 1
                else:
                    consecutive_provider_failures = 0
                if entry.get("fixture_retained"):
                    stop_reason = "Runtime or write state is uncertain; fixture retained"
                    break
                if consecutive_provider_failures >= 3:
                    stop_reason = "Three consecutive provider system failures"
                    break
        except BaseException as error:
            stop_reason = "Execution stopped: " + type(error).__name__
            raise
        finally:
            evidence.json(
                "run.json",
                {
                    "started_at": started_at,
                    "finished_at": now(),
                    "stop_reason": stop_reason,
                    "executions": entries,
                },
            )
            print(f"Evidence: {directory}", flush=True)
    return 1 if any(e["execution_status"] != "executed" for e in entries) else 0


if __name__ == "__main__":
    sys.exit(main())
