"""Hand-drawn underlines and circles on the real screen, drawn in time with Clicky's speech.

One transparent, click-through, always-on-top window per monitor (created on demand), excluded from screen
capture so the model never sees its own marks. The frame timer runs only while something is drawing or fading.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QPoint, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPainterPath, QPen, QScreen
from PySide6.QtWidgets import QWidget

from clicky.animation import ease_in_out
from clicky.overlay import exclude_window_from_capture

logger = logging.getLogger(__name__)

Point = tuple[float, float]

UNDERLINE_COLOR = QColor(250, 204, 21, 210)  # highlighter yellow
CIRCLE_COLOR = QColor(244, 63, 94, 235)  # coral red
UNDERLINE_WIDTH = 5.0
CIRCLE_WIDTH = 2.8
UNDERLINE_DRAW_SECONDS = 0.45
CIRCLE_DRAW_SECONDS = 0.6
DEFAULT_LINGER_SECONDS = 4.0
DEFAULT_FADE_SECONDS = 0.6
CLEAR_FADE_SECONDS = 0.2
FRAME_INTERVAL_MS = 16
LINGER_CHECK_INTERVAL_MS = 100


def underline_points(left: float, right: float, text_bottom: float, seed: int, segments: int = 24) -> list[Point]:
    """A slightly wavy line from left to right a few pixels under the text, like a quick pen stroke."""
    baseline = text_bottom + 4.0
    phase = (seed * 2.399) % (2 * math.pi)
    points: list[Point] = []
    for index in range(segments + 1):
        progress = index / segments
        x = left + (right - left) * progress
        wobble = 1.3 * math.sin(progress * 5.0 + phase) + 0.6 * math.sin(progress * 13.0 + phase * 1.7)
        # The stroke rises a touch at the end, as a real hand does.
        points.append((x, baseline + 1.5 + wobble + progress * 1.2))
    return points


def ellipse_points(box: tuple[float, float, float, float], seed: int, segments: int = 56) -> list[Point]:
    """A loose ellipse around the box that goes a bit past where it started, like a circled answer."""
    left, top, right, bottom = box
    center_x, center_y = (left + right) / 2, (top + bottom) / 2
    radius_x = (right - left) / 2 * 1.18 + 8
    radius_y = (bottom - top) / 2 * 1.3 + 8
    start_angle = -math.pi * 0.75 + (seed % 7) * 0.05
    sweep = 2 * math.pi * 1.08
    points: list[Point] = []
    for index in range(segments + 1):
        progress = index / segments
        angle = start_angle + sweep * progress
        drift = 1.0 + 0.06 * progress + 0.025 * math.sin(progress * 9 + seed)
        points.append((center_x + radius_x * drift * math.cos(angle), center_y + radius_y * drift * math.sin(angle)))
    return points


def partial_polyline(points: list[Point], progress: float) -> list[Point]:
    """The part of the stroke drawn so far, by length, with the last point interpolated."""
    if progress <= 0 or len(points) < 2:
        return points[:1]
    if progress >= 1:
        return list(points)
    lengths = [math.dist(points[index], points[index + 1]) for index in range(len(points) - 1)]
    target = sum(lengths) * progress
    drawn: list[Point] = [points[0]]
    for index, segment_length in enumerate(lengths):
        if target <= segment_length:
            ratio = 0.0 if segment_length == 0 else target / segment_length
            (x1, y1), (x2, y2) = points[index], points[index + 1]
            drawn.append((x1 + (x2 - x1) * ratio, y1 + (y2 - y1) * ratio))
            return drawn
        target -= segment_length
        drawn.append(points[index + 1])
    return drawn


@dataclass
class _Mark:
    points: list[Point]  # local window coordinates
    color: QColor
    width: float
    started_at: float
    draw_seconds: float
    fade_at: float | None = None
    fade_seconds: float = DEFAULT_FADE_SECONDS
    progress: float = field(default=0.0)

    def opacity(self, now: float) -> float:
        if self.fade_at is None or now < self.fade_at:
            return 1.0
        return max(0.0, 1.0 - (now - self.fade_at) / self.fade_seconds)

    def is_gone(self, now: float) -> bool:
        return self.opacity(now) <= 0.0

    def is_moving(self, now: float) -> bool:
        drawing = now - self.started_at < self.draw_seconds
        fading = self.fade_at is not None and now >= self.fade_at and not self.is_gone(now)
        return drawing or fading


class _ScreenLayerWindow(QWidget):
    def __init__(self, screen: QScreen) -> None:
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
        self.setWindowTitle("Clicky marks")
        self.screen_geometry = screen.geometry()
        self.setGeometry(self.screen_geometry)
        self.marks: list[_Mark] = []
        self._capture_exclusion_applied = False

    def show_if_needed(self) -> None:
        if self.isVisible():
            return
        self.show()
        if not self._capture_exclusion_applied:
            self._capture_exclusion_applied = exclude_window_from_capture(int(self.winId()))

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        now = time.monotonic()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        for mark in self.marks:
            opacity = mark.opacity(now)
            if opacity <= 0:
                continue
            draw_progress = ease_in_out(min(1.0, (now - mark.started_at) / mark.draw_seconds))
            stroke = partial_polyline(mark.points, draw_progress)
            if len(stroke) < 2:
                continue
            path = QPainterPath(QPointF(*stroke[0]))
            for x, y in stroke[1:]:
                path.lineTo(x, y)
            color = QColor(mark.color)
            color.setAlphaF(color.alphaF() * opacity)
            painter.setPen(
                QPen(color, mark.width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)
        painter.end()


class AnnotationLayer(QObject):
    emptied = Signal()  # the last mark faded away (or was cleared)

    def __init__(
        self,
        linger_seconds: float = DEFAULT_LINGER_SECONDS,
        fade_seconds: float = DEFAULT_FADE_SECONDS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._linger_seconds = linger_seconds
        self._fade_seconds = fade_seconds
        self._windows: dict[str, _ScreenLayerWindow] = {}
        self._mark_count = 0
        self._had_marks = False
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.setInterval(FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    @property
    def is_animating(self) -> bool:
        return self._timer.isActive()

    def visible_windows(self) -> list[QWidget]:
        return [window for window in self._windows.values() if window.isVisible()]

    def add_mark(self, event) -> None:
        """Draw an underline or circle for a controller.ScreenVisualEvent (global logical box)."""
        if event.box is None or event.kind not in ("underline", "circle"):
            return
        left, top, right, bottom = event.box
        screen = QGuiApplication.screenAt(QPoint(round((left + right) / 2), round((top + bottom) / 2)))
        screen = screen or QGuiApplication.primaryScreen()
        if screen is None:
            return
        window = self._window_for(screen)
        origin = window.screen_geometry.topLeft()
        local_box = (left - origin.x(), top - origin.y(), right - origin.x(), bottom - origin.y())
        self._mark_count += 1
        if event.kind == "underline":
            mark = _Mark(
                underline_points(local_box[0], local_box[2], local_box[3], seed=self._mark_count),
                UNDERLINE_COLOR,
                UNDERLINE_WIDTH,
                time.monotonic(),
                UNDERLINE_DRAW_SECONDS,
            )
        else:
            mark = _Mark(
                ellipse_points(local_box, seed=self._mark_count),
                CIRCLE_COLOR,
                CIRCLE_WIDTH,
                time.monotonic(),
                CIRCLE_DRAW_SECONDS,
            )
        window.marks.append(mark)
        self._had_marks = True
        window.show_if_needed()
        self._timer.start(FRAME_INTERVAL_MS)

    def finish(self) -> None:
        """The reply is over: keep the marks a little longer, then fade them."""
        self._schedule_fade(time.monotonic() + self._linger_seconds, self._fade_seconds)

    def clear(self) -> None:
        """A new question: fade everything out quickly."""
        self._schedule_fade(time.monotonic(), CLEAR_FADE_SECONDS)

    def close_all(self) -> None:
        self._timer.stop()
        for window in self._windows.values():
            window.close()
            window.deleteLater()
        self._windows.clear()

    def _schedule_fade(self, fade_at: float, fade_seconds: float) -> None:
        any_marks = False
        for window in self._windows.values():
            for mark in window.marks:
                if mark.fade_at is None or fade_at < mark.fade_at:
                    mark.fade_at = fade_at
                    mark.fade_seconds = fade_seconds
                any_marks = True
        if any_marks:
            self._timer.start(FRAME_INTERVAL_MS)

    def _window_for(self, screen: QScreen) -> _ScreenLayerWindow:
        key = f"{screen.name()}|{screen.geometry().getRect()}"
        window = self._windows.get(key)
        if window is None:
            window = _ScreenLayerWindow(screen)
            self._windows[key] = window
        return window

    def _tick(self) -> None:
        now = time.monotonic()
        anything_moving = False
        waiting_to_fade = False
        for window in self._windows.values():
            window.marks = [mark for mark in window.marks if not mark.is_gone(now)]
            if not window.marks:
                if window.isVisible():
                    window.hide()
                continue
            if any(mark.is_moving(now) for mark in window.marks):
                anything_moving = True
                window.update()  # repaint only while a stroke is drawing or fading
            elif any(mark.fade_at is not None for mark in window.marks):
                waiting_to_fade = True
        if self._had_marks and not any(window.marks for window in self._windows.values()):
            self._had_marks = False
            self.emptied.emit()
        if anything_moving:
            self._timer.setInterval(FRAME_INTERVAL_MS)
        elif waiting_to_fade:
            self._timer.setInterval(LINGER_CHECK_INTERVAL_MS)  # nothing to draw; check back for the fade
        else:
            self._timer.stop()
            self._timer.setInterval(FRAME_INTERVAL_MS)
