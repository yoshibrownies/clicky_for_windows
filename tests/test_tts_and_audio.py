import json
import struct

import httpx
import pytest

from clicky.audio_capture import compute_audio_level
from clicky.tts import TTSError, build_tts_request_body, fetch_speech_audio


def test_tts_body_matches_mac_app():
    assert build_tts_request_body("hi there") == {
        "text": "hi there",
        "model_id": "eleven_flash_v2_5",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
    }


async def test_fetch_speech_audio_returns_mp3_bytes():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/tts"
        assert json.loads(request.content)["text"] == "hello"
        assert request.headers["accept"] == "audio/mpeg"
        return httpx.Response(200, headers={"content-type": "audio/mpeg"}, content=b"ID3fake-mp3")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await fetch_speech_audio(client, "https://w.test/tts", "hello") == b"ID3fake-mp3"


@pytest.mark.parametrize(
    "response, message",
    [
        (httpx.Response(401, json={"detail": {"message": "invalid api key"}}), "401"),
        (httpx.Response(200, content=b""), "empty"),
    ],
)
async def test_fetch_speech_audio_raises(response, message):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        with pytest.raises(TTSError, match=message):
            await fetch_speech_audio(client, "https://w.test/tts", "hello")


async def test_fetch_speech_audio_rejects_blank_text():
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200))) as client:
        with pytest.raises(TTSError):
            await fetch_speech_audio(client, "https://w.test/tts", "   ")


def pcm16(samples: list[int]) -> bytes:
    return struct.pack(f"<{len(samples)}h", *samples)


def test_audio_level_of_silence_is_zero():
    assert compute_audio_level(pcm16([0] * 160)) == 0.0


def test_audio_level_of_full_scale_is_one():
    assert compute_audio_level(pcm16([32767, -32768] * 80)) == pytest.approx(1.0, abs=0.01)


def test_audio_level_is_monotonic_and_bounded():
    quiet = compute_audio_level(pcm16([300, -300] * 80))
    loud = compute_audio_level(pcm16([8000, -8000] * 80))
    assert 0.0 < quiet < loud <= 1.0


def test_audio_level_handles_empty_and_odd_length_input():
    assert compute_audio_level(b"") == 0.0
    assert compute_audio_level(b"\x01") == 0.0
    assert compute_audio_level(pcm16([1000]) + b"\x01") > 0.0
