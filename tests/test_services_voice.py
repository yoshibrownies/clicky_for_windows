"""WorkerServices picks the voice: Kokoro (in a worker thread) or ElevenLabs through the Worker."""

import asyncio
import logging
import threading

import httpx
import pytest

from clicky.config import load_settings
from clicky.kokoro_voice import KokoroSpeech
from clicky.playback import audio_file_suffix
from clicky.services import WorkerServices
from clicky.tts import TTSError

WAV_BYTES = b"RIFF\x00\x00\x00\x00WAVEfmt "


class FakeKokoroSpeech:
    def __init__(self) -> None:
        self.thread_ids: list[int] = []
        self.release = threading.Event()
        self.release.set()

    def synthesize(self, text: str) -> bytes:
        self.thread_ids.append(threading.get_ident())
        self.release.wait(5)
        return WAV_BYTES

    def load(self) -> None:
        pass


class ExplodingKokoroSpeech:
    def synthesize(self, text: str) -> bytes:
        raise AssertionError("Kokoro must not be used in ElevenLabs mode")

    def load(self) -> None:
        raise AssertionError("Kokoro must not be loaded in ElevenLabs mode")


def settings_for(voice: str):
    return load_settings({"CLICKY_WORKER_URL": "http://worker.test", "CLICKY_VOICE": voice})


async def test_kokoro_engine_synthesises_in_a_worker_thread():
    kokoro = FakeKokoroSpeech()
    services = WorkerServices(settings_for("kokoro"), kokoro_speech=kokoro)
    assert await services.fetch_speech("hello") == WAV_BYTES
    assert kokoro.thread_ids and kokoro.thread_ids[0] != threading.get_ident()


async def test_elevenlabs_engine_never_touches_kokoro():
    services = WorkerServices(settings_for("elevenlabs"), kokoro_speech=ExplodingKokoroSpeech())
    services._client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"mp3"))
    )
    assert await services.fetch_speech("hello") == b"mp3"
    await services.warm_up_voice()  # a no-op in ElevenLabs mode
    await services.aclose()


async def test_cancelling_kokoro_fetch_returns_promptly():
    kokoro = FakeKokoroSpeech()
    kokoro.release.clear()
    services = WorkerServices(settings_for("kokoro"), kokoro_speech=kokoro)
    task = asyncio.ensure_future(services.fetch_speech("a long answer"))
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 0.5)
    finally:
        kokoro.release.set()


async def test_kokoro_engine_without_kokoro_speech_raises_tts_error():
    services = WorkerServices(settings_for("kokoro"))
    with pytest.raises(TTSError):
        await services.fetch_speech("hello")


async def test_warm_up_logs_instead_of_raising_when_model_missing(tmp_path, caplog):
    services = WorkerServices(settings_for("kokoro"), kokoro_speech=KokoroSpeech(tmp_path, "af_heart"))
    with caplog.at_level(logging.WARNING):
        await services.warm_up_voice()
    assert "download_kokoro.py" in caplog.text


def test_audio_file_suffix_detects_wav_and_defaults_to_mp3():
    assert audio_file_suffix(b"RIFF\x00\x00\x00\x00WAVE") == ".wav"
    assert audio_file_suffix(b"\xff\xfb\x90") == ".mp3"
