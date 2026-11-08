"""Kokoro-82M: a free neural voice that runs on this PC, turning text into WAV bytes.

`KokoroSpeech.synthesize` blocks while the model works (a second or more for a long answer), so callers run it in a
worker thread (`asyncio.to_thread`), never on the GUI thread or directly on the asyncio loop. The model files come from
`scripts/download_kokoro.py`; nothing is downloaded at run time. `kokoro_onnx` is imported only when the model loads,
so the tests and app start don't need it. Design: docs/superpowers/specs/2026-11-08-kokoro-local-voice-design.md
"""

from __future__ import annotations

import io
import os
import threading
import wave
from array import array
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from clicky.tts import TTSError

MODEL_FILE_NAME = "kokoro-v1.0.int8.onnx"
VOICES_FILE_NAME = "voices-v1.0.bin"
SPEED = 1.0
LANGUAGE = "en-us"


def default_model_dir() -> Path:
    """%LOCALAPPDATA%/Clicky/models, next to Clicky's log file."""
    return Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Clicky" / "models"


def encode_wav(samples: Sequence[float], sample_rate: int) -> bytes:
    """Mono 16-bit PCM WAV from float samples in -1..1 (anything outside is clipped)."""
    if hasattr(samples, "clip"):  # a numpy array, as Kokoro returns: convert in one go rather than per sample
        pcm = (samples.clip(-1.0, 1.0) * 32767).astype("<i2").tobytes()
    else:
        pcm = array("h", (int(max(-1.0, min(1.0, sample)) * 32767) for sample in samples)).tobytes()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as writer:
        writer.setnchannels(1)
        writer.setsampwidth(2)
        writer.setframerate(sample_rate)
        writer.writeframes(pcm)
    return buffer.getvalue()


def _create_kokoro(model_path: str, voices_path: str) -> Any:
    from kokoro_onnx import Kokoro

    return Kokoro(model_path, voices_path)


class KokoroSpeech:
    """load() once (thread-safe), then synthesize(text) -> WAV bytes. Every failure is a TTSError."""

    def __init__(self, model_dir: Path, voice: str, kokoro_factory: Callable[[str, str], Any] | None = None) -> None:
        self._model_dir = model_dir
        self._voice = voice
        self._kokoro_factory = kokoro_factory or _create_kokoro
        self._kokoro: Any = None
        self._lock = threading.Lock()

    def load(self) -> None:
        with self._lock:
            if self._kokoro is not None:
                return
            model_path = self._model_dir / MODEL_FILE_NAME
            voices_path = self._model_dir / VOICES_FILE_NAME
            if not model_path.is_file() or not voices_path.is_file():
                raise TTSError(
                    f"Kokoro voice model not found in {self._model_dir}. Run: python scripts/download_kokoro.py"
                )
            try:
                self._kokoro = self._kokoro_factory(str(model_path), str(voices_path))
            except Exception as load_error:
                raise TTSError(f"Kokoro voice couldn't load: {load_error}") from load_error

    def synthesize(self, text: str) -> bytes:
        if not text.strip():
            raise TTSError("Nothing to speak.")
        self.load()
        try:
            samples, sample_rate = self._kokoro.create(text, voice=self._voice, speed=SPEED, lang=LANGUAGE)
        except Exception as synthesis_error:
            raise TTSError(f"Kokoro voice failed: {synthesis_error}") from synthesis_error
        return encode_wav(samples, sample_rate)
