"""Authenticated retail portal over the upstream buyer and merchant runtimes."""

from __future__ import annotations

import asyncio
from contextlib import aclosing, asynccontextmanager
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from commerce_common.streaming import AgentEvent, to_sse
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from merchant_agent import ListingFilters, MerchantSessionContext
from pydantic import BaseModel, ConfigDict, Field
from starlette.background import BackgroundTask

from .analysis_sql import capture_analysis_queries
from .auth import AuthClient, RequestIdentity, bind_context
from .commerce_client import CommerceError
from .sessions import SessionRecord, SessionStore
from .settings import ROOT


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


def _context(record: SessionRecord, page=None):
    reference = datetime.now(ZoneInfo("Asia/Shanghai"))
    if record.role == "buyer":
        from shopping_agent import PageContext, ShoppingSessionContext

        return ShoppingSessionContext(
            session_id=record.authorization_id,
            user_id=record.owner,
            now=reference,
            timezone="Asia/Shanghai",
            page=page or PageContext(),
        )
    return MerchantSessionContext(
        session_id=record.authorization_id,
        merchant_id="citybuddy",
        operator=record.owner,
        now=reference,
        timezone="Asia/Shanghai",
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


def create_app(
    settings=None,
    *,
    auth=None,
    store=None,
    backend=None,
    agent=None,
    provider=None,
    buyer_backend=None,
    buyer_agent=None,
    buyer_client=None,
    transactions=None,
    sandbox=None,
):
    resources: dict[str, Any] = {
        "auth": auth,
        "store": store,
        "backend": backend,
        "agent": agent,
        "provider": provider,
        "buyer_backend": buyer_backend,
        "buyer_agent": buyer_agent,
        "buyer_client": buyer_client,
        "transactions": transactions,
        "sandbox": sandbox,
    }
    busy: set[str] = set()
    active_users: dict[str, int] = {}

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
            from .buyer_commands import BuyerCommands
            from .memory import RetailMemoryStore

            resources["commands"] = BuyerCommands(resources["store"])
            resources["memory"] = RetailMemoryStore(resources["store"])
            if resources["provider"] is None:
                from .provider import Provider

                resources["provider"] = Provider(settings)
                owned.append(resources["provider"])
            if resources["sandbox"] is None:
                from .analysis_sandbox import DockerSandbox

                resources["sandbox"] = DockerSandbox(settings.analysis_sandbox_image)
                owned.append(resources["sandbox"])
            web_search = getattr(resources["provider"], "web_search", None)
            if resources["backend"] is None:
                from .analysis_sql import AnalysisSQL
                from .backend import CityBuddyMerchantBackend
                from .commerce_client import CommerceClient

                client = CommerceClient(settings.commerce_url)
                sql = AnalysisSQL(settings)
                owned.extend([client, sql])
                await sql.start()
                resources["backend"] = CityBuddyMerchantBackend(
                    resources["auth"],
                    resources["store"],
                    client,
                    sql,
                    report_as_of=datetime.fromisoformat(settings.as_of) if settings.as_of else None,
                    web_search=web_search,
                )
            if resources["agent"] is None:
                from .provider import build_agent

                resources["agent"] = build_agent(
                    settings,
                    resources["backend"],
                    resources["provider"],
                    memory_store=resources["memory"],
                    sandbox=resources["sandbox"],
                )
            if resources["buyer_client"] is None:
                from .buyer_client import BuyerClient

                resources["buyer_client"] = BuyerClient(settings.commerce_url)
                owned.append(resources["buyer_client"])
            if resources["transactions"] is None:
                from .buyer_transactions import BuyerTransactions

                resources["transactions"] = BuyerTransactions(
                    resources["auth"],
                    resources["buyer_client"],
                    resources["commands"],
                    settings,
                )
            if resources["buyer_backend"] is None:
                from .buyer_backend import CityBuddyStorefrontBackend

                resources["buyer_backend"] = CityBuddyStorefrontBackend(
                    resources["auth"],
                    resources["store"],
                    resources["buyer_client"],
                    resources["commands"],
                    web_search=web_search,
                )
            resources["buyer_backend"].transactions = resources["transactions"]
            if resources["buyer_agent"] is None:
                from .provider import build_buyer_agent

                resources["buyer_agent"] = build_buyer_agent(
                    settings,
                    resources["buyer_backend"],
                    resources["provider"],
                    memory_store=resources["memory"],
                )
            yield
        finally:
            for value in reversed(owned):
                result = value.close()
                if hasattr(result, "__await__"):
                    await result

    app = FastAPI(title="ShopMate", lifespan=lifespan)
    app.mount(
        "/products",
        StaticFiles(directory=ROOT / "web" / "public" / "products"),
        name="product-images",
    )
    app.state.resources = resources

    @app.exception_handler(CommerceError)
    async def commerce_error(_, error: CommerceError):
        return JSONResponse(
            status_code=error.status_code,
            content={"detail": error.detail, "category": error.category},
        )

    def context(record, page=None):
        return _context(record, page)

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

    async def storefront(user: RequestIdentity = identity_dependency):
        return user, resources["store"].storefront(user.subject)

    storefront_dependency = Depends(storefront)

    def acquire(record):
        if record.session_id in busy or record.status == "running":
            raise HTTPException(409, "Conversation is busy")
        if (
            len(busy) >= settings.max_active_tasks
            or active_users.get(record.owner, 0) >= settings.max_user_tasks
        ):
            raise HTTPException(
                429, "Assistant is busy; try again shortly", headers={"Retry-After": "2"}
            )
        busy.add(record.session_id)
        active_users[record.owner] = active_users.get(record.owner, 0) + 1

    def release(record):
        if record.session_id in busy:
            busy.remove(record.session_id)
            remaining = active_users[record.owner] - 1
            if remaining:
                active_users[record.owner] = remaining
            else:
                del active_users[record.owner]

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
        with bind_context(user, record.authorization_id):
            for draft_id in resources["store"].draft_ids(record.authorization_id):
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
    async def overview(bound=storefront_dependency):
        user, record = bound
        with bind_context(user, record.authorization_id):
            return await resources["backend"].overview(context(record))

    @app.get(prefix + "/listings")
    async def listings(
        query: str = Query(default="", max_length=256),
        limit: int = Query(default=20, ge=1, le=50),
        offset: int = Query(default=0, ge=0, le=10000),
        status: str | None = None,
        category: str | None = Query(default=None, max_length=100),
        max_stock: int | None = Query(default=None, ge=0),
        content_quality: str | None = None,
        sort: str = "relevance",
        bound=storefront_dependency,
    ):
        user, record = bound
        try:
            filters = ListingFilters(
                status=status,
                category=category,
                max_stock=max_stock,
                content_quality=content_quality,
                sort=sort,
            )
        except ValueError:
            raise HTTPException(422, "Invalid listing filters") from None
        with bind_context(user, record.authorization_id):
            page = await resources["backend"].listings_page(
                context(record), query, filters, limit, offset
            )
        return {
            "listings": page["items"],
            "next_offset": page["nextOffset"],
            "window": page["window"],
        }

    @app.get(prefix + "/inventory")
    async def inventory(
        limit: int = Query(default=20, ge=1, le=50),
        offset: int = Query(default=0, ge=0, le=10000),
        bound=storefront_dependency,
    ):
        user, record = bound
        with bind_context(user, record.authorization_id):
            page = await resources["backend"].inventory_page(context(record), limit, offset)
        return {
            "inventory": page["items"],
            "next_offset": page["nextOffset"],
            "window": page["window"],
        }

    @app.get(prefix + "/order-issues")
    async def order_issues(
        limit: int = Query(default=100, ge=1, le=100), bound=storefront_dependency
    ):
        user, record = bound
        with bind_context(user, record.authorization_id):
            page = await resources["backend"].order_issues_page(context(record), limit)
        return {
            "order_issues": page["items"],
            "limit": page["limit"],
            "truncated": page["truncated"],
        }

    @app.get(prefix + "/campaigns")
    async def campaigns(
        limit: int = Query(default=20, ge=1, le=50),
        offset: int = Query(default=0, ge=0, le=10000),
        bound=storefront_dependency,
    ):
        user, record = bound
        with bind_context(user, record.authorization_id):
            page = await resources["backend"].campaigns_page(context(record), limit, offset)
        return {"campaigns": page["items"], "next_offset": page["nextOffset"]}

    @app.get(prefix + "/promotions")
    async def promotions(
        limit: int = Query(default=20, ge=1, le=50),
        offset: int = Query(default=0, ge=0, le=10000),
        bound=storefront_dependency,
    ):
        user, record = bound
        with bind_context(user, record.authorization_id):
            page = await resources["backend"].promotions_page(context(record), limit, offset)
        return {"promotions": page["items"], "next_offset": page["nextOffset"]}

    @app.get(prefix + "/campaigns/{campaign_id}")
    async def campaign_detail(campaign_id: str, bound=storefront_dependency):
        user, record = bound
        with bind_context(user, record.authorization_id):
            campaign = await resources["backend"].campaign_detail(context(record), campaign_id)
        if campaign is None:
            raise HTTPException(404, "Campaign not found")
        return {"campaign": campaign}

    @app.get(prefix + "/promotions/{promotion_id}")
    async def promotion_detail(promotion_id: str, bound=storefront_dependency):
        user, record = bound
        with bind_context(user, record.authorization_id):
            promotion = await resources["backend"].promotion_detail(context(record), promotion_id)
        if promotion is None:
            raise HTTPException(404, "Promotion not found")
        return {"promotion": promotion}

    @app.get(prefix + "/changes")
    async def changes(
        limit: int = Query(default=20, ge=1, le=50),
        offset: int = Query(default=0, ge=0, le=10000),
        bound=storefront_dependency,
    ):
        user, record = bound
        with bind_context(user, record.authorization_id):
            page = await resources["backend"].changes_page(context(record), limit, offset)
        return {"changes": page["items"], "next_offset": page["nextOffset"]}

    @app.get(prefix + "/listings/{listing_id}")
    async def listing_detail(listing_id: str, bound=storefront_dependency):
        user, record = bound
        with bind_context(user, record.authorization_id):
            listing = await resources["backend"].get_listing(context(record), listing_id)
            if listing is None:
                raise HTTPException(404, "Listing not found")
            pricing = await resources["backend"].get_pricing_context(context(record), listing_id)
        return {"listing": _json(listing), "pricing": _json(pricing)}

    @app.get(prefix + "/changes/{change_id}")
    async def get_change(change_id: str, bound=storefront_dependency):
        user, record = bound
        with bind_context(user, record.authorization_id):
            change = await resources["backend"].get_change(context(record), change_id)
        return {"change": _json(change), "receipt": change.receipt}

    async def action(change_id, bound, apply):
        user, record = bound
        with bind_context(user, record.authorization_id):
            fn = (
                resources["backend"].apply_by_operator
                if apply
                else resources["backend"].discard_by_operator
            )
            result = await fn(context(record), change_id)
        # Java's receipt is persisted by the backend; no concurrent rewrite of chat history.
        return {**result, "change": _json(result["change"])}

    @app.post(prefix + "/changes/{change_id}/apply")
    async def apply(change_id: str, bound=storefront_dependency):
        return await action(change_id, bound, True)

    @app.post(prefix + "/changes/{change_id}/discard")
    async def discard(change_id: str, bound=storefront_dependency):
        return await action(change_id, bound, False)

    async def run_chat(request, bound, *, role):
        user, record = bound
        acquire(record)
        session_context = context(record, getattr(request, "page", None))
        active_agent = resources["buyer_agent" if role == "buyer" else "agent"]
        try:
            if role == "merchant":
                with bind_context(user, record.authorization_id):
                    for draft_id in resources["store"].draft_ids(record.authorization_id):
                        change = await resources["backend"].get_change(session_context, draft_id)
                        _update_change(record, _json(change))
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
            release(record)
            raise

        finished = False

        async def events():
            nonlocal finished
            status = "interrupted"
            budget = None
            analysis_queries = []
            try:
                with (
                    bind_context(
                        user,
                        record.authorization_id,
                        turn_id,
                        role=role,
                        conversation_id=record.session_id,
                    ),
                    resources["memory"].turn(),
                    capture_analysis_queries() as analysis_queries,
                ):
                    async with resources["provider"].task_budget() as budget:
                        async with aclosing(
                            active_agent.stream_turn(record.messages, session_context, record.state)
                        ) as stream:
                            async for event in stream:
                                _ui_event(record, event)
                                if event.type in {"turn_complete", "error"}:
                                    if event.type == "turn_complete":
                                        status = "completed"
                                        if getattr(active_agent, "memory", None) is not None:
                                            from .memory import extract_memory

                                            event.data["memory_status"] = await extract_memory(
                                                active_agent,
                                                record.messages,
                                                session_context,
                                            )
                                            record.items[-1]["memory_status"] = event.data[
                                                "memory_status"
                                            ]
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
                    release(record)

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
                    release(record)

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            # Prevent the frontend proxy from buffering SSE inside a compression stream.
            headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"},
            background=BackgroundTask(finish_unstarted_stream),
        )

    @app.post(prefix + "/chat")
    async def chat(request: ChatRequest, bound=session_dependency):
        return await run_chat(request, bound, role="merchant")

    app.post(prefix + "/conversations")(start_session)
    app.get(prefix + "/conversations")(sessions)

    @app.get(prefix + "/conversations/{conversation_id}")
    async def restore_conversation(conversation_id: str, user=identity_dependency):
        return await restore((user, resources["store"].get(conversation_id, user.subject)))

    @app.post(prefix + "/conversations/{conversation_id}/chat")
    async def chat_conversation(
        conversation_id: str, request: ChatRequest, user=identity_dependency
    ):
        return await chat(request, (user, resources["store"].get(conversation_id, user.subject)))

    from .buyer_routes import install_buyer_routes
    from .memory_routes import install_memory_routes

    install_memory_routes(app, prefix, storefront_dependency, resources, "merchant")
    install_buyer_routes(app, resources, busy, run_chat, context, LoginRequest)
    return app
