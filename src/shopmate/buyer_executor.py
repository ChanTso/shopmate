"""Deployment tools around the upstream shopping executor, without a second model loop."""

from __future__ import annotations

from commerce_common.execution import clamp_limit
from commerce_common.streaming import AgentEvent, ToolOutcome
from commerce_common.turn import current_tool_call
from fastapi import HTTPException
from pydantic import ValidationError
from shopping_agent.executor import MAX_ORDERS, ShoppingToolExecutor
from shopping_agent.gates import remember_order_items

from .auth import current_context
from .buyer_client import RefundArguments
from .commerce_client import CommerceError
from .memory import MemoryChanged
from .provider import TaskBudgetExceeded
from .search_tool import execute_search
from .web_search import SearchUnavailable

CART_TOOLS = {"add_to_cart", "update_cart_item", "remove_from_cart"}
CART_OPERATIONS = {"add_to_cart": "ADD", "update_cart_item": "SET", "remove_from_cart": "REMOVE"}

REFUND_TOOL = {
    "name": "prepare_refund",
    "description": (
        "Prepare a refund for the customer's exact requested amount and currency. Follow the "
        "amount_minor unit rules below; never replace it with the order total or another amount. "
        "Ask if the amount or unit is unclear. Java checks ownership, payment and remaining "
        "refundable amount. This does "
        "not submit a refund: present the returned confirmation card, and the customer must click "
        "its confirmation button. Never claim the money has been returned."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "order_id": {"type": "string"},
            "amount_minor": {
                "type": "integer",
                "minimum": 1,
                "description": (
                    "Exact requested refund in integer minor units, not display currency units. "
                    "For CNY, 1 yuan (元) = 100 fen (分): '100 分 CNY' means amount_minor=100 "
                    "(¥1.00), while '100 元 CNY' means amount_minor=10000 (¥100.00). "
                    "If already stated in 分, cents, or minor units, keep that integer; do not "
                    "multiply it by 100 again. Fields ending in Minor already use this unit."
                ),
            },
            "currency": {
                "type": "string",
                "pattern": "^[A-Z]{3}$",
                "description": "Requested ISO currency code matching the order; do not convert currencies.",
            },
        },
        "required": ["order_id", "amount_minor", "currency"],
        "additionalProperties": False,
    },
}


class BuyerToolExecutor(ShoppingToolExecutor):
    async def execute(self, name, tool_input):
        # A replay must bypass the quantity gate: the first execution may have filled the cart.
        if name in CART_TOOLS:
            try:
                call = current_tool_call.get()
                bound = current_context()
                arguments, _ = self.split_status(name, dict(tool_input or {}))
                command = self._backend.commands.by_call(
                    bound.session_id, bound.identity.subject, bound.turn_id, call.tool_use_id
                )
                if command is not None:
                    self._backend.commands.require_same_call(
                        command, "cart", CART_OPERATIONS[name], arguments
                    )
                    envelope = await self._backend.command_envelope(self._session, command.key)
                    state = envelope["command"]["state"]
                    if state == "confirmed":
                        return self._fenced(
                            {"recovered_command": envelope["command"], "cart": envelope["cart"]},
                            [AgentEvent.cart_update(envelope["cart"])],
                        )
                    if state == "rejected":
                        return ToolOutcome.error(
                            "The original cart command was rejected. Review the current cart before another change."
                        )
                    return ToolOutcome.error(
                        "The original cart operation is unconfirmed. Do not issue a new cart write. "
                        "Ask the customer to check or explicitly continue the original command in the cart panel."
                    )
            except (HTTPException, CommerceError) as error:
                return self.domain_error(error)
        return await super().execute(name, tool_input)

    def domain_error(self, error):
        if isinstance(error, TaskBudgetExceeded):
            raise error
        if isinstance(error, (HTTPException, CommerceError, MemoryChanged, SearchUnavailable)):
            message = error.detail if hasattr(error, "detail") else str(error)
            return ToolOutcome.error(self._sanitize(message, 300))
        return super().domain_error(error)

    def handlers(self):
        return super().handlers() | {
            "prepare_refund": self._prepare_refund,
            "web_search": self._web_search,
        }

    async def _get_orders(self, arguments):
        limit = clamp_limit(arguments.get("limit"), 5, MAX_ORDERS)
        orders = await self._backend.get_orders(self._session, limit)
        remember_order_items(self._state, orders)
        # Full payment/refund/fulfillment records can truncate the entire list mid-JSON.
        # Preserve every recent order ID here; the existing detail tool returns those facts.
        summaries = [
            {
                "order_id": order.order_id,
                "status": order.status.value,
                "payment_status": order.payment_status,
                "placed_at": order.placed_at.isoformat(),
                "estimated_delivery": order.estimated_delivery,
                "items": [
                    {
                        "product_id": item.product_id,
                        "title": self._sanitize(item.title, 60),
                        "quantity": item.quantity,
                    }
                    for item in order.items
                ],
            }
            for order in orders
        ]
        return self._fenced(
            {
                "orders": summaries,
                "detail": (
                    "Recent orders only; titles are shortened summaries. Use get_order_status "
                    "with an order_id for full items, payment, refunds and fulfillment facts."
                ),
            }
        )

    async def _web_search(self, arguments):
        return await execute_search(self, arguments)

    async def _prepare_refund(self, arguments):
        if set(arguments) != {"order_id", "amount_minor", "currency"}:
            return ToolOutcome.error(
                "Refund needs order_id, integer amount_minor and currency only."
            )
        try:
            request = RefundArguments.model_validate(
                {
                    "orderId": arguments["order_id"],
                    "amountMinor": arguments["amount_minor"],
                    "currency": arguments["currency"],
                }
            )
        except ValidationError:
            return ToolOutcome.error(
                "Refund needs a valid order ID, positive integer amount_minor and currency."
            )
        result = await self._backend.transactions.prepare_refund(
            self._session,
            request.model_dump(mode="json"),
            call_id=current_tool_call.get().tool_use_id,
        )
        return self._fenced(
            {"action": result["action"], "requires_user_confirmation": True},
            [AgentEvent.ui("refund_confirmation", {"action": result["action"]})],
        )
