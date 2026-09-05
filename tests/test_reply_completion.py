"""A Chat tool-only presentation round must not suppress the requested factual reply."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from commerce_common.testing import FakeClient, text_message, tool_use_message
from merchant_agent.backend import MerchantBackend
from merchant_agent.types import ListingDetails, MerchantSessionContext
from merchant_agent_runtime import MerchantAgent

from shopmate.backend import ShopMateConfig


class ReadBackend(SimpleNamespace):
    execute_analysis_query = MerchantBackend.execute_analysis_query


@pytest.mark.parametrize(
    ("question", "answer", "read_first"),
    [
        ("读取咖啡当前售价。", "咖啡当前售价为 24.60 CNY，版本为 4。", True),
        ("请先确认要比较的日期。", "你要比较哪两个 UTC 日期区间？", False),
    ],
)
async def test_suggestion_tool_result_is_followed_by_the_requested_answer(
    question, answer, read_first
):
    backend = ReadBackend(
        get_merchant_context=AsyncMock(return_value={}),
        get_listing=AsyncMock(
            return_value=ListingDetails(
                listing_id="coffee",
                title="Coffee",
                price=24.6,
                currency="CNY",
                attributes={"publication_version": "4"},
            )
        ),
    )
    responses = []
    if read_first:
        responses.append(tool_use_message("get_listing", {"listing_id": "coffee"}))
    responses.extend(
        [
            tool_use_message("present_suggestions", {"suggestions": ["指定日期区间"]}),
            text_message(answer),
        ]
    )
    client = FakeClient(responses)
    agent = MerchantAgent(backend=backend, config=ShopMateConfig(), client=client)
    messages = [{"role": "user", "content": question}]
    session = MerchantSessionContext(session_id="s", merchant_id="m", operator="operator")

    events = [event async for event in agent.stream_turn(messages, session)]

    assert len(client.calls) == len(responses)
    assert "".join(event.data["text"] for event in events if event.type == "text_delta") == answer
    assert [event.data["component"] for event in events if event.type == "ui"] == ["suggestions"]
    assert events[-1].type == "turn_complete"
    assert messages[-1]["role"] == "assistant"
