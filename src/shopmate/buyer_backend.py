"""The retail shopping tools use Java facts and persisted commands for cart writes."""

from __future__ import annotations

import asyncio
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from zoneinfo import ZoneInfo

from commerce_common.turn import current_tool_call
from pydantic import ValidationError
from shopping_agent.backend import NotOffered, StorefrontBackend, Unavailable
from shopping_agent.serialization import cart_payload
from shopping_agent.types import (
    Cart,
    CartItem,
    FulfillmentOption,
    Order,
    OrderItem,
    OrderStatus,
    Policy,
    ProductDetails,
    SearchFilters,
    UserPreferences,
)

from .auth import current_context
from .buyer_client import CartView, OrderView, RetailProduct
from .commerce_client import CommerceError


class BuyerCartItem(CartItem):
    currency: str
    orderable: bool
    line_total_minor: int | None

    @property
    def line_total(self) -> float | None:
        return None if self.line_total_minor is None else self.line_total_minor / 100


class BuyerCart(Cart):
    items: list[BuyerCartItem]
    currency: str | None = None
    subtotal_minor: int | None
    checkout_ready: bool

    @property
    def subtotal(self) -> float | None:
        return None if self.subtotal_minor is None else self.subtotal_minor / 100


class BuyerOrder(Order):
    payment_status: str
    payment: dict | None
    refunds: dict
    fulfillment: dict | None
    product_snapshot: dict


class BuyerFulfillmentOption(FulfillmentOption):
    code: str
    currency: str
    estimate_only: bool
    quoted_at: str


def product_details(value: RetailProduct) -> ProductDetails:
    content = value.content
    try:
        return ProductDetails(
            product_id=value.id,
            title=value.title,
            brand=content.get("brand"),
            price=value.priceMinor / 100,
            currency=value.currency,
            rating=content.get("rating"),
            review_count=content.get("reviewCount"),
            image_url=content.get("imageUrl"),
            category=content.get("category"),
            labels=content.get("labels", []),
            attributes=content.get("attributes", {}),
            in_stock=value.inStock,
            short_description=value.shortDescription,
            options={option.name: option.values for option in value.options},
            option_values=value.optionValues,
            variant_of=value.variantOf,
            long_description=content.get("longDescription"),
            specs=content.get("specs", {}),
            review_highlights=content.get("reviewHighlights", []),
            variants=[product_details(item) for item in value.variants],
        )
    except ValidationError:
        raise CommerceError(502, "INVALID_RESPONSE", "Invalid retail product content") from None


def shopping_cart(value: CartView) -> BuyerCart:
    return BuyerCart(
        currency=value.currency,
        subtotal_minor=value.subtotalMinor,
        checkout_ready=value.checkoutReady,
        items=[
            BuyerCartItem(
                product_id=item.productId,
                title=item.name,
                price=item.unitPriceMinor / 100,
                quantity=item.quantity,
                image_url=item.imageUrl,
                option_values=item.optionValues,
                variant_of=item.familyId,
                currency=item.currency,
                orderable=item.orderable,
                line_total_minor=item.lineTotalMinor,
            )
            for item in value.items
        ],
    )


def shopping_order(value: OrderView) -> BuyerOrder:
    zone = ZoneInfo("Asia/Shanghai")
    payment = value.payment.model_dump(mode="json") if value.payment else None
    if payment is not None and value.payment.succeededAt is not None:
        payment["succeededAt"] = value.payment.succeededAt.astimezone(zone).isoformat()
    fulfillment = value.fulfillment.model_dump(mode="json") if value.fulfillment else None
    if fulfillment is not None:
        for name in (
            "promisedDeliveryAt",
            "estimatedDeliveryAt",
            "packedAt",
            "shippedAt",
            "deliveredAt",
            "observedAt",
        ):
            stamp = getattr(value.fulfillment, name)
            fulfillment[name] = stamp.astimezone(zone).isoformat() if stamp is not None else None
    status = OrderStatus(value.status.lower())
    if value.status == "PAID" and value.fulfillment is not None:
        facts = value.fulfillment
        status = (
            OrderStatus.DELAYED
            if facts.delayReason and facts.stage != "DELIVERED"
            else {
                "PROCESSING": OrderStatus.PROCESSING,
                "PACKED": OrderStatus.PROCESSING,
                "SHIPPED": OrderStatus.SHIPPED,
                "OUT_FOR_DELIVERY": OrderStatus.OUT_FOR_DELIVERY,
                "DELIVERED": OrderStatus.DELIVERED,
            }[facts.stage]
        )
    product = value.product
    return BuyerOrder(
        order_id=value.orderId,
        status=status,
        placed_at=value.createdAt.astimezone(zone),
        items=[
            OrderItem(
                product_id=product.productId,
                title=product.name,
                quantity=product.quantity,
                price=product.unitPriceMinor / 100,
            )
        ],
        total=product.totalPriceMinor / 100,
        currency=product.currency,
        estimated_delivery=fulfillment["estimatedDeliveryAt"] if fulfillment else None,
        tracking_url=None,
        payment_status=value.status,
        payment=payment,
        refunds=value.refunds.model_dump(mode="json"),
        fulfillment=fulfillment,
        product_snapshot=product.model_dump(mode="json"),
    )


