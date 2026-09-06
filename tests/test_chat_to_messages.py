"""Local fake-provider checks only; no network and no provider acceptance claim."""

from __future__ import annotations

import asyncio
import json
import unittest

import anthropic
import httpx

from shopmate.providers.chat_to_messages import (
    ChatCompatibilityError,
    make_client,
    translate_request,
    translate_response,
)


def chunk(delta=None, finish=None, usage=None):
    value = {"id": "fixture-response", "model": "fixture-model", "choices": []}
    if delta is not None or finish is not None:
        value["choices"] = [{"index": 0, "delta": delta or {}, "finish_reason": finish}]
    if usage is not None:
        value["usage"] = usage
    return value


class FakeStream(httpx.AsyncByteStream):
    def __init__(self, chunks, stop_observer=None):
        self.chunks = chunks
        self.finished = False
        self.closed = False
        self.stop_observer = stop_observer

    async def __aiter__(self):
        for item in self.chunks:
            if self.stop_observer is not None:
                assert not self.stop_observer(), (
                    "tool closed before the upstream response completed"
                )
            yield ("data: " + json.dumps(item) + "\n\n").encode()
            await asyncio.sleep(0)
        self.finished = True
        yield b"data: [DONE]\n\n"

    async def aclose(self):
        self.closed = True


class CompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def open_client(self, response):
        async def handle(request):
            self.assertEqual(request.url.path, "/v1/chat/completions")
            self.assertEqual(request.headers["authorization"], "Bearer fixture-key")
            self.assertNotIn("x-api-key", request.headers)
            self.assertNotIn("anthropic-beta", request.headers)
            body = json.loads(request.content)
            self.assertEqual(body["max_completion_tokens"], 50)
            self.assertNotIn("max_tokens", body)
            self.assertNotIn("thinking", body)
            return response

        client = make_client(
            "https://fixture.invalid/v1",
            "fixture-key",
            upstream_transport=httpx.MockTransport(handle),
        )
        self.addAsyncCleanup(client.close)
        return client

    async def consume(self, chunks):
        source = FakeStream(chunks)
        client = await self.open_client(
            httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=source)
        )
        events = []
        async with client.messages.stream(
            model="fixture-model", max_tokens=50, messages=[{"role": "user", "content": "fixture"}]
        ) as stream:
            async for event in stream:
                events.append(event)
            message = await stream.get_final_message()
        return source, client, events, message

    async def test_sdk_request_explicitly_preserves_optional_tool_fields(self):
        from merchant_agent.tools.registry import build_tools

        from shopmate.backend import ShopMateConfig

        tool = next(t for t in build_tools(ShopMateConfig(), []) if t["name"] == "search_listings")
        original = json.dumps(tool, sort_keys=True)

        async def handle(request):
            function = json.loads(request.content)["tools"][0]["function"]
            self.assertIs(function["strict"], False)
            self.assertEqual(function["parameters"], tool["input_schema"])
            self.assertNotIn("filters", function["parameters"]["required"])
            self.assertIn("category", function["parameters"]["properties"]["filters"]["properties"])
            return httpx.Response(
                200,
                json={
                    "choices": [
                        {
                            "finish_reason": "tool_calls",
                            "message": {
                                "tool_calls": [
                                    {
                                        "id": "lookup",
                                        "type": "function",
                                        "function": {
                                            "name": "search_listings",
                                            "arguments": '{"query":"coffee"}',
                                        },
                                    }
                                ],
                            },
                        }
                    ],
                },
            )

        client = make_client(
            "https://fixture.invalid/v1",
            "fixture-key",
            upstream_transport=httpx.MockTransport(handle),
        )
        self.addAsyncCleanup(client.close)
        response = await client.messages.create(
            model="fixture-model",
            max_tokens=50,
            tools=[tool],
            messages=[{"role": "user", "content": "Find coffee"}],
        )
        self.assertEqual(response.content[0].input, {"query": "coffee"})
        self.assertEqual(json.dumps(tool, sort_keys=True), original)

    def test_explicit_strict_tool_is_not_silently_downgraded(self):
        body = translate_request(
            {
                "model": "fixture-model",
                "max_tokens": 50,
                "messages": [],
                "tools": [
                    {
                        "name": "one",
                        "strict": True,
                        "input_schema": {
                            "type": "object",
                            "properties": {},
                            "additionalProperties": False,
                        },
                    }
                ],
            }
        )
        self.assertIs(body["tools"][0]["function"]["strict"], True)

    async def test_text_and_usage(self):
        source, client, _events, message = await self.consume(
            [
                chunk({"content": "first "}),
                chunk({"content": "second"}, "stop"),
                chunk(
                    usage={
                        "prompt_tokens": 20,
                        "completion_tokens": 4,
                        "prompt_tokens_details": {"cached_tokens": 5},
                    }
                ),
            ]
        )
        self.assertEqual(message.content[0].text, "first second")
        self.assertEqual(message.usage.input_tokens, 15)
        self.assertEqual(message.usage.cache_read_input_tokens, 5)
        self.assertEqual(message.usage.output_tokens, 4)
        self.assertTrue(source.closed)
        self.assertEqual(client._chat_compat_transport.observations[0]["text_delta_count"], 2)

    async def test_cache_presence_is_separate_from_sdk_zero_in_both_response_modes(self):
        for streaming in (False, True):
            for details, available, cached in (
                (None, False, 0),
                ({"cached_tokens": None}, False, 0),
                ({"cached_tokens": 0}, True, 0),
                ({"cached_tokens": 5}, True, 5),
            ):
                with self.subTest(streaming=streaming, details=details):
                    usage = {"prompt_tokens": 20, "completion_tokens": 4}
                    if details is not None:
                        usage["prompt_tokens_details"] = details
                    if streaming:
                        _, client, _, message = await self.consume(
                            [chunk({"content": "ok"}, "stop"), chunk(usage=usage)]
                        )
                    else:
                        client = await self.open_client(
                            httpx.Response(
                                200,
                                json={
                                    "choices": [
                                        {"finish_reason": "stop", "message": {"content": "ok"}}
                                    ],
                                    "usage": usage,
                                },
                            )
                        )
                        message = await client.messages.create(
                            model="fixture-model",
                            max_tokens=50,
                            messages=[{"role": "user", "content": "fixture"}],
                        )
                    observation = client._chat_compat_transport.observations[0]
                    self.assertIs(observation["usage_available"], True)
                    self.assertIs(observation["cache_read_usage_available"], available)
                    self.assertIs(observation["cache_creation_usage_available"], False)
                    self.assertEqual(message.usage.input_tokens, 20 - cached)
                    self.assertEqual(message.usage.cache_read_input_tokens, cached)
                    self.assertEqual(message.usage.output_tokens, 4)

    async def test_interleaved_tools_and_no_early_stop(self):
        stopped = []
        pieces = [
            chunk(
                {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_a",
                            "type": "function",
                            "function": {"name": "one", "arguments": '{"x":1}'},
                        }
                    ]
                }
            ),
            chunk(
                {
                    "tool_calls": [
                        {
                            "index": 1,
                            "id": "call_b",
                            "type": "function",
                            "function": {"name": "two", "arguments": '{"y":'},
                        }
                    ]
                }
            ),
            chunk(
                {
                    "tool_calls": [
                        {"index": 0, "function": {"arguments": " "}},
                        {"index": 1, "function": {"arguments": "2}"}},
                    ]
                }
            ),
            chunk({}, "tool_calls"),
            chunk(usage={"prompt_tokens": 20, "completion_tokens": 8}),
        ]
        source = FakeStream(pieces, lambda: stopped)
        client = await self.open_client(
            httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=source)
        )
        deltas = []
        async with client.messages.stream(
            model="fixture-model", max_tokens=50, messages=[{"role": "user", "content": "fixture"}]
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    self.assertFalse(source.finished)
                    deltas.append(event.delta.partial_json)
                if event.type == "content_block_stop":
                    self.assertTrue(source.finished)
                    stopped.append(event.index)
            message = await stream.get_final_message()
        self.assertEqual(deltas, ['{"x":1}', '{"y":', " ", "2}"])
        self.assertEqual([b.input for b in message.content], [{"x": 1}, {"y": 2}])
        self.assertEqual(message.stop_reason, "tool_use")

    async def test_length_with_parseable_tool_does_not_execute(self):
        with self.assertRaises(ChatCompatibilityError):
            await self.consume(
                [
                    chunk(
                        {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "a",
                                    "type": "function",
                                    "function": {"name": "write", "arguments": '{"x":1}'},
                                }
                            ]
                        }
                    ),
                    chunk({}, "length"),
                ]
            )

    async def test_missing_finish_is_not_success(self):
        with self.assertRaises(ChatCompatibilityError):
            await self.consume([chunk({"content": "unfinished"})])

    async def test_duplicate_tool_ids_rejected_in_stream_and_create(self):
        calls = [
            {
                "index": index,
                "id": "same",
                "type": "function",
                "function": {"name": name, "arguments": "{}"},
            }
            for index, name in enumerate(("one", "two"))
        ]
        with self.assertRaises(ChatCompatibilityError):
            await self.consume([chunk({"tool_calls": calls}), chunk({}, "tool_calls")])
        with self.assertRaises(ChatCompatibilityError):
            translate_response(
                {"choices": [{"message": {"tool_calls": calls}, "finish_reason": "tool_calls"}]},
                "fixture-model",
            )

    async def test_nonstream_analysis_tool_call(self):
        client = await self.open_client(
            httpx.Response(
                200,
                json={
                    "id": "create-id",
                    "model": "fixture-model",
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": None,
                                "tool_calls": [
                                    {
                                        "id": "query-id",
                                        "type": "function",
                                        "function": {
                                            "name": "execute_analysis_query",
                                            "arguments": '{"sql":"SELECT 1"}',
                                        },
                                    },
                                ],
                            },
                            "finish_reason": "tool_calls",
                        }
                    ],
                    "usage": {"prompt_tokens": 30, "completion_tokens": 9},
                },
            )
        )
        response = await client.messages.create(
            model="fixture-model", max_tokens=50, messages=[{"role": "user", "content": "fixture"}]
        )
        self.assertEqual(response.content[0].input, {"sql": "SELECT 1"})
        self.assertEqual(response.content[0].id, "query-id")
        self.assertEqual(response.stop_reason, "tool_use")

    async def test_safe_http_error(self):
        client = await self.open_client(
            httpx.Response(503, text="PRIVATE upstream body fixture-key https://secret.invalid")
        )
        with self.assertRaises(anthropic.APIStatusError) as raised:
            await client.messages.create(
                model="fixture-model",
                max_tokens=50,
                messages=[{"role": "user", "content": "fixture"}],
            )
        self.assertEqual(raised.exception.status_code, 503)
        self.assertNotIn("PRIVATE", str(raised.exception))
        self.assertNotIn("fixture-key", str(raised.exception))
        self.assertNotIn("secret.invalid", str(raised.exception))
        observation = client._chat_compat_transport.observations[0]
        self.assertEqual(observation["error_category"], "provider_http")
        self.assertEqual(observation["http_status"], 503)
        self.assertNotIn("PRIVATE", json.dumps(observation))

    async def test_transport_failure_is_distinct_and_does_not_expose_exception_body(self):
        async def broken(request):
            raise httpx.ConnectError("PRIVATE credential fixture-key", request=request)

        client = make_client(
            "https://fixture.invalid/v1",
            "fixture-key",
            upstream_transport=httpx.MockTransport(broken),
        )
        self.addAsyncCleanup(client.close)
        with self.assertRaises(anthropic.APIConnectionError) as raised:
            await client.messages.create(
                model="fixture-model",
                max_tokens=50,
                messages=[{"role": "user", "content": "fixture"}],
            )
        observation = client._chat_compat_transport.observations[0]
        self.assertEqual(observation["error_category"], "provider_transport")
        self.assertNotIn("http_status", observation)
        self.assertNotIn("PRIVATE", str(raised.exception))
        self.assertNotIn("fixture-key", json.dumps(observation))

    async def test_missing_usage_is_explicitly_unknown(self):
        _, client, _, _ = await self.consume([chunk({"content": "ok"}, "stop")])
        self.assertFalse(client._chat_compat_transport.observations[0]["usage_available"])

    def test_request_history_and_native_options(self):
        translated = translate_request(
            {
                "model": "fixture-model",
                "max_tokens": 50,
                "stream": True,
                "system": [
                    {"type": "text", "text": "system", "cache_control": {"type": "ephemeral"}}
                ],
                "thinking": {"type": "enabled", "budget_tokens": 20},
                "output_config": {"effort": "high"},
                "tools": [
                    {
                        "name": "one",
                        "description": "read",
                        "input_schema": {"type": "object"},
                        "cache_control": {"type": "ephemeral"},
                        "eager_input_streaming": True,
                    }
                ],
                "tool_choice": {"type": "tool", "name": "one"},
                "messages": [
                    {"role": "user", "content": "start"},
                    {
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "id": "id", "name": "one", "input": {"x": 1}}
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": "id",
                                "content": [{"type": "text", "text": "receipt"}],
                            },
                            {"type": "text", "text": "follow-up"},
                        ],
                    },
                ],
            }
        )
        self.assertEqual(
            [m["role"] for m in translated["messages"]],
            ["system", "user", "assistant", "tool", "user"],
        )
        self.assertEqual(translated["messages"][3]["tool_call_id"], "id")
        self.assertEqual(translated["messages"][3]["content"], "receipt")
        self.assertEqual(
            translated["tool_choice"], {"type": "function", "function": {"name": "one"}}
        )
        serialized = json.dumps(translated)
        for field in ["cache_control", "thinking", "output_config", "eager_input_streaming"]:
            self.assertNotIn(field, serialized)


if __name__ == "__main__":
    unittest.main(verbosity=2)
