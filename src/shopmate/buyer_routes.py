"""Buyer portal: model tools prepare; the authenticated customer confirms checkout and refund."""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Query
from pydantic import ConfigDict, Field
from shopping_agent import PageContext

from .auth import RequestIdentity, bind_context
from .buyer_client import CheckoutCommand, Currency, Nonnegative, Positive, Quantity, RequestModel
from .memory_routes import install_memory_routes


class ChatRequest(RequestModel):
    message: str = Field(min_length=1, max_length=4000)
    page: PageContext = Field(default_factory=PageContext)


class CommandKey(RequestModel):
    request_key: str = Field(min_length=1, max_length=128, pattern=r"^[\x21-\x7e]+$")


class AddCart(CommandKey):
    productId: str = Field(min_length=1, max_length=128)
    quantity: Quantity


class SetCart(AddCart):
    expectedCartVersion: Nonnegative


class RemoveCart(CommandKey):
    productId: str = Field(min_length=1, max_length=128)
    expectedCartVersion: Nonnegative


class CheckoutRequest(CheckoutCommand):
    request_key: str = Field(min_length=1, max_length=128, pattern=r"^[\x21-\x7e]+$")


class PrepareRefund(CommandKey):
    orderId: str = Field(min_length=1, max_length=128)
    amountMinor: Positive
    currency: Currency


class DeliveryRequest(RequestModel):
    product_ids: list[str] = Field(max_length=20)


class EmptyRequest(RequestModel):
    model_config = ConfigDict(extra="forbid")


