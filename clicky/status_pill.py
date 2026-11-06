"""The status pill: a small dark pill at the top of the screen while Clicky is busy.

"Listening" with live bars from the microphone, "Thinking" with pulsing dots, "Speaking" with animated bars.
Click-through, never focused, excluded from screen capture. Fades out shortly after Clicky goes idle; the timer only
runs while it's visible.
"""

from __future__ import annotations

import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QGuiApplication, QPainter, QPolygonF
from PySide6.QtWidgets import QWidget

from clicky.overlay import exclude_window_from_capture

PILL_WIDTH = 196
PILL_HEIGHT = 38
SHADOW = 8
FRAME_INTERVAL_MS = 33
LABELS = {"listening": "Listening", "processing": "Thinking", "responding": "Speaking"}
PILL_COLOR = QColor(24, 27, 31, 238)
TEXT_COLOR = QColor(244, 246, 245)
GREEN = QColor(74, 196, 132)


class StatusPill(QWidget):
    def __init__(self, hide_delay_seconds: float = 0.6, fade_seconds: float = 0.3) -> None:
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
        self.setWindowTitle("Clicky status")
        self.resize(PILL_WIDTH + 2 * SHADOW, PILL_HEIGHT + 2 * SHADOW)
        self._hide_delay_seconds = hide_delay_seconds
        self._fade_seconds = fade_seconds
        self._state = "idle"
        self._idle_since: float | None = None
        self._shown_at = 0.0
        self._audio_level = 0.0
        self._font = QFont("Segoe UI", 10, QFont.Weight.DemiBold)
        self._capture_exclusion_applied = False
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.setInterval(FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    @property
    def label(self) -> str:
        return LABELS.get(self._state, "")

    @property
    def is_animating(self) -> bool:
        return self._timer.isActive()

    def set_state(self, state: str) -> None:
        if state in LABELS:
            self._state = state
            self._idle_since = None
            if not self.isVisible():
                self._dock()
                self._shown_at = time.monotonic()
                self.show()
                if not self._capture_exclusion_applied:
                    self._capture_exclusion_applied = exclude_window_from_capture(int(self.winId()))
            self._timer.start()
        elif state == "idle" and self.isVisible():
            self._idle_since = time.monotonic()
        self.update()

    def set_audio_level(self, level: float) -> None:
        self._audio_level = level if level > self._audio_level else self._audio_level * 0.7 + level * 0.3

    def _dock(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.move(available.center().x() - self.width() // 2, available.top() + 6)

    def _opacity(self, now: float) -> float:
        fade_in = min(1.0, (now - self._shown_at) / 0.15)
        if self._idle_since is None:
            return fade_in
        fade_start = self._idle_since + self._hide_delay_seconds
        if now < fade_start:
            return fade_in
        return max(0.0, 1.0 - (now - fade_start) / self._fade_seconds)

    def _tick(self) -> None:
        now = time.monotonic()
        if self._idle_since is not None and self._opacity(now) <= 0:
            self._state = "idle"
            self._timer.stop()
            self.hide()
            return
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        now = time.monotonic()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setOpacity(self._opacity(now))
        pill = QRectF(SHADOW, SHADOW, PILL_WIDTH, PILL_HEIGHT)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(0, 0, 0, 40))
        painter.drawRoundedRect(pill.adjusted(-2, 0, 2, 4), PILL_HEIGHT / 2 + 2, PILL_HEIGHT / 2 + 2)
        painter.setBrush(PILL_COLOR)
        painter.drawRoundedRect(pill, PILL_HEIGHT / 2, PILL_HEIGHT / 2)

        # Clicky's triangle.
        tip = QPointF(pill.left() + 16, pill.top() + 11)
        painter.setBrush(GREEN)
        painter.drawPolygon(QPolygonF([tip, QPointF(tip.x() + 4, tip.y() + 15), QPointF(tip.x() + 13, tip.y() + 7)]))

        painter.setFont(self._font)
        painter.setPen(TEXT_COLOR)
        painter.drawText(
            QRectF(pill.left() + 38, pill.top(), 100, PILL_HEIGHT),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.label,
        )

        indicator_left = pill.right() - 52
        center_y = pill.center().y()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(GREEN)
        if self._state == "processing":
            for index in range(3):
                pulse = 0.5 + 0.5 * math.sin(now * 6 - index * 0.8)
                painter.setOpacity(self._opacity(now) * (0.35 + 0.65 * pulse))
                painter.drawEllipse(QPointF(indicator_left + 8 + index * 13, center_y), 3.6, 3.6)
        else:
            for index in range(5):
                if self._state == "listening":
                    height = 4 + 18 * self._audio_level * (0.6 + 0.4 * math.sin(now * 9 + index * 1.4))
                else:
                    height = 6 + 10 * (0.5 + 0.5 * math.sin(now * 7 + index * 1.1))
                painter.drawRoundedRect(QRectF(indicator_left + index * 8, center_y - height / 2, 4, height), 2, 2)
        painter.end()
