"""Network services behind the Cloudflare Worker. All methods run on the AsyncRunner's loop."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable

import httpx

from clicky.claude_client import ChatStreamEvent, stream_chat
from clicky.config import Settings, is_openai_model
from clicky.kokoro_voice import KokoroSpeech
from clicky.openai_client import stream_openai_chat
from clicky.transcription import (
    ASSEMBLYAI_WEBSOCKET_BASE_URL,
    AssemblyAIStreamingSession,
    build_websocket_url,
    fetch_temporary_token,
)
from clicky.tts import TTSError, fetch_speech_audio

logger = logging.getLogger(__name__)

# Words AssemblyAI should expect, improving recognition of names it would otherwise mishear.
TRANSCRIPTION_KEYTERMS = ("Clicky", "Claude", "VS Code", "GitHub", "Python", "Windows")


class WorkerServices:
    def __init__(
        self,
        settings: Settings,
        assemblyai_websocket_base_url: str = ASSEMBLYAI_WEBSOCKET_BASE_URL,
        kokoro_speech: KokoroSpeech | None = None,
    ) -> None:
        self._settings = settings
        self._kokoro_speech = kokoro_speech
        # Overridable so the end-to-end test can point at a local fake AssemblyAI.
        self._assemblyai_websocket_base_url = assemblyai_websocket_base_url
        self._client: httpx.AsyncClient | None = None

    def _http_client(self) -> httpx.AsyncClient:
        # Created lazily so it binds to the loop thread that uses it.
        if self._client is None:
            self._client = httpx.AsyncClient(headers={"user-agent": "clicky-windows/0.1"})
        return self._client

    async def start_transcription(self, on_transcript_update: Callable[[str], None]) -> AssemblyAIStreamingSession:
        token = await fetch_temporary_token(self._http_client(), self._settings.transcribe_token_url)
        session = AssemblyAIStreamingSession(
            websocket_url=build_websocket_url(token, TRANSCRIPTION_KEYTERMS, self._assemblyai_websocket_base_url),
            on_transcript_update=on_transcript_update,
        )
        await session.open()
        return session

    def stream_reply(self, request_body: dict) -> AsyncIterator[ChatStreamEvent]:
        if is_openai_model(str(request_body.get("model", ""))):
            return stream_openai_chat(self._http_client(), self._settings.chat_openai_url, request_body)
        return stream_chat(self._http_client(), self._settings.chat_url, request_body)

    def _uses_kokoro(self) -> bool:
        return self._settings.voice_engine == "kokoro"

    async def fetch_speech(self, text: str) -> bytes:
        """The spoken answer as audio bytes: a Kokoro WAV (made in a worker thread) or an ElevenLabs MP3."""
        if not self._uses_kokoro():
            return await fetch_speech_audio(self._http_client(), self._settings.tts_url, text)
        if self._kokoro_speech is None:
            raise TTSError("Kokoro voice isn't set up")
        return await asyncio.to_thread(self._kokoro_speech.synthesize, text)

    async def warm_up_voice(self) -> None:
        """Load the Kokoro model in the background at startup, so the first answer isn't slower."""
        if not self._uses_kokoro() or self._kokoro_speech is None:
            return
        try:
            await asyncio.to_thread(self._kokoro_speech.load)
        except TTSError as load_error:
            logger.warning("Kokoro voice unavailable, Windows voice will speak instead: %s", load_error)

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
