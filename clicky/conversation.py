"""Short rolling memory of the conversation, sent as plain text with every request."""

from __future__ import annotations

from collections import deque

DEFAULT_MAX_EXCHANGES = 10


class ConversationHistory:
    """Keeps the last N (user transcript, assistant reply) pairs. Screenshots are not kept, only text,
    the same as the macOS app, so each request carries images for the current turn only."""

    def __init__(self, max_exchanges: int = DEFAULT_MAX_EXCHANGES) -> None:
        self._exchanges: deque[tuple[str, str]] = deque(maxlen=max_exchanges)

    def add(self, user_transcript: str, assistant_reply: str) -> None:
        if not user_transcript.strip() or not assistant_reply.strip():
            return
        self._exchanges.append((user_transcript.strip(), assistant_reply.strip()))

    def clear(self) -> None:
        self._exchanges.clear()

    def __len__(self) -> int:
        return len(self._exchanges)

    def as_messages(self) -> list[dict]:
        messages: list[dict] = []
        for user_transcript, assistant_reply in self._exchanges:
            messages.append({"role": "user", "content": user_transcript})
            messages.append({"role": "assistant", "content": assistant_reply})
        return messages
