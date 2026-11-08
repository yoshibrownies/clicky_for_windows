import io
import struct
import wave
from pathlib import Path

import pytest

from clicky.kokoro_voice import MODEL_FILE_NAME, VOICES_FILE_NAME, KokoroSpeech, encode_wav
from clicky.tts import TTSError


class FakeKokoro:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict]] = []
        self.error = error

    def create(self, text: str, **options):
        self.calls.append((text, options))
        if self.error is not None:
            raise self.error
        return [0.0, 0.5, -1.0, 2.0], 24000


class FakeFactory:
    def __init__(self, kokoro: FakeKokoro) -> None:
        self.kokoro = kokoro
        self.paths: list[tuple[str, str]] = []

    def __call__(self, model_path: str, voices_path: str) -> FakeKokoro:
        self.paths.append((model_path, voices_path))
        return self.kokoro


def model_dir_with_files(tmp_path: Path) -> Path:
    (tmp_path / MODEL_FILE_NAME).write_bytes(b"")
    (tmp_path / VOICES_FILE_NAME).write_bytes(b"")
    return tmp_path


def test_encode_wav_writes_mono_16_bit_clipped_samples():
    wav = encode_wav([0.0, 0.5, -1.0, 2.0], 24000)
    with wave.open(io.BytesIO(wav)) as reader:
        assert (reader.getnchannels(), reader.getsampwidth(), reader.getframerate()) == (1, 2, 24000)
        assert struct.unpack("<4h", reader.readframes(4)) == (0, 16383, -32767, 32767)


def test_synthesize_returns_wav_and_passes_voice_speed_lang(tmp_path):
    factory = FakeFactory(FakeKokoro())
    speech = KokoroSpeech(model_dir_with_files(tmp_path), "af_heart", kokoro_factory=factory)
    audio = speech.synthesize("hello there")
    assert audio[:4] == b"RIFF"
    assert factory.kokoro.calls == [("hello there", {"voice": "af_heart", "speed": 1.0, "lang": "en-us"})]
    assert factory.paths == [(str(tmp_path / MODEL_FILE_NAME), str(tmp_path / VOICES_FILE_NAME))]


def test_model_loads_once_across_calls(tmp_path):
    factory = FakeFactory(FakeKokoro())
    speech = KokoroSpeech(model_dir_with_files(tmp_path), "af_heart", kokoro_factory=factory)
    speech.load()
    speech.synthesize("one")
    speech.synthesize("two")
    assert len(factory.paths) == 1


def test_missing_model_raises_tts_error_naming_the_script(tmp_path):
    factory = FakeFactory(FakeKokoro())
    speech = KokoroSpeech(tmp_path, "af_heart", kokoro_factory=factory)
    with pytest.raises(TTSError, match="download_kokoro.py"):
        speech.synthesize("hello")
    assert factory.paths == []


def test_blank_text_raises_tts_error(tmp_path):
    speech = KokoroSpeech(model_dir_with_files(tmp_path), "af_heart", kokoro_factory=FakeFactory(FakeKokoro()))
    with pytest.raises(TTSError, match="Nothing to speak."):
        speech.synthesize("   ")


def test_synthesis_error_becomes_tts_error(tmp_path):
    factory = FakeFactory(FakeKokoro(error=ValueError("bad voice")))
    speech = KokoroSpeech(model_dir_with_files(tmp_path), "nope", kokoro_factory=factory)
    with pytest.raises(TTSError, match="bad voice"):
        speech.synthesize("hello")


def test_a_failing_model_load_becomes_tts_error(tmp_path):
    def broken_factory(model_path: str, voices_path: str):
        raise RuntimeError("corrupt model")

    speech = KokoroSpeech(model_dir_with_files(tmp_path), "af_heart", kokoro_factory=broken_factory)
    with pytest.raises(TTSError, match="corrupt model"):
        speech.load()
