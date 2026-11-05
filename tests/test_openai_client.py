import json

import httpx
import pytest

from clicky.claude_client import ChatStreamError, StreamFinished, TextDelta
from clicky.config import is_openai_model, load_settings
from clicky.openai_client import build_openai_chat_request_body, stream_openai_chat


def openai_sse(chunks: list[dict]) -> bytes:
    return ("".join(f"data: {json.dumps(chunk)}\n\n" for chunk in chunks) + "data: [DONE]\n\n").encode()


def chunk(content=None, finish_reason=None, refusal=None) -> dict:
    delta = {}
    if content is not None:
        delta["content"] = content
    if refusal is not None:
        delta["refusal"] = refusal
    return {
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


async def collect(handler) -> list:
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return [event async for event in stream_openai_chat(client, "https://worker.test/chat-openai", {"model": "m"})]


def test_model_routing_and_url():
    assert is_openai_model("gpt-6.1-terra")
    assert is_openai_model("gpt-6-luna")
    assert not is_openai_model("claude-opus-5-5")
    settings = load_settings({"CLICKY_WORKER_URL": "https://w.test", "CLICKY_MODEL": "gpt-6.1-terra"})
    assert settings.chat_openai_url == "https://w.test/chat-openai"


def test_openai_request_body_shape():
    body = build_openai_chat_request_body(
        model="gpt-6.1-terra",
        effort="low",
        system_prompt="be clicky",
        history_messages=[{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}],
        screenshots=[(b"\xff\xd8one", "screen 1 label")],
        user_transcript="what is this",
    )
    assert body["model"] == "gpt-6.1-terra"
    assert body["stream"] is True
    assert body["reasoning_effort"] == "low"
    assert body["max_completion_tokens"] >= 1024
    for forbidden_key in ("max_tokens", "temperature", "top_p", "system", "output_config", "logprobs"):
        assert forbidden_key not in body
    messages = body["messages"]
    assert messages[0] == {"role": "developer", "content": "be clicky"}
    assert messages[1:3] == [{"role": "user", "content": "q"}, {"role": "assistant", "content": "a"}]
    current_turn = messages[3]
    assert current_turn["role"] == "user"
    assert [part["type"] for part in current_turn["content"]] == ["image_url", "text", "text"]
    image_url = current_turn["content"][0]["image_url"]["url"]
    assert image_url.startswith("data:image/jpeg;base64,")
    assert current_turn["content"][1]["text"] == "screen 1 label"
    assert current_turn["content"][-1]["text"] == "what is this"


async def test_stream_yields_text_and_maps_stop_to_end_turn():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        stream = openai_sse(
            [chunk(content=""), chunk(content="click "), chunk(content="save."), chunk(finish_reason="stop")]
        )
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=stream)

    events = await collect(handler)
    assert events == [TextDelta("click "), TextDelta("save."), StreamFinished("end_turn")]
    assert seen[0].url.path == "/chat-openai"


@pytest.mark.parametrize(
    "finish_chunks, expected_stop",
    [
        ([chunk(finish_reason="content_filter")], "refusal"),
        ([chunk(refusal="I can't help with that."), chunk(finish_reason="stop")], "refusal"),
        ([chunk(finish_reason="length")], "max_tokens"),
    ],
)
async def test_stream_maps_refusals_and_length(finish_chunks, expected_stop):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=openai_sse(finish_chunks))

    events = await collect(handler)
    assert events[-1] == StreamFinished(expected_stop)
    assert not any(isinstance(event, TextDelta) and "can't" in event.text for event in events)


async def test_http_error_message_is_surfaced():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            401, json={"error": {"message": "Incorrect API key provided", "type": "invalid_request_error"}}
        )

    with pytest.raises(ChatStreamError, match="OpenAI request failed \\(401\\): Incorrect API key provided"):
        await collect(handler)


async def test_error_object_mid_stream_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'data: {"error": {"message": "server overloaded"}}\n\n')

    with pytest.raises(ChatStreamError, match="server overloaded"):
        await collect(handler)


async def test_stream_without_done_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=f"data: {json.dumps(chunk(content='hi'))}\n\n".encode())

    with pytest.raises(ChatStreamError, match="ended"):
        await collect(handler)
