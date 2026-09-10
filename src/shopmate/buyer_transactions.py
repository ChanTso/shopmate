"""User-confirmed checkout/payment and model-prepared, user-confirmed refunds."""

from __future__ import annotations

import time
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import HTTPException

from .auth import current_context
from .buyer_client import CheckoutCommand, RefundArguments
from .buyer_commands import BuyerCommand, BuyerCommands
from .commerce_client import CommerceError


def definitive_refusal(error: CommerceError) -> bool:
    return error.status_code in (400, 401, 403, 404, 409, 422) and error.category not in {
        "INDETERMINATE",
        "INCONSISTENT_DURABLE_STATE",
        "RETRYABLE_CONCURRENCY",
        "retryable_concurrency",
        "COMMERCE_ERROR",
    }


class BuyerTransactions:
    def __init__(self, auth, client, commands: BuyerCommands, settings):
        self.auth, self.client, self.commands, self.settings = auth, client, commands, settings

    def _bound(self, session):
        bound = current_context()
        if (
            bound.role != "buyer"
            or bound.session_id != session.session_id
            or bound.identity.subject != session.user_id
        ):
            raise HTTPException(403, "Buyer session mismatch")
        return bound

    async def _read_token(self, session):
        bound = self._bound(session)
        return await self.auth.exchange_shopping(
            bound.identity, session.session_id, "shopping:orders:read"
        )

    async def create_checkout(self, session, key, body):
        bound = self._bound(session)
        body = CheckoutCommand.model_validate(body).model_dump(mode="json")
        command = self.commands.register(
            session_id=session.session_id,
            owner=session.user_id,
            source_conversation=bound.conversation_id,
            turn_id="user-checkout",
            call_id=key,
            kind="checkout",
            operation="CHECKOUT",
            arguments=body,
            body=body,
            key=key,
        )
        return await self._submit_checkout(session, bound, command)

    async def retry_checkout(self, session, key):
        bound = self._bound(session)
        command = self.commands.get(key, session.session_id, session.user_id)
        if command.kind != "checkout":
            raise HTTPException(404, "Checkout command not found")
        return await self._submit_checkout(session, bound, command)

    async def _submit_checkout(self, session, bound, command):
        if command.rejection:
            raise CommerceError(
                409,
                command.rejection,
                "The original checkout was rejected; review the current cart",
            )
        if command.result is not None:
            checkout = await self.checkout(session, command.result["checkoutId"])
        else:
            try:
                checkout = await self.client.create_checkout(
                    bound.identity.token,
                    command.key,
                    command.body,
                    correlation_id=command.key,
                )
            except CommerceError as error:
                if definitive_refusal(error):
                    self.commands.reject(command, error.category)
                raise
            self.commands.complete(command, checkout.model_dump(mode="json"))
        return {
            "checkout": checkout.model_dump(mode="json"),
            "command": self.commands.get(command.key, session.session_id, session.user_id).public(),
        }

    def _checkout_ref(self, session, checkout_id):
        self._bound(session)
        for command in self.commands.list(session.session_id, session.user_id, kind="checkout"):
            if command.result is not None and command.result["checkoutId"] == checkout_id:
                return command
        raise HTTPException(404, "Checkout not found for this buyer")

    async def checkout(self, session, checkout_id):
        self._checkout_ref(session, checkout_id)
        result = await self.client.checkout(
            checkout_id, await self._read_token(session), session.session_id
        )
        if result is None:
            raise HTTPException(404, "Checkout not found")
        return result

    async def checkouts(self, session):
        result = []
        for command in self.commands.list(session.session_id, session.user_id, kind="checkout"):
            if command.result is not None:
                result.append(
                    (await self.checkout(session, command.result["checkoutId"])).model_dump(
                        mode="json"
                    )
                )
        return result

    async def pay(self, session, checkout_id):
        bound = self._bound(session)
        command = self._checkout_ref(session, checkout_id)
        if not self.settings.payment_callback_secret:
            raise HTTPException(503, "Mock payment callback is not configured")
        checkout = await self.checkout(session, checkout_id)
        progress = self.commands.confirmation(command) or {"payments": {}}
        for order in checkout.orders:
            if order.status == "PAID":
                continue
            if order.status != "UNPAID":
                raise HTTPException(
                    409, "An original order cannot be paid; inspect checkout status"
                )
            identity = str(uuid5(NAMESPACE_URL, f"shopmate:{checkout_id}:{order.orderId}"))
            payment = progress["payments"].get(order.orderId)
            if payment is None:
                attempt = await self.client.start_payment(
                    order.orderId,
                    bound.identity.token,
                    "pay-" + identity,
                    order.product.totalPriceMinor,
                    checkout.currency,
                )
                payment = {"attempt": attempt.model_dump(mode="json")}
                progress["payments"][order.orderId] = payment
                self.commands.confirm(command, progress)
            attempt = payment["attempt"]
            body = {
                "callbackEventId": identity,
                "callbackCorrelationId": attempt["callbackCorrelationId"],
                "orderId": order.orderId,
                "amountMinor": attempt["amountMinor"],
                "currency": attempt["currency"],
                "outcome": "SUCCEEDED",
            }
            # Event, amount and correlation persist across interruption; only the signature time changes.
            callback = await self.client.payment_callback(
                body,
                "callback-" + identity,
                key_id="shopmate-local-payment",
                secret=self.settings.payment_callback_secret,
                timestamp=int(time.time()),
            )
            payment["callback"] = callback.model_dump(mode="json")
            self.commands.confirm(command, progress)
        return (await self.checkout(session, checkout_id)).model_dump(mode="json")

    async def prepare_refund(self, session, arguments, *, call_id, key=None):
        bound = self._bound(session)
        arguments = RefundArguments.model_validate(arguments).model_dump(mode="json")
        command = self.commands.register(
            session_id=session.session_id,
            owner=session.user_id,
            source_conversation=bound.conversation_id,
            turn_id=bound.turn_id or "user-refund",
            call_id=call_id,
            kind="refund",
            operation="REFUND_REQUEST",
            arguments=arguments,
            body={
                "request": {"actionType": "REFUND_REQUEST", "arguments": arguments},
                "trace_id": str(uuid4()),
                "action_turn_id": str(uuid4()),
            },
            key=key,
        )
        return await self._submit_refund(session, bound, command)

    async def retry_refund(self, session, key):
        bound = self._bound(session)
        command = self.commands.get(key, session.session_id, session.user_id)
        if command.kind != "refund":
            raise HTTPException(404, "Refund command not found")
        return await self._submit_refund(session, bound, command)

    async def _submit_refund(self, session, bound, command):
        if command.rejection:
            raise CommerceError(
                409, command.rejection, "The original refund preparation was rejected"
            )
        if command.result is None:
            token = await self.auth.exchange_shopping(
                bound.identity, command.session_id, "refund:create"
            )
            try:
                action = await self.client.prepare_refund(
                    token,
                    command.session_id,
                    command.body["trace_id"],
                    command.body["action_turn_id"],
                    command.body["request"],
                )
            except CommerceError as error:
                if definitive_refusal(error):
                    self.commands.reject(command, error.category)
                raise
            self.commands.complete(command, action.model_dump(mode="json"))
        command = self.commands.get(command.key, session.session_id, session.user_id)
        return {"action": command.result, "command": command.public()}

    def _action_ref(self, session, action_id):
        self._bound(session)
        for command in self.commands.list(session.session_id, session.user_id, kind="refund"):
            if command.result is not None and command.result["pendingActionId"] == action_id:
                return command
        raise HTTPException(404, "Refund action not found for this buyer")

    def actions(self, session):
        self._bound(session)
        return [
            {"action": c.result, "receipt": self.commands.confirmation(c)}
            for c in self.commands.list(session.session_id, session.user_id, kind="refund")
            if c.result is not None
        ]

    async def confirm_refund(self, session, action_id):
        bound = self._bound(session)
        command: BuyerCommand = self._action_ref(session, action_id)
        # Always ask Java to replay its receipt; Python never declares refund execution from a draft.
        token = await self.auth.exchange_shopping(
            bound.identity, command.session_id, "refund:create"
        )
        receipt = await self.client.confirm_refund(
            action_id,
            token,
            command.session_id,
            command.body["trace_id"],
            command.body["action_turn_id"],
        )
        result = receipt.model_dump(mode="json")
        self.commands.confirm(command, result)
        return result