def install_buyer_routes(app, resources, busy, run_chat, context, login_model):
    prefix = "/api/buyer"

    async def identity(authorization: str | None = Header(default=None)):
        if (
            authorization is None
            or not authorization.startswith("Bearer ")
            or len(authorization) > 16384
        ):
            raise HTTPException(401, "Direct user bearer required")
        return await resources["auth"].verify(authorization[7:], role="buyer")

    identity_dependency = Depends(identity)

    async def session(
        user: RequestIdentity = identity_dependency,
        session_id: str | None = Header(default=None, alias="X-Session-Id"),
    ):
        if not session_id or len(session_id) > 128:
            raise HTTPException(400, "X-Session-Id is required")
        return user, resources["store"].get(session_id, user.subject, role="buyer")

    session_dependency = Depends(session)
    install_memory_routes(app, prefix, session_dependency, resources, "buyer")

    def acquire(record):
        if record.session_id in busy or record.status == "running":
            raise HTTPException(409, "Session is busy")
        busy.add(record.session_id)

    @app.get(prefix + "/health")
    async def health():
        return {"ok": True, "role": "buyer"}

    # The concrete model annotation is assigned before route registration (FastAPI resolves annotations).
    async def login(request):
        return await resources["auth"].login(
            request.loginIdentifier, request.password, role="buyer"
        )

    login.__annotations__["request"] = login_model
    app.post(prefix + "/login")(login)

    @app.post(prefix + "/session")
    async def start_session(user: RequestIdentity = identity_dependency):
        record = resources["store"].create(user.subject, role="buyer")
        return {"session_id": record.session_id, "operator": record.owner, "status": record.status}

    @app.get(prefix + "/sessions")
    async def sessions(user: RequestIdentity = identity_dependency):
        return {"sessions": resources["store"].list(user.subject, role="buyer")}

    @app.get(prefix + "/session")
    async def restore(bound=session_dependency):
        user, record = bound
        with bind_context(user, record.session_id, role="buyer"):
            await resources["buyer_backend"].recover_cart_commands(context(record))
            commands = [
                c.public() for c in resources["commands"].list(record.session_id, user.subject)
            ]
            checkouts = await resources["transactions"].checkouts(context(record))
            actions = resources["transactions"].actions(context(record))
        return {
            "session_id": record.session_id,
            "operator": record.owner,
            "items": record.items,
            "status": record.status,
            "run_status": record.status,
            "commands": commands,
            "checkouts": checkouts,
            "actions": actions,
        }

    @app.get(prefix + "/products")
    async def products(
        query: str = Query(default="", max_length=500),
        limit: int = Query(default=24, ge=1, le=50),
        offset: int = Query(default=0, ge=0, le=10000),
        bound=session_dependency,
    ):
        user, record = bound
        with bind_context(user, record.session_id, role="buyer"):
            return await resources["buyer_backend"].products_page(
                context(record), query, limit, offset
            )

    @app.get(prefix + "/products/{product_id}")
    async def product(product_id: str, bound=session_dependency):
        user, record = bound
        with bind_context(user, record.session_id, role="buyer"):
            product = await resources["buyer_backend"].get_product_details(
                context(record), product_id
            )
        if product is None:
            raise HTTPException(404, "Product not found")
        return {"product": product.model_dump(mode="json")}

    @app.get(prefix + "/cart")
    async def cart(bound=session_dependency):
        user, record = bound
        with bind_context(user, record.session_id, role="buyer"):
            return await resources["buyer_backend"].cart_envelope(context(record))

    async def mutate_cart(operation, request, bound):
        user, record = bound
        acquire(record)
        try:
            with bind_context(user, record.session_id, role="buyer"):
                return await resources["buyer_backend"].cart_mutation(
                    context(record),
                    operation,
                    request.model_dump(exclude={"request_key"}),
                    request.request_key,
                )
        finally:
            busy.discard(record.session_id)

    @app.post(prefix + "/cart/add")
    async def add_cart(request: AddCart, bound=session_dependency):
        return await mutate_cart("ADD", request, bound)

    @app.post(prefix + "/cart/set")
    async def set_cart(request: SetCart, bound=session_dependency):
        return await mutate_cart("SET", request, bound)

    @app.post(prefix + "/cart/remove")
    async def remove_cart(request: RemoveCart, bound=session_dependency):
        return await mutate_cart("REMOVE", request, bound)

    @app.get(prefix + "/commands")
    async def commands(
        key: str | None = Query(default=None, max_length=128), bound=session_dependency
    ):
        user, record = bound
        with bind_context(user, record.session_id, role="buyer"):
            await resources["buyer_backend"].recover_cart_commands(context(record))
            if key is not None:
                values = [resources["commands"].get(key, record.session_id, user.subject)]
            else:
                own = resources["commands"].list(record.session_id, user.subject)
                other = [
                    c
                    for c in resources["commands"].unknown_cart(user.subject)
                    if c.session_id != record.session_id
                ]
                values = own + other
        return {"commands": [c.public() for c in values]}

    @app.post(prefix + "/commands/retry")
    async def retry_command(request: CommandKey, bound=session_dependency):
        user, record = bound
        acquire(record)
        try:
            with bind_context(user, record.session_id, role="buyer"):
                return await resources["buyer_backend"].command_envelope(
                    context(record), request.request_key, retry=True
                )
        finally:
            busy.discard(record.session_id)

    @app.get(prefix + "/orders")
    async def orders(limit: int = Query(default=20, ge=1, le=20), bound=session_dependency):
        user, record = bound
        token = await resources["auth"].exchange_shopping(
            user, record.session_id, "shopping:orders:read"
        )
        values = await resources["buyer_client"].orders(token, record.session_id, limit=limit)
        return {"orders": [v.model_dump(mode="json") for v in values]}

    @app.get(prefix + "/orders/{order_id}")
    async def order(order_id: str, bound=session_dependency):
        user, record = bound
        token = await resources["auth"].exchange_shopping(
            user, record.session_id, "shopping:orders:read"
        )
        value = await resources["buyer_client"].order(order_id, token, record.session_id)
        if value is None:
            raise HTTPException(404, "Order not found")
        return {"order": value.model_dump(mode="json")}

    @app.get(prefix + "/profile")
    async def profile(bound=session_dependency):
        user, record = bound
        with bind_context(user, record.session_id, role="buyer"):
            value = await resources["buyer_backend"].get_preferences(context(record))
        return {"profile": value.model_dump(mode="json")}

    @app.get(prefix + "/policies")
    async def policies(query: str = Query(default="", max_length=500), bound=session_dependency):
        user, record = bound
        with bind_context(user, record.session_id, role="buyer"):
            values = await resources["buyer_backend"].search_policies(context(record), query)
        return {"policies": [v.model_dump(mode="json") for v in values]}

    @app.post(prefix + "/delivery")
    async def delivery(request: DeliveryRequest, bound=session_dependency):
        user, record = bound
        with bind_context(user, record.session_id, role="buyer"):
            values = await resources["buyer_backend"].get_fulfillment_options(
                context(record), request.product_ids
            )
        return {"options": [v.model_dump(mode="json") for v in values]}

    @app.post(prefix + "/delivery/cart")
    async def delivery_cart(request: EmptyRequest, bound=session_dependency):
        user, record = bound
        with bind_context(user, record.session_id, role="buyer"):
            return await resources["buyer_backend"].delivery_cart(context(record))

    async def transact(method, bound, *args):
        user, record = bound
        acquire(record)
        try:
            with bind_context(user, record.session_id, role="buyer"):
                return await method(context(record), *args)
        finally:
            busy.discard(record.session_id)

    @app.post(prefix + "/checkouts")
    async def create_checkout(request: CheckoutRequest, bound=session_dependency):
        return await transact(
            resources["transactions"].create_checkout,
            bound,
            request.request_key,
            request.model_dump(exclude={"request_key"}),
        )

    @app.post(prefix + "/checkouts/retry")
    async def retry_checkout(request: CommandKey, bound=session_dependency):
        return await transact(resources["transactions"].retry_checkout, bound, request.request_key)

    @app.get(prefix + "/checkouts")
    async def checkouts(bound=session_dependency):
        user, record = bound
        with bind_context(user, record.session_id, role="buyer"):
            return {"checkouts": await resources["transactions"].checkouts(context(record))}

    @app.get(prefix + "/checkouts/{checkout_id}")
    async def checkout(checkout_id: str, bound=session_dependency):
        user, record = bound
        with bind_context(user, record.session_id, role="buyer"):
            value = await resources["transactions"].checkout(context(record), checkout_id)
        return {"checkout": value.model_dump(mode="json")}

    @app.post(prefix + "/checkouts/{checkout_id}/pay")
    async def pay(checkout_id: str, request: EmptyRequest, bound=session_dependency):
        return {"checkout": await transact(resources["transactions"].pay, bound, checkout_id)}

    @app.post(prefix + "/actions/prepare")
    async def prepare_refund(request: PrepareRefund, bound=session_dependency):
        async def prepare(ctx):
            return await resources["transactions"].prepare_refund(
                ctx,
                request.model_dump(exclude={"request_key"}),
                call_id=request.request_key,
                key=request.request_key,
            )

        return await transact(prepare, bound)

    @app.post(prefix + "/actions/retry")
    async def retry_refund(request: CommandKey, bound=session_dependency):
        return await transact(resources["transactions"].retry_refund, bound, request.request_key)

    @app.get(prefix + "/actions")
    async def actions(bound=session_dependency):
        user, record = bound
        with bind_context(user, record.session_id, role="buyer"):
            return {"actions": resources["transactions"].actions(context(record))}

    @app.post(prefix + "/actions/{action_id}/confirm")
    async def confirm_refund(action_id: str, request: EmptyRequest, bound=session_dependency):
        return {
            "receipt": await transact(resources["transactions"].confirm_refund, bound, action_id)
        }

    @app.post(prefix + "/chat")
    async def chat(request: ChatRequest, bound=session_dependency):
        user, record = bound
        with bind_context(user, record.session_id, role="buyer"):
            await resources["buyer_backend"].recover_cart_commands(context(record))
        return await run_chat(request, bound, role="buyer")
