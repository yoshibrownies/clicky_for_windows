"""Plays the ElevenLabs MP3 reply with QtMultimedia (GUI thread)."""

from __future__ import annotations

import logging
import os
import tempfile

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

logger = logging.getLogger(__name__)


def progress_fraction(position_ms: int, duration_ms: int) -> float | None:
    """Playback progress 0..1, or None while the duration is still unknown."""
    if duration_ms <= 0:
        return None
    return min(1.0, max(0.0, position_ms / duration_ms))


class SpeechPlayer(QObject):
    """play(mp3_bytes) / stop(). Emits `finished` once per play, whether it ended, failed or was stopped."""

    finished = Signal()
    started = Signal()
    progress = Signal(float)  # 0..1 while playing; drives the timing of underlines and notes

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._audio_output = QAudioOutput(self)
        self._audio_output.setVolume(1.0)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio_output)
        self._player.mediaStatusChanged.connect(self._on_media_status_changed)
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._player.errorOccurred.connect(self._on_error)
        # Qt 6 reports position a few times a second, enough to time phrase-level marks.
        self._player.positionChanged.connect(self._on_position_changed)
        self._current_file_path: str | None = None
        self._is_playing = False

    @property
    def is_playing(self) -> bool:
        return self._is_playing

    def play(self, mp3_audio: bytes) -> None:
        self.stop()
        # A temp file is the most reliable source across Qt's Windows media backends.
        file_descriptor, file_path = tempfile.mkstemp(prefix="clicky-reply-", suffix=".mp3")
        with os.fdopen(file_descriptor, "wb") as mp3_file:
            mp3_file.write(mp3_audio)
        self._current_file_path = file_path
        self._is_playing = True
        self._player.setSource(QUrl.fromLocalFile(file_path))
        self._player.play()

    def stop(self) -> None:
        if not self._is_playing:
            self._delete_current_file()
            return
        self._player.stop()
        self._finish()

    def _finish(self) -> None:
        if not self._is_playing:
            return
        self._is_playing = False
        self._player.setSource(QUrl())
        self._delete_current_file()
        self.finished.emit()

    def _delete_current_file(self) -> None:
        file_path, self._current_file_path = self._current_file_path, None
        if file_path:
            try:
                os.remove(file_path)
            except OSError:
                logger.debug("Could not delete %s yet", file_path)

    def _on_position_changed(self, position_ms: int) -> None:
        if not self._is_playing:
            return
        fraction = progress_fraction(position_ms, self._player.duration())
        if fraction is not None:
            self.progress.emit(fraction)

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._finish()
        elif status == QMediaPlayer.MediaStatus.InvalidMedia:
            logger.warning("Reply audio could not be decoded")
            self._finish()

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        if state == QMediaPlayer.PlaybackState.PlayingState and self._is_playing:
            self.started.emit()

    def _on_error(self, error: QMediaPlayer.Error, error_text: str) -> None:
        if error != QMediaPlayer.Error.NoError:
            logger.warning("Playback error: %s", error_text)
            self._finish()
