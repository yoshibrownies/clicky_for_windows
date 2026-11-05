"""The whiteboard: plays the animation scenes Clicky writes (see scene.py) in a paper-white panel.

Click-through, always on top, excluded from screen capture, docked to the left of the notepad. 60 fps while the
scene plays; afterwards it holds the last frame with the timer stopped, lingers, then fades.
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QGuiApplication, QPainter
from PySide6.QtWidgets import QWidget

from clicky.notepad import PAPER_WIDTH as NOTEPAD_PAPER_WIDTH
from clicky.notepad import SHADOW
from clicky.overlay import exclude_window_from_capture
from clicky.scene import Scene
from clicky.scene_painter import BOARD_COLOR, ScenePainter, WorldMapper, nice_ticks  # noqa: F401

logger = logging.getLogger(__name__)

BOARD_WIDTH = 520
BOARD_HEIGHT = 390
FRAME_INTERVAL_MS = 16
IDLE_CHECK_INTERVAL_MS = 200
DEFAULT_LINGER_SECONDS = 20.0
DEFAULT_FADE_SECONDS = 0.6
CLEAR_FADE_SECONDS = 0.2
PIXEL_LIMIT = 10_000.0


class WhiteboardWindow(QWidget):
    def __init__(self, linger_seconds: float = DEFAULT_LINGER_SECONDS, fade_seconds: float = DEFAULT_FADE_SECONDS):
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setWindowTitle("Clicky's whiteboard")
        self.resize(BOARD_WIDTH + 2 * SHADOW, BOARD_HEIGHT + 2 * SHADOW)
        self._linger_seconds = linger_seconds
        self._fade_seconds = fade_seconds
        self._enabled = True
        self._scene: Scene | None = None
        self._started_at = 0.0
        self._fade_at: float | None = None
        self._active_fade_seconds = fade_seconds
        self._capture_exclusion_applied = False
        self._scene_painter = ScenePainter()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.setInterval(FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    # ----- public API (GUI thread) -----

    @property
    def is_playing(self) -> bool:
        return self._scene is not None and self._timer.isActive() and self._elapsed() < self._scene.duration

    def current_time(self) -> float:
        if self._scene is None:
            return 0.0
        return min(self._elapsed(), self._scene.duration)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self.clear()

    def play(self, scene: Scene | None) -> None:
        if scene is None or not self._enabled:
            return
        self._scene = scene
        self._started_at = time.monotonic()
        self._fade_at = None
        if not self.isVisible():
            self._dock()
            self.show()
            if not self._capture_exclusion_applied:
                self._capture_exclusion_applied = exclude_window_from_capture(int(self.winId()))
        self._timer.start(FRAME_INTERVAL_MS)
        self.update()

    def finish(self) -> None:
        if self._scene is not None:
            self._fade_at = max(time.monotonic(), self._started_at + self._scene.duration) + self._linger_seconds
            self._active_fade_seconds = self._fade_seconds
            self._timer.start(FRAME_INTERVAL_MS)

    def clear(self) -> None:
        if self._scene is not None and self.isVisible():
            self._fade_at = time.monotonic()
            self._active_fade_seconds = CLEAR_FADE_SECONDS
            self._timer.start(FRAME_INTERVAL_MS)
        else:
            self._reset()

    # ----- internals -----

    def _elapsed(self) -> float:
        return time.monotonic() - self._started_at

    def _dock(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        notepad_column = NOTEPAD_PAPER_WIDTH + 2 * SHADOW + 16
        x = available.right() - notepad_column - self.width() - 8
        y = available.top() + 72
        if x < available.left() + 16:  # no room beside the notepad: bottom-right corner instead
            x = available.right() - self.width() - 16
            y = available.bottom() - self.height() - 16
        self.move(x, y)

    def _opacity(self, now: float) -> float:
        if self._fade_at is None or now < self._fade_at:
            return 1.0
        return max(0.0, 1.0 - (now - self._fade_at) / self._active_fade_seconds)

    def _reset(self) -> None:
        self._scene = None
        self._fade_at = None
        self._timer.stop()
        if self.isVisible():
            self.hide()

    def _tick(self) -> None:
        now = time.monotonic()
        if self._scene is None:
            self._timer.stop()
            return
        if self._fade_at is not None and self._opacity(now) <= 0:
            self._reset()
            return
        playing = self._elapsed() < self._scene.duration
        fading = self._fade_at is not None and now >= self._fade_at
        if playing or fading:
            self._timer.setInterval(FRAME_INTERVAL_MS)
            self.update()
        elif self._fade_at is not None:
            self._timer.setInterval(IDLE_CHECK_INTERVAL_MS)  # holding the last frame until the fade
        else:
            self.update()  # final frame
            self._timer.stop()

    # ----- painting -----

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setOpacity(self._opacity(time.monotonic()))
        board = QRectF(SHADOW, SHADOW, self.width() - 2 * SHADOW, self.height() - 2 * SHADOW)
        for spread in range(SHADOW, 0, -3):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, int(10 * (1 - spread / SHADOW)) + 3))
            painter.drawRoundedRect(board.adjusted(-spread / 2, -spread / 4, spread / 2, spread), 16, 16)
        painter.setBrush(BOARD_COLOR)
        painter.drawRoundedRect(board, 14, 14)
        scene = self._scene
        if scene is not None:
            try:
                self._scene_painter.paint(painter, board, scene, self.current_time())
            except Exception:  # a broken frame must never take the app down
                logger.exception("Whiteboard frame failed")
        painter.end()
