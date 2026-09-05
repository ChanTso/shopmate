"""Explicit Chat Completions to Messages SDK transport adapter.

This is NOT a native Messages endpoint. Only text and ordinary client function tools
are supported. Anthropic cache_control, thinking/output_config and eager_input_streaming
are not forwarded. Parameter deltas remain live; tool completion waits for the complete
Chat response. No credentials, endpoint, prompt, response body or tool arguments are logged.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable
from typing import Any

import anthropic
import httpx
from jiter import from_json


class ChatCompatibilityError(RuntimeError):
    """Messages contain only fixed classifications, never upstream exception text."""


NOT_FORWARDED = (
    "cache_control",
    "thinking",
    "output_config",
    "eager_input_streaming",
    "Anthropic beta headers",
    "Anthropic server tools",
)


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if content is None:
        return ""
    if not isinstance(content, list):
        raise ChatCompatibilityError("UnsupportedContent")
    parts = []
    for block in content:
        if not isinstance(block, dict) or block.get("type") != "text":
            raise ChatCompatibilityError("UnsupportedContentBlock")
        parts.append(block.get("text", ""))
    if any(not isinstance(part, str) for part in parts):
        raise ChatCompatibilityError("InvalidText")
    return "\n".join(parts)


def translate_request(body: dict[str, Any]) -> dict[str, Any]:
    messages: list[dict[str, Any]] = []
    system = _text(body.get("system"))
    if system:
        messages.append({"role": "system", "content": system})
    for message in body.get("messages", []):
        role, content = message.get("role"), message.get("content")
        if role not in {"user", "assistant"}:
            raise ChatCompatibilityError("UnsupportedRole")
        if isinstance(content, str):
            messages.append({"role": role, "content": content})
            continue
        if not isinstance(content, list):
            raise ChatCompatibilityError("UnsupportedMessage")
        if role == "assistant":
            text_parts, calls = [], []
            for block in content:
                kind = block.get("type")
                if kind == "text":
                    text_parts.append(_text([block]))
                elif kind == "tool_use":
                    calls.append(
                        {
                            "id": block["id"],
                            "type": "function",
                            "function": {
                                "name": block["name"],
                                "arguments": json.dumps(block["input"], ensure_ascii=False),
                            },
                        }
                    )
                elif kind not in {"thinking", "redacted_thinking"}:
                    raise ChatCompatibilityError("UnsupportedAssistantBlock")
            translated: dict[str, Any] = {
                "role": "assistant",
                "content": "\n".join(text_parts) or None,
            }
            if calls:
                translated["tool_calls"] = calls
            messages.append(translated)
        else:
            pending: list[str] = []
            for block in content:
                if block.get("type") == "text":
                    pending.append(_text([block]))
                elif block.get("type") == "tool_result":
                    if pending:
                        messages.append({"role": "user", "content": "\n".join(pending)})
                        pending.clear()
                    result_text = _text(block.get("content"))
                    if block.get("is_error"):
                        result_text = "Tool returned an error:\n" + result_text
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": block["tool_use_id"],
                            "content": result_text,
                        }
                    )
                else:
                    raise ChatCompatibilityError("UnsupportedUserBlock")
            if pending:
                messages.append({"role": "user", "content": "\n".join(pending)})
    request: dict[str, Any] = {
        "model": body["model"],
        "messages": messages,
        "max_completion_tokens": body["max_tokens"],
        "stream": bool(body.get("stream", False)),
    }
    for field in ("temperature", "top_p"):
        if field in body:
            request[field] = body[field]
    if body.get("stop_sequences"):
        request["stop"] = body["stop_sequences"]
    if body.get("container") is not None:
        raise ChatCompatibilityError("ServerContainerUnsupported")
    if body.get("tools"):
        tools = []
        for tool in body["tools"]:
            if tool.get("type") not in {None, "custom"} or "input_schema" not in tool:
                raise ChatCompatibilityError("ServerToolUnsupported")
            function = {"name": tool["name"], "parameters": tool["input_schema"]}
            if "description" in tool:
                function["description"] = tool["description"]
            tools.append({"type": "function", "function": function})
        request["tools"] = tools
    if "tool_choice" in body:
        choice = body["tool_choice"]
        kind = choice.get("type")
        if kind in {"auto", "none", "any"}:
            request["tool_choice"] = "required" if kind == "any" else kind
        elif kind == "tool":
            request["tool_choice"] = {"type": "function", "function": {"name": choice["name"]}}
        else:
            raise ChatCompatibilityError("UnsupportedToolChoice")
        if choice.get("disable_parallel_tool_use"):
            request["parallel_tool_calls"] = False
    if request["stream"]:
        request["stream_options"] = {"include_usage": True}
    return request


def _usage(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        # SDK requires numbers at message_start; absence is separately recorded in observations.
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
        }
    prompt, output = value.get("prompt_tokens"), value.get("completion_tokens")
    cached = (value.get("prompt_tokens_details") or {}).get("cached_tokens", 0)
    if (
        any(type(number) is not int or number < 0 for number in (prompt, output, cached))
        or cached > prompt
    ):
        raise ChatCompatibilityError("InvalidUsage")
    return {
        "input_tokens": prompt - cached,
        "output_tokens": output,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": cached,
    }


def _stop(reason: Any, has_tools: bool) -> str:
    if reason == "tool_calls" and has_tools:
        return "tool_use"
    if reason == "stop" and not has_tools:
        return "end_turn"
    if reason == "length" and not has_tools:
        return "max_tokens"
    raise ChatCompatibilityError("IncompleteOrUnsupportedFinishReason")


def _arguments(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (ValueError, TypeError):
        raise ChatCompatibilityError("InvalidToolArguments") from None
    if not isinstance(value, dict):
        raise ChatCompatibilityError("NonObjectToolArguments")
    return value


def _identity(call_id: Any, name: Any, seen: set[str]) -> None:
    if any(not isinstance(value, str) or not value.strip() for value in (call_id, name)):
        raise ChatCompatibilityError("InvalidToolIdentity")
    if call_id in seen:
        raise ChatCompatibilityError("DuplicateToolIdentity")
    seen.add(call_id)


def translate_response(body: dict[str, Any], model: str) -> dict[str, Any]:
    choices = body.get("choices", [])
    if len(choices) != 1:
        raise ChatCompatibilityError("ExpectedOneChoice")
    choice = choices[0]
    message = choice.get("message", {})
    if message.get("refusal"):
        raise ChatCompatibilityError("UpstreamRefusal")
    content = []
    if message.get("content"):
        content.append({"type": "text", "text": _text(message["content"])})
    calls = message.get("tool_calls") or []
    seen: set[str] = set()
    for call in calls:
        if call.get("type") != "function":
            raise ChatCompatibilityError("UnsupportedReturnedTool")
        _identity(call.get("id"), call.get("function", {}).get("name"), seen)
        content.append(
            {
                "type": "tool_use",
                "id": call["id"],
                "name": call["function"]["name"],
                "input": _arguments(call["function"]["arguments"]),
            }
        )
    return {
        "id": body.get("id", "chat-compat"),
        "type": "message",
        "role": "assistant",
        "model": body.get("model") or model,
        "content": content,
        "stop_reason": _stop(choice.get("finish_reason"), bool(calls)),
        "stop_sequence": None,
        "usage": _usage(body.get("usage")),
    }


def _event(kind: str, **payload: Any) -> bytes:
    return (
        "event: "
        + kind
        + "\ndata: "
        + json.dumps({"type": kind, **payload}, ensure_ascii=False)
        + "\n\n"
    ).encode()


async def _data_events(response: httpx.Response) -> AsyncIterator[str]:
    pending: list[str] = []
    async for line in response.aiter_lines():
        if line.startswith("data:"):
            pending.append(line[5:].lstrip(" "))
        elif not line and pending:
            yield "\n".join(pending)
            pending.clear()
    if pending:
        yield "\n".join(pending)


def _observe_error(observation: dict[str, Any] | None, category: str) -> None:
    if observation is not None:
        observation["error_category"] = category
        observation["elapsed_ms"] = round((time.monotonic() - observation["_started"]) * 1000)


class _MessagesStream(httpx.AsyncByteStream):
    def __init__(self, upstream: httpx.Response, model: str, observation: dict[str, Any]) -> None:
        self.upstream, self.model, self.observation = upstream, model, observation

    async def __aiter__(self) -> AsyncIterator[bytes]:
        try:
            async for item in self._events():
                yield item
        except ChatCompatibilityError:
            _observe_error(self.observation, "provider_protocol")
            raise
        except httpx.HTTPError as error:
            _observe_error(self.observation, "provider_transport")
            raise ChatCompatibilityError(type(error).__name__) from None
        except (ValueError, TypeError, KeyError) as error:
            _observe_error(self.observation, "provider_protocol")
            raise ChatCompatibilityError(type(error).__name__) from None
        finally:
            await self.upstream.aclose()

    async def _events(self) -> AsyncIterator[bytes]:
        started = False
        block_count = 0
        text_index: int | None = None
        tools: dict[int, dict[str, Any]] = {}
        finish = None
        usage = None
        async for data in _data_events(self.upstream):
            if data == "[DONE]":
                break
            try:
                chunk = json.loads(data)
            except ValueError:
                raise ChatCompatibilityError("InvalidUpstreamSSE") from None
            if "error" in chunk:
                raise ChatCompatibilityError("UpstreamStreamError")
            if not started:
                yield _event(
                    "message_start",
                    message={
                        "id": chunk.get("id", "chat-compat"),
                        "type": "message",
                        "role": "assistant",
                        "model": chunk.get("model") or self.model,
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": _usage(None),
                    },
                )
                started = True
            if chunk.get("usage") is not None:
                usage = chunk["usage"]
            choices = chunk.get("choices", [])
            if not choices:
                continue
            if len(choices) != 1 or choices[0].get("index", 0) != 0:
                raise ChatCompatibilityError("ExpectedOneStreamChoice")
            choice = choices[0]
            if choice.get("finish_reason") is not None:
                if finish is not None and finish != choice["finish_reason"]:
                    raise ChatCompatibilityError("ConflictingFinishReason")
                finish = choice["finish_reason"]
            delta = choice.get("delta") or {}
            if delta.get("refusal"):
                raise ChatCompatibilityError("UpstreamRefusal")
            if delta.get("content"):
                if text_index is None:
                    text_index, block_count = block_count, block_count + 1
                    yield _event(
                        "content_block_start",
                        index=text_index,
                        content_block={"type": "text", "text": ""},
                    )
                yield _event(
                    "content_block_delta",
                    index=text_index,
                    delta={"type": "text_delta", "text": delta["content"]},
                )
                self.observation["text_delta_count"] += 1
            # reasoning_content and other provider reasoning fields are intentionally not
            # represented as signed Anthropic thinking blocks.
            for call in delta.get("tool_calls") or []:
                key = call.get("index")
                if type(key) is not int or key < 0:
                    raise ChatCompatibilityError("MissingToolIndex")
                tool = tools.setdefault(
                    key, {"id": "", "name": "", "pieces": [], "buffer": "", "index": None}
                )
                function = call.get("function") or {}
                if call.get("type") not in {None, "function"}:
                    raise ChatCompatibilityError("UnsupportedReturnedTool")
                if call.get("id"):
                    if tool["id"] and tool["id"] != call["id"]:
                        raise ChatCompatibilityError("ChangedToolIdentity")
                    tool["id"] = call["id"]
                if function.get("name"):
                    if tool["name"] and tool["name"] != function["name"]:
                        raise ChatCompatibilityError("ChangedToolName")
                    tool["name"] = function["name"]
                piece = function.get("arguments")
                if piece is not None:
                    if not isinstance(piece, str):
                        raise ChatCompatibilityError("InvalidArgumentDelta")
                    tool["pieces"].append(piece)
                    tool["buffer"] += piece
                    if tool["buffer"]:
                        try:
                            from_json(tool["buffer"].encode(), partial_mode=True)
                        except ValueError:
                            # The SDK uses this same partial parser, but its own ValueError
                            # embeds raw arguments. Classify before yielding instead.
                            raise ChatCompatibilityError("InvalidPartialToolArguments") from None
                if tool["index"] is None and tool["id"] and tool["name"]:
                    tool["index"], block_count = block_count, block_count + 1
                    yield _event(
                        "content_block_start",
                        index=tool["index"],
                        content_block={
                            "type": "tool_use",
                            "id": tool["id"],
                            "name": tool["name"],
                            "input": {},
                        },
                    )
                if tool["index"] is not None:
                    for piece in tool["pieces"]:
                        yield _event(
                            "content_block_delta",
                            index=tool["index"],
                            delta={"type": "input_json_delta", "partial_json": piece},
                        )
                        self.observation["tool_argument_delta_count"] += 1
                    tool["pieces"].clear()
        if not started:
            raise ChatCompatibilityError("EmptyUpstreamStream")
        stop_reason = _stop(finish, bool(tools))
        # Validate all completed calls before closing any block: the reference runtime
        # starts tools at block_stop, including with eager dispatch enabled.
        seen: set[str] = set()
        for tool in tools.values():
            if tool["index"] is None:
                raise ChatCompatibilityError("IncompleteToolIdentity")
            _identity(tool["id"], tool["name"], seen)
            _arguments(tool["buffer"])
        final_usage = _usage(usage)
        self.observation["usage_available"] = usage is not None
        self.observation["usage"] = final_usage if usage is not None else None
        self.observation["elapsed_ms"] = round(
            (time.monotonic() - self.observation["_started"]) * 1000
        )
        self.observation["completed"] = True
        for index in range(block_count):
            yield _event("content_block_stop", index=index)
        yield _event(
            "message_delta",
            delta={"stop_reason": stop_reason, "stop_sequence": None},
            usage=final_usage,
        )
        yield _event("message_stop")

    async def aclose(self) -> None:
        await self.upstream.aclose()


class ChatToMessagesTransport(httpx.AsyncBaseTransport):
    def __init__(
        self,
        root: str,
        api_key: str,
        *,
        timeout_s: float = 60,
        upstream_transport: httpx.AsyncBaseTransport | None = None,
        before_request: Callable | None = None,
        observe: Callable | None = None,
    ) -> None:
        parsed = httpx.URL(root)
        if (
            parsed.scheme not in {"https", "http"}
            or parsed.userinfo
            or parsed.query
            or parsed.fragment
        ):
            raise ChatCompatibilityError("InvalidRootURL")
        root = root.rstrip("/")
        self._endpoint = root + (
            "/chat/completions"
            if parsed.path.rstrip("/").endswith("/v1")
            else "/v1/chat/completions"
        )
        self._key = api_key
        self._upstream = httpx.AsyncClient(
            transport=upstream_transport, timeout=timeout_s, follow_redirects=False
        )
        self.observations: list[dict[str, Any]] = []
        self._before_request, self._observe = before_request, observe

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method != "POST" or request.url.path != "/v1/messages":
            raise ChatCompatibilityError("UnsupportedSDKRoute")
        observation = None
        try:
            body = translate_request(json.loads(await request.aread()))
            if self._before_request is not None:
                self._before_request(body)
            observation = {
                "model": body["model"],
                "_started": time.monotonic(),
                "stream": body["stream"],
                "completed": False,
                "usage_available": False,
                "text_delta_count": 0,
                "tool_argument_delta_count": 0,
            }
            (self._observe or self.observations.append)(observation)
            outbound = self._upstream.build_request(
                "POST",
                self._endpoint,
                json=body,
                headers={
                    "Authorization": "Bearer " + self._key,
                    "Accept": "text/event-stream" if body["stream"] else "application/json",
                },
            )
            upstream = await self._upstream.send(outbound, stream=body["stream"])
            observation["http_status"] = upstream.status_code
            if not 200 <= upstream.status_code < 300:
                _observe_error(observation, "provider_http")
                status = upstream.status_code
                await upstream.aclose()
                return httpx.Response(
                    status,
                    request=request,
                    json={
                        "type": "error",
                        "error": {
                            "type": "api_error",
                            "message": "UpstreamHTTPStatus " + str(status),
                        },
                    },
                )
            if body["stream"]:
                return httpx.Response(
                    200,
                    request=request,
                    headers={"content-type": "text/event-stream"},
                    stream=_MessagesStream(upstream, body["model"], observation),
                )
            try:
                response_body = upstream.json()
                translated = translate_response(response_body, body["model"])
                observation.update(
                    completed=True,
                    usage_available=response_body.get("usage") is not None,
                    usage=translated["usage"] if response_body.get("usage") is not None else None,
                    elapsed_ms=round((time.monotonic() - observation["_started"]) * 1000),
                )
                return httpx.Response(200, request=request, json=translated)
            finally:
                await upstream.aclose()
        except ChatCompatibilityError:
            _observe_error(observation, "provider_protocol")
            raise
        except httpx.HTTPError as error:
            _observe_error(observation, "provider_transport")
            raise ChatCompatibilityError(type(error).__name__) from None
        except (ValueError, TypeError, KeyError) as error:
            _observe_error(observation, "provider_protocol")
            raise ChatCompatibilityError(type(error).__name__) from None

    async def aclose(self) -> None:
        await self._upstream.aclose()


def make_client(
    root: str,
    api_key: str,
    *,
    timeout_s: float = 60,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
    before_request: Callable | None = None,
    observe: Callable | None = None,
) -> anthropic.AsyncAnthropic:
    """Construct without network access; caller injects and owns the returned SDK client.

    `_chat_compat_transport.observations` contains only counts/booleans. Any absent
    upstream usage becomes SDK-required zeros and usage_available=False; never interpret
    that as measured zero tokens. Report this route as Chat compatibility, not Messages.
    """
    transport = ChatToMessagesTransport(
        root,
        api_key,
        timeout_s=timeout_s,
        upstream_transport=upstream_transport,
        before_request=before_request,
        observe=observe,
    )
    client = anthropic.AsyncAnthropic(
        api_key="local-compat-transport-only",
        base_url="https://chat-compat.invalid",
        max_retries=0,
        timeout=timeout_s,
        http_client=httpx.AsyncClient(transport=transport, timeout=timeout_s),
    )
    client._chat_compat_transport = transport
    return client
