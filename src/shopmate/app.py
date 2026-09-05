"""Authenticated merchant portal over the upstream MerchantAgent runtime."""

from __future__ import annotations

import asyncio
from contextlib import aclosing, asynccontextmanager
from datetime import UTC, datetime
from typing import Any

from commerce_common.streaming import AgentEvent, to_sse
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from merchant_agent import MerchantSessionContext
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask

from .analysis_sql import capture_analysis_queries
from .auth import AuthClient, RequestIdentity, bind_context
from .commerce_client import CommerceError
from .sessions import SessionRecord, SessionStore


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    loginIdentifier: str = Field(min_length=1, max_length=256)
    password: str = Field(min_length=1, max_length=1024, repr=False)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=1, max_length=4000)


def _json(value):
    return (
        value.model_dump(mode="json", exclude_none=True) if hasattr(value, "model_dump") else value
    )


def _context(record: SessionRecord, as_of: str | None = None) -> MerchantSessionContext:
    reference = datetime.fromisoformat(as_of) if as_of else datetime.now(UTC)
    if reference.tzinfo is None:
        raise ValueError("Report reference date must include a timezone")
    return MerchantSessionContext(
        session_id=record.session_id,
        merchant_id="citybuddy",
        operator=record.owner,
        now=reference.astimezone(UTC),
    )


def _update_change(record: SessionRecord, change: dict):
    """Refresh persisted cards from a Java-backed receipt after an operator action."""
    from merchant_agent import StagedChange

    record.state.seen_changes[change["change_id"]] = StagedChange.model_validate(change)
    for item in record.items:
        if item.get("kind") != "assistant":
            continue
        if change["change_id"] in item.get("changeIds", []):
            item["suggestionsStale"] = change["status"] != "staged"
        for segment in item.get("segments", []):
            if segment.get("type") == "ui":
                payload = segment["block"].get("payload", {})
                if (
                    isinstance(payload, dict)
                    and payload.get("change", {}).get("change_id") == change["change_id"]
                ):
                    payload["change"] = change


def _ui_event(record: SessionRecord, event: AgentEvent):
    """Store the same final card/text payloads the browser receives, without animation state."""
    item = record.items[-1]
    data = event.data
    if event.type == "text_delta":
        segments = item["segments"]
        if segments and segments[-1]["type"] == "text":
            segments[-1]["text"] += str(data.get("text", ""))
        else:
            segments.append({"type": "text", "text": str(data.get("text", ""))})
    elif event.type in ("ui", "ui_partial"):
        component = str(data.get("component", ""))
        payload = data.get("payload", {})
        if component == "suggestions":
            if event.type == "ui":
                item["suggestions"] = payload.get("suggestions", [])
            return
        stream_id = data.get("stream_id")
        key = f"{item['turn']}:{stream_id or component}"
        segment = {
            "type": "ui",
            "block": {"component": component, "payload": payload},
            "slotKey": key,
            "status": "final" if event.type == "ui" else "partial",
        }
        existing = next(
            (i for i, s in enumerate(item["segments"]) if s.get("slotKey") == key), None
        )
        if existing is None:
            item["segments"].append(segment)
        else:
            item["segments"][existing] = segment
        if isinstance(payload, dict) and isinstance(payload.get("change"), dict):
            change_id = payload["change"].get("change_id")
            if change_id and change_id not in item["changeIds"]:
                item["changeIds"].append(change_id)
    elif event.type == "tool_call":
        item["tools"].append(str(data.get("tool", "")))
    elif event.type == "change_update" and isinstance(data.get("change"), dict):
        _update_change(record, data["change"])
    elif event.type == "error":
        item["segments"].append({"type": "error", "text": str(data.get("message", "Turn failed"))})


