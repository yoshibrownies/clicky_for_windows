import json

import httpx
import pytest

from clicky.claude_client import (
    ClaudeStreamError,
    SSEParser,
    StreamFinished,
    TextDelta,
    build_chat_request_body,
    stream_chat,
)
from clicky.conversation import ConversationHistory


def sse(event_type: str, payload: dict) -> str:
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


HAPPY_STREAM = (
    sse("message_start", {"type": "message_start", "message": {"id": "msg_1"}})
    + 'event: ping\ndata: {"type": "ping"}\n\n'
    + sse(
        "content_block_start",
        {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": ""}},
    )
    + sse(
        "content_block_delta",
        {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": ""}},
    )
    + sse(
        "content_block_delta",
        {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "abc"}},
    )
    + sse("content_block_stop", {"type": "content_block_stop", "index": 0})
    + sse(
        "content_block_start",
        {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
    )
    + sse(
        "content_block_delta",
        {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "hello "}},
    )
    + sse(
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "text_delta", "text": "there [POINT:none]"},
        },
    )
    + sse("content_block_stop", {"type": "content_block_stop", "index": 1})
    + sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn"}})
    + sse("message_stop", {"type": "message_stop"})
)


# ---------- conversation history ----------


def test_history_keeps_only_the_last_ten_exchanges():
    history = ConversationHistory(max_exchanges=10)
    for exchange_number in range(12):
        history.add(f"question {exchange_number}", f"answer {exchange_number}")
    messages = history.as_messages()
    assert len(messages) == 20
    assert messages[0] == {"role": "user", "content": "question 2"}
    assert messages[-1] == {"role": "assistant", "content": "answer 11"}


def test_history_skips_empty_replies_and_can_clear():
    history = ConversationHistory()
    history.add("hi", "   ")
    assert history.as_messages() == []
    history.add("hi", "hey")
    history.clear()
    assert history.as_messages() == []


# ---------- request body ----------


def test_request_body_shape():
    history = ConversationHistory()
    history.add("earlier question", "earlier answer")
    body = build_chat_request_body(
        model="claude-opus-5-5",
        effort="low",
        system_prompt="be clicky",
        history_messages=history.as_messages(),
        screenshots=[(b"\xff\xd8jpeg-one", "screen 1 label"), (b"\xff\xd8jpeg-two", "screen 2 label")],
        user_transcript="what is this button",
    )
    assert body["model"] == "claude-opus-5-5"
    assert body["stream"] is True
    assert body["system"] == "be clicky"
    assert body["output_config"] == {"effort": "low"}
    assert body["max_tokens"] >= 1024
    for forbidden_key in ("thinking", "temperature", "top_p", "top_k"):
        assert forbidden_key not in body

    messages = body["messages"]
    assert messages[:2] == history.as_messages()
    current_turn = messages[2]
    assert current_turn["role"] == "user"
    block_types = [block["type"] for block in current_turn["content"]]
    assert block_types == ["image", "text", "image", "text", "text"]
    first_image = current_turn["content"][0]
    assert first_image["source"]["type"] == "base64"
    assert first_image["source"]["media_type"] == "image/jpeg"
    assert "\n" not in first_image["source"]["data"]
    assert current_turn["content"][1]["text"] == "screen 1 label"
    assert current_turn["content"][-1]["text"] == "what is this button"


# ---------- SSE parser ----------


def test_sse_parser_handles_chunks_split_anywhere():
    raw_stream = HAPPY_STREAM.encode()
    for split_size in (1, 7, 64):
        parser = SSEParser()
        events = []
        for start in range(0, len(raw_stream), split_size):
            events.extend(parser.feed(raw_stream[start : start + split_size]))
        assert [event.event for event in events][:3] == ["message_start", "ping", "content_block_start"]
        assert events[-1].event == "message_stop"
        assert len(events) == 12


def test_sse_parser_handles_crlf_and_multiline_data():
    parser = SSEParser()
    events = parser.feed(b"event: x\r\ndata: line one\r\ndata: line two\r\n\r\n: comment\r\n\r\n")
    assert len(events) == 1
    assert events[0].event == "x"
    assert events[0].data == "line one\nline two"


# ---------- stream_chat ----------


def make_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def collect(client: httpx.AsyncClient, body: dict) -> list:
    return [event async for event in stream_chat(client, "https://worker.test/chat", body)]


async def test_stream_chat_yields_text_then_finish():
    seen_requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_requests.append(request)
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=HAPPY_STREAM.encode()
        )

    async with make_client(handler) as client:
        events = await collect(client, {"model": "m"})

    assert events == [TextDelta("hello "), TextDelta("there [POINT:none]"), StreamFinished("end_turn")]
    assert seen_requests[0].method == "POST"
    assert seen_requests[0].url.path == "/chat"
    assert json.loads(seen_requests[0].content) == {"model": "m"}


async def test_stream_chat_raises_with_api_error_message_on_http_error():
    error_body = {"type": "error", "error": {"type": "invalid_request_error", "message": "bad model"}}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json=error_body)

    async with make_client(handler) as client:
        with pytest.raises(ClaudeStreamError, match="bad model") as error_info:
            await collect(client, {})
    assert error_info.value.status_code == 400


async def test_stream_chat_raises_on_error_event_mid_stream():
    stream_text = sse("message_start", {"type": "message_start", "message": {}}) + sse(
        "error", {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=stream_text.encode())

    async with make_client(handler) as client:
        with pytest.raises(ClaudeStreamError, match="Overloaded"):
            await collect(client, {})


async def test_stream_chat_raises_when_stream_ends_early():
    stream_text = sse("message_start", {"type": "message_start", "message": {}})

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=stream_text.encode())

    async with make_client(handler) as client:
        with pytest.raises(ClaudeStreamError, match="ended"):
            await collect(client, {})


async def test_stream_chat_reports_refusal_stop_reason():
    stream_text = (
        sse("message_start", {"type": "message_start", "message": {}})
        + sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": "refusal"}})
        + sse("message_stop", {"type": "message_stop"})
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=stream_text.encode())

    async with make_client(handler) as client:
        events = await collect(client, {})
    assert events == [StreamFinished("refusal")]


async def test_stream_chat_wraps_network_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route", request=request)

    async with make_client(handler) as client:
        with pytest.raises(ClaudeStreamError, match="reach"):
            await collect(client, {})
