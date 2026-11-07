"""Windows' built-in voice as a fallback when ElevenLabs can't speak (GUI thread).

`SystemVoice` wraps Qt's QTextToSpeech (bundled with PySide6; engines "winrt"/"sapi", "mock" in tests) and reports
word-by-word progress like `SpeechPlayer`. `VoiceOutput` owns both and re-emits their signals, so the controller and
the visual director keep a single player.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtTextToSpeech import QTextToSpeech

from clicky.playback import SpeechPlayer

logger = logging.getLogger(__name__)

# winrt starts speaking in about 0.3 s; if nothing has started by then, the engine is stuck and the answer goes to text.
START_TIMEOUT_MS = 4000


class SystemVoice(QObject):
    """speak(text) / stop(). Emits `finished` once per speak, whether it ended, failed or was stopped."""

    started = Signal()
    progress = Signal(float)
    finished = Signal()
    failed = Signal(str)

    def __init__(
        self, engine: str = "winrt", parent: QObject | None = None, start_timeout_ms: int = START_TIMEOUT_MS
    ) -> None:
        super().__init__(parent)
        self._start_timer = QTimer(self)
        self._start_timer.setSingleShot(True)
        self._start_timer.setInterval(start_timeout_ms)
        self._start_timer.timeout.connect(self._on_start_timeout)
        available = QTextToSpeech.availableEngines()
        chosen = engine if engine in available else (available[0] if available else "")
        self._speech = QTextToSpeech(chosen, self) if chosen else None
        self._text = ""
        self._is_playing = False
        if self._speech is not None:
            self._speech.stateChanged.connect(self._on_state_changed)
            self._speech.sayingWord.connect(self._on_saying_word)

    @property
    def available(self) -> bool:
        return self._speech is not None

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    def speak(self, text: str) -> None:
        self.stop()
        if self._speech is None or not text.strip():
            self.failed.emit("no windows voice is available")
            return
        if self._speech.state() == QTextToSpeech.State.Error:
            # Already in Error: a failing say() changes nothing, so no state signal would ever report it.
            self._is_playing = True
            self._fail(self._speech.errorString() or "windows voice is in an error state")
            return
        self._text = text
        self._is_playing = True
        self._start_timer.start()
        self._speech.say(text)

    def stop(self) -> None:
        if not self._is_playing:
            return
        self._is_playing = False  # before stop(): the Ready state it reports must not finish a second time
        self._start_timer.stop()
        if self._speech is not None:
            self._speech.stop()
        self.finished.emit()

    def _on_saying_word(self, word: str, utterance_id: int, start: int, length: int) -> None:
        if self._is_playing and self._text:
            self.progress.emit(max(0.0, min(1.0, (start + length) / len(self._text))))

    def _on_state_changed(self, state: QTextToSpeech.State) -> None:
        if not self._is_playing:
            return
        if state == QTextToSpeech.State.Speaking:
            self._start_timer.stop()
            self.started.emit()
        elif state == QTextToSpeech.State.Ready:
            self._start_timer.stop()
            self._is_playing = False
            self.progress.emit(1.0)
            self.finished.emit()
        elif state == QTextToSpeech.State.Error:
            self._fail(self._speech.errorString() if self._speech is not None else "windows voice failed")

    def _on_start_timeout(self) -> None:
        if self._is_playing:
            # Fail first: winrt reports Ready synchronously on stop(), which must not count as a finished answer.
            self._fail("windows voice didn't start")
            if self._speech is not None:
                self._speech.stop()

    def _fail(self, message: str) -> None:
        """Report a failure (the answer is then shown as text), then finish once."""
        if not self._is_playing:
            return
        logger.warning("Windows voice failed: %s", message)
        self._is_playing = False
        self._start_timer.stop()
        self.failed.emit(message)
        self.finished.emit()


class VoiceOutput(QObject):
    """One player for the controller: ElevenLabs MP3s through `play`, the Windows voice through `speak_text`."""

    started = Signal()
    progress = Signal(float)
    finished = Signal()
    failed = Signal(str)

    def __init__(self, player: SpeechPlayer, voice: SystemVoice, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._player = player
        self._voice = voice
        for source in (player, voice):
            source.started.connect(self.started)
            source.progress.connect(self.progress)
            source.finished.connect(self.finished)
        voice.failed.connect(self.failed)

    @property
    def is_playing(self) -> bool:
        return self._player.is_playing or self._voice.is_playing

    def play(self, mp3_audio: bytes) -> None:
        self._voice.stop()
        self._player.play(mp3_audio)

    def speak_text(self, text: str) -> None:
        self._player.stop()
        self._voice.speak(text)

    def stop(self) -> None:
        self._player.stop()
        self._voice.stop()