def create_app(settings=None, *, auth=None, store=None, backend=None, agent=None, provider=None):
    resources: dict[str, Any] = {
        "auth": auth,
        "store": store,
        "backend": backend,
        "agent": agent,
        "provider": provider,
    }
    busy: set[str] = set()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal settings
        if settings is None:
            from .settings import load_settings

            settings = load_settings()
        owned = []
        try:
            if resources["auth"] is None:
                resources["auth"] = AuthClient(settings)
                owned.append(resources["auth"])
            if resources["store"] is None:
                resources["store"] = SessionStore(settings.state_path)
                owned.append(resources["store"])
            if resources["backend"] is None:
                from .analysis_sql import AnalysisSQL
                from .backend import CityBuddyMerchantBackend
                from .commerce_client import CommerceClient

                client = CommerceClient(settings.commerce_url)
                sql = AnalysisSQL(settings)
                owned.extend([client, sql])
                await sql.start()
                resources["backend"] = CityBuddyMerchantBackend(
                    resources["auth"], resources["store"], client, sql
                )
            if resources["provider"] is None:
                from .provider import Provider

                resources["provider"] = Provider(settings)
                owned.append(resources["provider"])
            if resources["agent"] is None:
                from .provider import build_agent

                resources["agent"] = build_agent(
                    settings, resources["backend"], resources["provider"]
                )
            yield
        finally:
            for value in reversed(owned):
                result = value.close()
                if hasattr(result, "__await__"):
                    await result

    app = FastAPI(title="ShopMate", lifespan=lifespan)
    app.state.resources = resources

    @app.exception_handler(CommerceError)
    async def commerce_error(_, error: CommerceError):
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": error.detail, "category": error.category},
        )

    def context(record):
        return _context(record, getattr(settings, "as_of", None))

    async def identity(authorization: str | None = Header(default=None)) -> RequestIdentity:
        if (
            authorization is None
            or not authorization.startswith("Bearer ")
            or len(authorization) > 16384
        ):
            raise HTTPException(401, "Direct user bearer required")
        return await resources["auth"].verify(authorization[7:])

    identity_dependency = Depends(identity)

    async def session(
        user: RequestIdentity = identity_dependency,
        session_id: str | None = Header(default=None, alias="X-Session-Id"),
    ):
        if not session_id or len(session_id) > 128:
            raise HTTPException(400, "X-Session-Id is required")
        return user, resources["store"].get(session_id, user.subject)

    session_dependency = Depends(session)

    def acquire(record):
        if record.session_id in busy or record.status == "running":
            raise HTTPException(409, "Session is busy")
        busy.add(record.session_id)

    prefix = "/api/merchant"

    @app.get(prefix + "/health")
    async def health():
        return {"ok": True, "role": "merchant"}

    @app.post(prefix + "/login")
    async def login(request: LoginRequest):
        return await resources["auth"].login(request.loginIdentifier, request.password)

    @app.post(prefix + "/session")
    async def start_session(user: RequestIdentity = identity_dependency):
        record = resources["store"].create(user.subject)
        return {"session_id": record.session_id, "operator": record.owner, "status": record.status}

    @app.get(prefix + "/sessions")
    async def sessions(user: RequestIdentity = identity_dependency):
        return {"sessions": resources["store"].list(user.subject)}

    @app.get(prefix + "/session")
    async def restore(bound=session_dependency):
        user, record = bound
        with bind_context(user, record.session_id):
            for draft_id in resources["store"].draft_ids(record.session_id):
                change = await resources["backend"].get_change(context(record), draft_id)
                _update_change(record, _json(change))
        return {
            "session_id": record.session_id,
            "operator": record.owner,
            "items": record.items,
            "status": record.status,
            "run_status": record.status,
        }

    @app.get(prefix + "/overview")
    async def overview(bound=session_dependency):
        user, record = bound
        with bind_context(user, record.session_id):
            return await resources["backend"].overview(context(record))

    @app.get(prefix + "/listings")
    async def listings(query: str = "", limit: int = 100, bound=session_dependency):
        user, record = bound
        with bind_context(user, record.session_id):
            results = await resources["backend"].search_listings(context(record), query, None, 100)
        return {
            "total": len(results),
            "listings": [_json(r) for r in results[: max(1, min(limit, 100))]],
        }

    @app.get(prefix + "/listings/{listing_id}")
    async def listing_detail(listing_id: str, bound=session_dependency):
        user, record = bound
        with bind_context(user, record.session_id):
            listing = await resources["backend"].get_listing(context(record), listing_id)
            if listing is None:
                raise HTTPException(404, "Listing not found")
            pricing = await resources["backend"].get_pricing_context(context(record), listing_id)
        return {"listing": _json(listing), "pricing": _json(pricing)}

    @app.get(prefix + "/changes/{change_id}")
    async def get_change(change_id: str, bound=session_dependency):
        user, record = bound
        with bind_context(user, record.session_id):
            change = await resources["backend"].get_change(context(record), change_id)
        return {"change": _json(change), "receipt": change.receipt}

    async def action(change_id, bound, apply):
        user, record = bound
        acquire(record)
        try:
            with bind_context(user, record.session_id):
                fn = (
                    resources["backend"].apply_by_operator
                    if apply
                    else resources["backend"].discard_by_operator
                )
                result = await fn(context(record), change_id)
            result["change"] = _json(result["change"])
            _update_change(record, result["change"])
            # This trusted application message records an observed result, never model authorization.
            record.messages.append(
                {
                    "role": "user",
                    "content": "Portal action result: "
                    + str(
                        {
                            "change_id": change_id,
                            "status": result["change"]["status"],
                            "receipt": result["receipt"],
                        }
                    ),
                }
            )
            resources["store"].save(record)
            return result
        finally:
            busy.discard(record.session_id)

    @app.post(prefix + "/changes/{change_id}/apply")
    async def apply(change_id: str, bound=session_dependency):
        return await action(change_id, bound, True)

    @app.post(prefix + "/changes/{change_id}/discard")
    async def discard(change_id: str, bound=session_dependency):
        return await action(change_id, bound, False)

    @app.post(prefix + "/chat")
    async def chat(request: ChatRequest, bound=session_dependency):
        user, record = bound
        acquire(record)
        try:
            record.messages.append({"role": "user", "content": request.message})
            turn = 1 + max((i.get("turn", 0) for i in record.items), default=0)
            record.items.extend(
                [
                    {"kind": "user", "text": request.message},
                    {
                        "kind": "assistant",
                        "turn": turn,
                        "segments": [],
                        "suggestions": [],
                        "changeIds": [],
                        "pending": True,
                        "tools": [],
                    },
                ]
            )
            turn_id = resources["store"].begin_turn(record)
        except BaseException:
            busy.discard(record.session_id)
            raise

        finished = False

        async def events():
            nonlocal finished
            status = "interrupted"
            budget = None
            analysis_queries = []
            try:
                with (
                    bind_context(user, record.session_id, turn_id),
                    capture_analysis_queries() as analysis_queries,
                ):
                    async with resources["provider"].task_budget() as budget:
                        async with aclosing(
                            resources["agent"].stream_turn(
                                record.messages, context(record), record.state
                            )
                        ) as stream:
                            async for event in stream:
                                _ui_event(record, event)
                                if event.type in {"turn_complete", "error"}:
                                    if event.type == "turn_complete":
                                        status = "completed"
                                    event.data["analysis_queries"] = analysis_queries
                                    if budget is not None:
                                        event.data["provider_usage"] = budget.summary()
                                yield to_sse(event)
            except asyncio.CancelledError:
                resources["store"]._terminate_ui(
                    record, "The connection was interrupted. You can continue."
                )
                raise
            except Exception:  # noqa: BLE001 -- model/tool boundary: never expose provider exception bodies
                status = "failed"
                event = AgentEvent(
                    type="error",
                    data={
                        "message": "The turn could not complete. Saved changes can be checked before retrying.",
                        "analysis_queries": analysis_queries,
                    },
                )
                if budget is not None:
                    event.data["provider_usage"] = budget.summary()
                _ui_event(record, event)
                yield to_sse(event)
            finally:
                finished = True
                record.items[-1]["analysis_queries"] = analysis_queries
                if budget is not None:
                    record.items[-1]["provider_usage"] = budget.summary()
                try:
                    resources["store"].finish_turn(record, status)
                finally:
                    busy.discard(record.session_id)

        async def finish_unstarted_stream():
            nonlocal finished
            # This response may finish after another operation has acquired the session.
            if not finished:
                finished = True
                try:
                    resources["store"]._terminate_ui(
                        record, "The connection was interrupted. You can continue."
                    )
                    resources["store"].finish_turn(record, "interrupted")
                finally:
                    busy.discard(record.session_id)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            background=BackgroundTask(finish_unstarted_stream),
        )

    return app
