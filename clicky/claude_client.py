"""Streams Claude replies through the Cloudflare Worker's /chat route.

Why raw httpx instead of the Anthropic SDK: the SDK always posts to {base_url}/v1/messages, but the
upstream Worker (kept unchanged on purpose) only serves /chat and forwards the body verbatim to
https://api.anthropic.com/v1/messages with its own key and headers.
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

import httpx

DEFAULT_MAX_TOKENS = 4096
# Generous read timeout: the first byte can take a while when the model thinks before answering.
CHAT_TIMEOUT = httpx.Timeout(connect=10.0, read=90.0, write=30.0, pool=10.0)


class ChatStreamError(RuntimeError):
    """A chat reply failed (HTTP error, error event, network problem or truncated stream). Any provider."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


# Original name, kept so existing imports keep working.
ClaudeStreamError = ChatStreamError


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class StreamFinished:
    stop_reason: str | None


ChatStreamEvent = TextDelta | StreamFinished


@dataclass(frozen=True)
class SSEEvent:
    event: str
    data: str


class SSEParser:
    """Incremental Server-Sent Events parser. Feed it raw bytes as they arrive, in any chunking."""

    def __init__(self) -> None:
        self._pending_text = ""
        self._decoder_buffer = b""
        self._event_name = ""
        self._data_lines: list[str] = []

    def feed(self, chunk: bytes) -> list[SSEEvent]:
        # Keep incomplete UTF-8 sequences until the rest of the bytes arrive.
        self._decoder_buffer += chunk
        try:
            decoded_text = self._decoder_buffer.decode("utf-8")
            self._decoder_buffer = b""
        except UnicodeDecodeError as decode_error:
            decoded_text = self._decoder_buffer[: decode_error.start].decode("utf-8")
            self._decoder_buffer = self._decoder_buffer[decode_error.start :]

        self._pending_text += decoded_text
        completed_events: list[SSEEvent] = []
        while True:
            newline_index = self._pending_text.find("\n")
            if newline_index == -1:
                break
            line = self._pending_text[:newline_index].rstrip("\r")
            self._pending_text = self._pending_text[newline_index + 1 :]
            event = self._process_line(line)
            if event is not None:
                completed_events.append(event)
        return completed_events

    def _process_line(self, line: str) -> SSEEvent | None:
        if line == "":
            if not self._data_lines and not self._event_name:
                return None
            event = SSEEvent(event=self._event_name or "message", data="\n".join(self._data_lines))
            self._event_name = ""
            self._data_lines = []
            return event
        if line.startswith(":"):
            return None
        field_name, _, field_value = line.partition(":")
        field_value = field_value.removeprefix(" ")
        if field_name == "event":
            self._event_name = field_value
        elif field_name == "data":
            self._data_lines.append(field_value)
        return None


def build_chat_request_body(
    *,
    model: str,
    effort: str,
    system_prompt: str,
    history_messages: Sequence[dict],
    screenshots: Sequence[tuple[bytes, str]],
    user_transcript: str,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> dict:
    """Messages API body: prior text turns, then this turn's labelled screenshots and the transcript."""
    current_turn_content: list[dict] = []
    for jpeg_bytes, screen_label in screenshots:
        current_turn_content.append(
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": base64.b64encode(jpeg_bytes).decode("ascii"),
                },
            }
        )
        current_turn_content.append({"type": "text", "text": screen_label})
    current_turn_content.append({"type": "text", "text": user_transcript})

    return {
        "model": model,
        "max_tokens": max_tokens,
        "stream": True,
        "system": system_prompt,
        # Voice chat: low effort keeps time-to-first-word short. Thinking is left at the model default
        # (Opus 5.5 cannot disable it; effort is the control).
        "output_config": {"effort": effort},
        "messages": [*history_messages, {"role": "user", "content": current_turn_content}],
    }


def _error_message_from_body(body_text: str) -> str:
    try:
        payload = json.loads(body_text)
    except ValueError:
        return body_text.strip()[:300] or "no details"
    if isinstance(payload, dict):
        error_object = payload.get("error")
        if isinstance(error_object, dict) and error_object.get("message"):
            return str(error_object["message"])
        if isinstance(error_object, str):
            return error_object
    return body_text.strip()[:300]


async def stream_chat(client: httpx.AsyncClient, chat_url: str, body: dict) -> AsyncIterator[ChatStreamEvent]:
    """POST the body and yield TextDelta chunks, ending with exactly one StreamFinished."""
    parser = SSEParser()
    stop_reason: str | None = None
    try:
        async with client.stream("POST", chat_url, json=body, timeout=CHAT_TIMEOUT) as response:
            if response.status_code != 200:
                error_text = (await response.aread()).decode("utf-8", errors="replace")
                raise ClaudeStreamError(
                    f"Claude request failed ({response.status_code}): {_error_message_from_body(error_text)}",
                    status_code=response.status_code,
                )
            async for chunk in response.aiter_bytes():
                for sse_event in parser.feed(chunk):
                    if not sse_event.data:
                        continue
                    try:
                        payload = json.loads(sse_event.data)
                    except ValueError:
                        continue
                    event_type = payload.get("type", sse_event.event)

                    if event_type == "content_block_delta":
                        delta = payload.get("delta") or {}
                        if delta.get("type") == "text_delta" and delta.get("text"):
                            yield TextDelta(delta["text"])
                    elif event_type == "message_delta":
                        stop_reason = (payload.get("delta") or {}).get("stop_reason") or stop_reason
                    elif event_type == "error":
                        raise ClaudeStreamError(f"Claude stream error: {_error_message_from_body(sse_event.data)}")
                    elif event_type == "message_stop":
                        yield StreamFinished(stop_reason)
                        return
    except httpx.HTTPError as network_error:
        raise ClaudeStreamError(f"Couldn't reach the Clicky Worker: {network_error}") from network_error

    raise ClaudeStreamError("Claude stream ended before the reply was finished.")
