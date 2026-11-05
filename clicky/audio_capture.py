"""Microphone capture: 16 kHz, mono, signed 16-bit little-endian, the format AssemblyAI expects."""

from __future__ import annotations

import logging
import math
import sys
from array import array
from collections.abc import Callable

logger = logging.getLogger(__name__)

SAMPLE_RATE_HERTZ = 16000
# 50 ms per block: AssemblyAI accepts 50-1000 ms frames.
BLOCK_SIZE_FRAMES = 800
# RMS (in dBFS) that maps to an empty / full waveform.
LEVEL_FLOOR_DBFS = -55.0


class MicrophoneError(RuntimeError):
    pass


def compute_audio_level(pcm16_audio: bytes) -> float:
    """Loudness of a PCM16 block as 0..1 on a log scale, for the waveform animation."""
    usable_length = len(pcm16_audio) - (len(pcm16_audio) % 2)
    if usable_length == 0:
        return 0.0
    samples = array("h")
    samples.frombytes(pcm16_audio[:usable_length])
    if sys.byteorder == "big":
        samples.byteswap()
    mean_square = sum(sample * sample for sample in samples) / len(samples)
    if mean_square <= 0:
        return 0.0
    rms_dbfs = 20 * math.log10(math.sqrt(mean_square) / 32768)
    return min(1.0, max(0.0, 1 - rms_dbfs / LEVEL_FLOOR_DBFS))


class MicrophoneStreamer:
    """Opens the default input device and calls on_audio(bytes) from the audio thread for every block.

    The callback must be fast and thread-safe (the controller hands blocks to the asyncio loop with
    call_soon_threadsafe).
    """

    def __init__(self, on_audio: Callable[[bytes], None]) -> None:
        self._on_audio = on_audio
        self._stream = None

    @property
    def is_running(self) -> bool:
        return self._stream is not None

    def start(self) -> None:
        if self._stream is not None:
            return
        try:
            import sounddevice

            self._stream = sounddevice.RawInputStream(
                samplerate=SAMPLE_RATE_HERTZ,
                blocksize=BLOCK_SIZE_FRAMES,
                channels=1,
                dtype="int16",
                callback=self._handle_audio_block,
            )
            self._stream.start()
        except Exception as microphone_error:  # sounddevice raises PortAudioError and plain OSErrors
            self._stream = None
            raise MicrophoneError(
                "Couldn't open the microphone. Check Windows Settings → Privacy & security → Microphone, "
                f"and that an input device is plugged in. ({microphone_error})"
            ) from microphone_error

    def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is None:
            return
        try:
            stream.stop()
            stream.close()
        except Exception:
            logger.exception("Error closing microphone stream")

    def _handle_audio_block(self, input_data, frame_count, time_info, status) -> None:
        if status:
            logger.debug("Microphone status: %s", status)
        self._on_audio(bytes(input_data))
