from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from shopmate.auth import RequestIdentity, bind_context
from shopmate.buyer_client import OrderView
from shopmate.buyer_transactions import BuyerTransactions
from tests.test_buyer_client import order


def setup(status="UNPAID"):
    data = order() | {"orderKind": "SECKILL", "status": status, "payment": None}
    value = OrderView.model_validate(data)
    client = SimpleNamespace(
        order=AsyncMock(return_value=value),
        start_payment=AsyncMock(
            return_value=SimpleNamespace(
                callbackCorrelationId="persisted-correlation", amountMinor=7500, currency="CNY"
            )
        ),
        payment_callback=AsyncMock(),
    )
    auth = SimpleNamespace(exchange_shopping=AsyncMock(return_value="obo"))
    transaction = BuyerTransactions(
        auth, client, None, SimpleNamespace(payment_callback_secret="test-only")
    )
    session = SimpleNamespace(session_id="storefront", user_id="buyer")
    return transaction, client, session


async def test_payment_retry_reuses_original_attempt_and_callback_after_lost_response():
    transaction, client, session = setup()
    client.payment_callback.side_effect = [TimeoutError("response lost"), {}]
    with bind_context(RequestIdentity("buyer", "direct"), "storefront", role="buyer"):
        with pytest.raises(TimeoutError):
            await transaction.pay_order(session, "order-1")
        await transaction.pay_order(session, "order-1")
    assert client.start_payment.await_args_list[0] == client.start_payment.await_args_list[1]
    first, second = client.payment_callback.await_args_list
    assert first.args == second.args
    assert first.args[0]["callbackCorrelationId"] == "persisted-correlation"
    assert first.args[0]["amountMinor"] == 7500


@pytest.mark.parametrize("status", ["CANCELLED", "FULFILLED"])
async def test_unpayable_order_never_starts_payment(status):
    transaction, client, session = setup()
    client.order.return_value = SimpleNamespace(orderKind="SECKILL", status=status)
    with (
        bind_context(RequestIdentity("buyer", "direct"), "storefront", role="buyer"),
        pytest.raises(HTTPException, match="Order cannot be paid"),
    ):
        await transaction.pay_order(session, "order-1")
    client.start_payment.assert_not_awaited()


async def test_missing_owned_order_cannot_trigger_signed_callback():
    transaction, client, session = setup()
    client.order.return_value = None
    with (
        bind_context(RequestIdentity("buyer", "direct"), "storefront", role="buyer"),
        pytest.raises(HTTPException) as error,
    ):
        await transaction.pay_order(session, "someone-elses-order")
    assert error.value.status_code == 404
    client.payment_callback.assert_not_awaited()
