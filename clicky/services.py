"""Network services behind the Cloudflare Worker. All methods run on the AsyncRunner's loop."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable

import httpx

from clicky.claude_client import ChatStreamEvent, stream_chat
from clicky.config import Settings
from clicky.transcription import AssemblyAIStreamingSession, build_websocket_url, fetch_temporary_token
from clicky.tts import fetch_speech_audio

# Words AssemblyAI should expect, improving recognition of names it would otherwise mishear.
TRANSCRIPTION_KEYTERMS = ("Clicky", "Claude", "VS Code", "GitHub", "Python", "Windows")


class WorkerServices:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None

    def _http_client(self) -> httpx.AsyncClient:
        # Created lazily so it binds to the loop thread that uses it.
        if self._client is None:
            self._client = httpx.AsyncClient(headers={"user-agent": "clicky-windows/0.1"})
        return self._client

    async def start_transcription(
        self, on_transcript_update: Callable[[str], None]
    ) -> AssemblyAIStreamingSession:
        token = await fetch_temporary_token(self._http_client(), self._settings.transcribe_token_url)
        session = AssemblyAIStreamingSession(
            websocket_url=build_websocket_url(token, TRANSCRIPTION_KEYTERMS),
            on_transcript_update=on_transcript_update,
        )
        await session.open()
        return session

    def stream_reply(self, request_body: dict) -> AsyncIterator[ChatStreamEvent]:
        return stream_chat(self._http_client(), self._settings.chat_url, request_body)

    async def fetch_speech(self, text: str) -> bytes:
        return await fetch_speech_audio(self._http_client(), self._settings.tts_url, text)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
