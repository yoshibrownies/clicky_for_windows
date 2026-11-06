"""Short rolling memory of the conversation, sent as plain text with every request."""

from __future__ import annotations

import threading
from collections import deque

DEFAULT_MAX_EXCHANGES = 10


class ConversationHistory:
    """Keeps the last N (user transcript, assistant reply) pairs. Screenshots are not kept, only text,
    the same as the macOS app, so each request carries images for the current turn only."""

    def __init__(self, max_exchanges: int = DEFAULT_MAX_EXCHANGES) -> None:
        self._exchanges: deque[tuple[str, str]] = deque(maxlen=max_exchanges)
        # Read and written on the asyncio thread, cleared from the GUI thread (tray "forget").
        self._lock = threading.Lock()

    def add(self, user_transcript: str, assistant_reply: str) -> None:
        if not user_transcript.strip() or not assistant_reply.strip():
            return
        with self._lock:
            self._exchanges.append((user_transcript.strip(), assistant_reply.strip()))

    def clear(self) -> None:
        with self._lock:
            self._exchanges.clear()

    def __len__(self) -> int:
        with self._lock:
            return len(self._exchanges)

    def as_messages(self) -> list[dict]:
        with self._lock:
            exchanges = list(self._exchanges)
        messages: list[dict] = []
        for user_transcript, assistant_reply in exchanges:
            messages.append({"role": "user", "content": user_transcript})
            messages.append({"role": "assistant", "content": assistant_reply})
        return messages