def price_bound(value: float | None, *, minimum: bool) -> int | None:
    if value is None:
        return None
    amount = Decimal(str(value)) * 100
    if not amount.is_finite() or amount < 0:
        raise CommerceError(400, "VALIDATION", "Price filter must be a finite nonnegative amount")
    return int(amount.to_integral_value(rounding=ROUND_CEILING if minimum else ROUND_FLOOR))


CART_REJECTIONS = {
    "VALIDATION",
    "NOT_FOUND",
    "AUTHENTICATION",
    "AUTHORIZATION",
    "IDEMPOTENCY_CONFLICT",
    "VERSION_CONFLICT",
    "QUANTITY_LIMIT",
    "CART_LIMIT",
    "NOT_ORDERABLE",
    "CURRENCY_CONFLICT",
    "AMOUNT_LIMIT",
}
TOOL_OPERATIONS = {"add_to_cart": "ADD", "update_cart_item": "SET", "remove_from_cart": "REMOVE"}


class CityBuddyStorefrontBackend(StorefrontBackend):
    def __init__(self, auth, store, client, commands, *, web_search=None):
        self.auth, self.store, self.client, self.commands = auth, store, client, commands
        self.web_search = web_search

    @staticmethod
    def _bound(session):
        context = current_context()
        if (
            context.role != "buyer"
            or context.session_id != session.session_id
            or context.identity.subject != session.user_id
        ):
            raise CommerceError(403, "CONTEXT_MISMATCH", "Buyer session context does not match")
        return context

    async def _token(self, session, scope):
        context = self._bound(session)
        return await self.auth.exchange_shopping(context.identity, session.session_id, scope)

    async def search_products(self, session, query, filters: SearchFilters | None = None, limit=8):
        identity = self._bound(session).identity
        filters = filters or SearchFilters()
        body = {
            "query": query,
            "category": filters.category,
            "attributes": filters.attributes,
            "minPriceMinor": price_bound(filters.min_price, minimum=True),
            "maxPriceMinor": price_bound(filters.max_price, minimum=False),
            "minRating": filters.min_rating,
            "sort": filters.sort,
            "limit": limit,
            "currency": "CNY",
        }
        return [
            product_details(value)
            for value in await self.client.search_products(identity.token, body)
        ]

    async def products_page(self, session, query="", limit=24, offset=0):
        token = self._bound(session).identity.token
        values = (
            await self.client.search_products(
                token, {"query": query, "limit": limit, "offset": offset}
            )
            if query
            else await self.client.products(token, limit=limit, offset=offset)
        )
        return {
            "products": [product_details(value).model_dump(mode="json") for value in values],
            "next_offset": offset + limit if len(values) == limit else None,
        }

    async def get_product_details(self, session, product_id):
        value = await self.client.product(product_id, self._bound(session).identity.token)
        return None if value is None else product_details(value)

    async def _cart(self, session):
        return await self.client.cart(
            await self._token(session, "shopping:cart:read"), session.session_id
        )

    async def get_cart(self, session):
        return shopping_cart(await self._cart(session))

    @staticmethod
    def _envelope(cart: CartView, command=None):
        result = {"cart": cart_payload(shopping_cart(cart)), "quote": cart.model_dump(mode="json")}
        if command is not None:
            result["command"] = command.public()
        return result

    async def cart_envelope(self, session):
        return self._envelope(await self._cart(session))

    async def _recover(self, session, command):
        context = self._bound(session)
        self.store.get(command.session_id, context.identity.subject, role="buyer")
        if command.result is None and command.rejection is None:
            token = await self.auth.exchange_shopping(
                context.identity, command.session_id, "shopping:cart:read"
            )
            result = await self.client.cart_command(command.key, token, command.session_id)
            if result is not None:
                self._complete(command, result)
        return self.commands.get(command.key, command.session_id, context.identity.subject)

    def _complete(self, command, result):
        if result.receipt.key != command.key or result.receipt.operation != command.operation:
            raise CommerceError(
                502, "INVALID_RESPONSE", "Cart receipt does not match the original command"
            )
        self.commands.complete(command, result.model_dump(mode="json"))

    async def recover_cart_commands(self, session):
        owner = self._bound(session).identity.subject
        return [
            (await self._recover(session, command)).public()
            for command in self.commands.unknown_cart(owner)
        ]

    async def _write(self, session, command):
        token = await self._token(session, "shopping:cart:write")
        body = command.body
        try:
            if command.operation == "ADD":
                result = await self.client.cart_add(
                    token, session.session_id, command.key, body["productId"], body["quantity"]
                )
            elif command.operation == "SET":
                result = await self.client.cart_set(
                    token,
                    session.session_id,
                    command.key,
                    body["productId"],
                    body["quantity"],
                    body["expectedCartVersion"],
                )
            elif command.operation == "REMOVE":
                result = await self.client.cart_remove(
                    token,
                    session.session_id,
                    command.key,
                    body["productId"],
                    body["expectedCartVersion"],
                )
            else:
                raise ValueError("Unsupported persisted cart operation")
        except CommerceError as error:
            if (
                error.status_code in (400, 401, 403, 404, 409, 413, 422)
                and error.category in CART_REJECTIONS
            ):
                self.commands.reject(command, error.category)
            raise
        self._complete(command, result)
        return result.cart

    async def command_envelope(self, session, key, retry=False):
        owner = self._bound(session).identity.subject
        command = self.commands.get(key, session.session_id, owner)
        if command.kind != "cart":
            raise CommerceError(400, "VALIDATION", "This endpoint only handles cart commands")
        command = await self._recover(session, command)
        if retry and command.result is None and command.rejection is None:
            await self._write(session, command)
            command = self.commands.get(key, session.session_id, owner)
        return self._envelope(await self._cart(session), command)

    async def cart_mutation(self, session, operation, body, key):
        context = self._bound(session)
        if operation not in {"ADD", "SET", "REMOVE"}:
            raise CommerceError(400, "VALIDATION", "Unsupported cart operation")
        prior = next(
            (
                item
                for item in self.commands.list(session.session_id, session.user_id, kind="cart")
                if item.key == key
            ),
            None,
        )
        if prior is not None:
            self.commands.require_same_call(prior, "cart", operation, body)
            return await self.command_envelope(session, key)
        command = self.commands.register(
            session_id=session.session_id,
            owner=session.user_id,
            turn_id=context.turn_id or "ui",
            call_id="ui:" + key,
            kind="cart",
            operation=operation,
            arguments=body,
            body=body,
            key=key,
        )
        cart = await self._write(session, command)
        return self._envelope(
            cart, self.commands.get(command.key, session.session_id, session.user_id)
        )

    async def _tool_write(self, session, operation, product_id, quantity=None):
        context = self._bound(session)
        call = current_tool_call.get(None)
        if call is None or context.turn_id is None or TOOL_OPERATIONS.get(call.name) != operation:
            raise CommerceError(
                400, "MISSING_TOOL_CONTEXT", "Cart write requires its original tool call"
            )
        arguments = {key: value for key, value in call.arguments.items() if key != "status"}
        existing = self.commands.by_call(
            session.session_id, session.user_id, context.turn_id, call.tool_use_id
        )
        if existing is not None:
            self.commands.require_same_call(existing, "cart", operation, arguments)
            existing = await self._recover(session, existing)
            if existing.result is None:
                raise CommerceError(
                    409,
                    existing.rejection or "RESULT_UNCONFIRMED",
                    "Original cart command was not confirmed; use its explicit retry action",
                )
            return shopping_cart(await self._cart(session))
        body = {"productId": product_id}
        if operation != "REMOVE":
            body["quantity"] = quantity
        if operation != "ADD":
            body["expectedCartVersion"] = (await self._cart(session)).version
        command = self.commands.register(
            session_id=session.session_id,
            owner=session.user_id,
            turn_id=context.turn_id,
            call_id=call.tool_use_id,
            kind="cart",
            operation=operation,
            arguments=arguments,
            body=body,
        )
        try:
            return shopping_cart(await self._write(session, command))
        except CommerceError as error:
            if error.category == "NOT_ORDERABLE":
                raise Unavailable(f"{product_id} is currently not purchasable") from None
            raise

    async def add_to_cart(self, session, product_id, quantity):
        return await self._tool_write(session, "ADD", product_id, quantity)

    async def update_cart_item(self, session, product_id, quantity):
        return await self._tool_write(session, "SET", product_id, quantity)

    async def remove_from_cart(self, session, product_id):
        return await self._tool_write(session, "REMOVE", product_id)

    async def get_preferences(self, session):
        value = await self.client.preferences(
            await self._token(session, "shopping:profile:read"), session.session_id
        )
        return UserPreferences(
            user_id=value.userId,
            display_name=value.displayName,
            loyalty_tier=value.loyaltyTier,
            default_location=value.defaultLocation,
            preferences=value.preferences,
        )

    async def get_orders(self, session, limit=5):
        values = await self.client.orders(
            await self._token(session, "shopping:orders:read"), session.session_id, limit=limit
        )
        return [shopping_order(value) for value in values]

    async def get_order(self, session, order_id):
        value = await self.client.order(
            order_id, await self._token(session, "shopping:orders:read"), session.session_id
        )
        return None if value is None else shopping_order(value)

    async def search_policies(self, session, query):
        values = await self.client.policies(query, self._bound(session).identity.token)
        return [
            Policy(
                policy_id=value.policyId,
                title=value.title,
                category=value.category,
                content=value.content,
            )
            for value in values
        ]

    async def get_fulfillment_options(self, session, product_ids):
        token = self._bound(session).identity.token
        products = await asyncio.gather(
            *(self.client.product(identifier, token) for identifier in dict.fromkeys(product_ids))
        )
        if any(value is not None and value.kind == "family" for value in products):
            raise NotOffered("配送估算需要先选择实际商品规格")
        items = [
            {"productId": value.productId, "quantity": 1} for value in products if value is not None
        ]
        if product_ids and not items:
            return []
        try:
            estimate = await self.client.delivery(items, token)
        except CommerceError as error:
            if error.status_code == 422 and error.category in {
                "unsupported_currency",
                "sku_unavailable",
            }:
                raise NotOffered("所选商品当前无法提供配送估算") from None
            raise
        return self._delivery_options(estimate)

    async def delivery_cart(self, session):
        context = self._bound(session)
        cart = await self._cart(session)
        if not cart.checkoutReady:
            raise CommerceError(
                409, "NOT_ORDERABLE", "The current cart cannot be quoted for delivery"
            )
        estimate = await self.client.delivery(
            [{"productId": item.productId, "quantity": item.quantity} for item in cart.items],
            context.identity.token,
        )
        return {
            "estimate": estimate.model_dump(mode="json"),
            "options": [
                option.model_dump(mode="json") for option in self._delivery_options(estimate)
            ],
        }

    @staticmethod
    def _delivery_options(estimate):
        options = []
        for option in estimate.options:
            eta = (
                option.readyAt.astimezone(ZoneInfo(estimate.timeZone)).isoformat()
                if option.readyAt
                else f"{option.earliestDate.isoformat()} 至 {option.latestDate.isoformat()} ({estimate.timeZone})"
            )
            options.append(
                BuyerFulfillmentOption(
                    method=option.method,
                    eta=eta,
                    fee=option.feeMinor / 100,
                    location=option.location,
                    code=option.code,
                    currency=estimate.currency,
                    estimate_only=estimate.estimateOnly,
                    quoted_at=estimate.quotedAt.isoformat(),
                )
            )
        return options
