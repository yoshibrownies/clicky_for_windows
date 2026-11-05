"""Streams OpenAI replies through the Worker's /chat-openai route (Chat Completions API).

Produces the same TextDelta / StreamFinished events as claude_client, with stop reasons mapped onto Claude's
names, so the controller doesn't care which provider answered.
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Sequence

import httpx

from clicky.claude_client import (
    CHAT_TIMEOUT,
    DEFAULT_MAX_TOKENS,
    ChatStreamError,
    ChatStreamEvent,
    SSEParser,
    StreamFinished,
    TextDelta,
    _error_message_from_body,
)

FINISH_REASON_TO_STOP_REASON = {
    "stop": "end_turn",
    "length": "max_tokens",
    "content_filter": "refusal",
}


def build_openai_chat_request_body(
    *,
    model: str,
    effort: str,
    system_prompt: str,
    history_messages: Sequence[dict],
    screenshots: Sequence[tuple[bytes, str]],
    user_transcript: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict:
    """Chat Completions body. History is plain text turns, so it can be passed through unchanged."""
    current_turn_content: list[dict] = []
    for jpeg_bytes, screen_label in screenshots:
        image_data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")
        current_turn_content.append({"type": "image_url", "image_url": {"url": image_data_url}})
        current_turn_content.append({"type": "text", "text": screen_label})
    current_turn_content.append({"type": "text", "text": user_transcript})

    return {
        "model": model,
        "stream": True,
        # Reasoning models: max_completion_tokens covers reasoning + visible output (max_tokens is deprecated).
        "max_completion_tokens": max_tokens,
        # Same level names as Clicky's effort setting (low / medium / high). No temperature: GPT-6 rejects it
        # unless reasoning is off.
        "reasoning_effort": effort,
        "messages": [
            {"role": "developer", "content": system_prompt},
            *history_messages,
            {"role": "user", "content": current_turn_content},
        ],
    }


async def stream_openai_chat(client: httpx.AsyncClient, chat_url: str, body: dict) -> AsyncIterator[ChatStreamEvent]:
    """POST the body and yield TextDelta chunks, ending with exactly one StreamFinished."""
    parser = SSEParser()
    stop_reason: str | None = None
    model_refused = False
    try:
        async with client.stream("POST", chat_url, json=body, timeout=CHAT_TIMEOUT) as response:
            if response.status_code != 200:
                error_text = (await response.aread()).decode("utf-8", errors="replace")
                raise ChatStreamError(
                    f"OpenAI request failed ({response.status_code}): {_error_message_from_body(error_text)}",
                    status_code=response.status_code,
                )
            async for raw_chunk in response.aiter_bytes():
                for sse_event in parser.feed(raw_chunk):
                    data = sse_event.data.strip()
                    if not data:
                        continue
                    if data == "[DONE]":
                        yield StreamFinished("refusal" if model_refused else stop_reason)
                        return
                    try:
                        payload = json.loads(data)
                    except ValueError:
                        continue
                    if isinstance(payload, dict) and "error" in payload:
                        raise ChatStreamError(f"OpenAI stream error: {_error_message_from_body(data)}")
                    for choice in payload.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if delta.get("refusal"):
                            # The refusal text is the model's own wording; Clicky speaks its standard apology.
                            model_refused = True
                        if delta.get("content"):
                            yield TextDelta(delta["content"])
                        finish_reason = choice.get("finish_reason")
                        if finish_reason:
                            stop_reason = FINISH_REASON_TO_STOP_REASON.get(finish_reason, finish_reason)
    except httpx.HTTPError as network_error:
        raise ChatStreamError(f"Couldn't reach the Clicky Worker: {network_error}") from network_error

    raise ChatStreamError("OpenAI stream ended before the reply was finished.")
