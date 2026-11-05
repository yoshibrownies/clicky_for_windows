"""ElevenLabs text-to-speech through the Worker's /tts route.

Returns MP3 bytes; playback lives in playback.py."""

from __future__ import annotations

import httpx

TTS_TIMEOUT = httpx.Timeout(connect=10.0, read=60.0, write=30.0, pool=10.0)


class TTSError(RuntimeError):
    pass


def build_tts_request_body(text: str) -> dict:
    return {
        "text": text,
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }


async def fetch_speech_audio(client: httpx.AsyncClient, tts_url: str, text: str) -> bytes:
    if not text.strip():
        raise TTSError("Nothing to speak.")
    try:
        response = await client.post(
            tts_url, json=build_tts_request_body(text), headers={"accept": "audio/mpeg"}, timeout=TTS_TIMEOUT
        )
    except httpx.HTTPError as network_error:
        raise TTSError(f"Couldn't reach the Clicky Worker: {network_error}") from network_error
    if response.status_code != 200:
        raise TTSError(f"Text-to-speech failed ({response.status_code}): {response.text[:200]}")
    if not response.content:
        raise TTSError("Text-to-speech returned empty audio.")
    return response.content
