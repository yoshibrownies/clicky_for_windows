"""The whiteboard: plays the animation scenes Clicky writes (see scene.py) in a paper-white panel.

Click-through, always on top, excluded from screen capture, docked to the left of the notepad. 60 fps while the
scene plays; afterwards it holds the last frame with the timer stopped, lingers, then fades.
"""

from __future__ import annotations

import logging
import math
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

from clicky.notepad import PAPER_WIDTH as NOTEPAD_PAPER_WIDTH
from clicky.notepad import SHADOW, _handwriting_font
from clicky.overlay import exclude_window_from_capture
from clicky.scene import DrawItem, Scene

logger = logging.getLogger(__name__)

BOARD_WIDTH = 520
BOARD_HEIGHT = 390
FRAME_INTERVAL_MS = 16
IDLE_CHECK_INTERVAL_MS = 200
DEFAULT_LINGER_SECONDS = 20.0
DEFAULT_FADE_SECONDS = 0.6
CLEAR_FADE_SECONDS = 0.2
PIXEL_LIMIT = 10_000.0

COLORS = {
    "blue": QColor(37, 99, 235),
    "red": QColor(220, 38, 38),
    "green": QColor(22, 163, 74),
    "orange": QColor(234, 88, 12),
    "purple": QColor(124, 58, 237),
    "teal": QColor(13, 148, 136),
    "gray": QColor(100, 116, 139),
    "black": QColor(30, 41, 59),
    "yellow": QColor(202, 138, 4),
}
BOARD_COLOR = QColor(255, 255, 255)
GRID_COLOR = QColor(226, 232, 240)
AXIS_COLOR = QColor(71, 85, 105)


def nice_ticks(low: float, high: float, target_count: int = 6) -> list[float]:
    """Round-numbered tick positions (1, 2 or 5 times a power of ten) spanning low..high."""
    span = high - low
    if span <= 0 or not math.isfinite(span):
        return [low]
    raw_step = span / (target_count - 1)
    magnitude = 10 ** math.floor(math.log10(raw_step))
    normalized = raw_step / magnitude
    step = min((1, 2, 5, 10), key=lambda candidate: abs(candidate - normalized)) * magnitude
    first = math.ceil(low / step - 1e-9) * step
    ticks: list[float] = []
    value = first
    while value <= high + step * 1e-6 and len(ticks) < 25:
        ticks.append(round(value, 10) + 0.0)
        value += step
    return ticks


class WorldMapper:
    """World coordinates (y up) to pixel coordinates inside a rectangle (y down)."""

    def __init__(self, world: tuple[float, float, float, float], rect: tuple[float, float, float, float]) -> None:
        self.x_min, self.x_max, self.y_min, self.y_max = world
        self.left, self.top, self.width, self.height = rect
        self.scale_x = self.width / (self.x_max - self.x_min)
        self.scale_y = self.height / (self.y_max - self.y_min)

    def to_pixel(self, x: float, y: float) -> tuple[float, float]:
        pixel_x = self.left + (x - self.x_min) * self.scale_x
        pixel_y = self.top + self.height - (y - self.y_min) * self.scale_y
        return (max(-PIXEL_LIMIT, min(PIXEL_LIMIT, pixel_x)), max(-PIXEL_LIMIT, min(PIXEL_LIMIT, pixel_y)))

    def vector_to_pixel(self, dx: float, dy: float) -> tuple[float, float]:
        return (
            max(-PIXEL_LIMIT, min(PIXEL_LIMIT, dx * self.scale_x)),
            max(-PIXEL_LIMIT, min(PIXEL_LIMIT, -dy * self.scale_y)),
        )


def _color(name: str, alpha: float = 1.0) -> QColor:
    color = QColor(COLORS.get(name, COLORS["blue"]))
    color.setAlphaF(max(0.0, min(1.0, color.alphaF() * alpha)))
    return color


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
        self._hand_font = _handwriting_font(16)
        self._caption_font = _handwriting_font(17)
        self._tick_font = QFont("Segoe UI", 8)
        self._label_font = _handwriting_font(14)
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
                self._paint_scene(painter, board, scene, self.current_time())
            except Exception:  # a broken frame must never take the app down
                logger.exception("Whiteboard frame failed")
        painter.end()

    def _plot_rect(self, board: QRectF, scene: Scene) -> QRectF:
        left_margin = 58 if scene.axes else 20
        bottom_margin = 66 if scene.axes else 44
        top_margin = 44 if scene.title else 18
        return QRectF(
            board.left() + left_margin,
            board.top() + top_margin,
            board.width() - left_margin - 22,
            board.height() - top_margin - bottom_margin,
        )

    def _paint_scene(self, painter: QPainter, board: QRectF, scene: Scene, t: float) -> None:
        plot = self._plot_rect(board, scene)
        mapper = WorldMapper(scene.world, (plot.left(), plot.top(), plot.width(), plot.height()))

        if scene.title:
            painter.setFont(self._hand_font)
            painter.setPen(COLORS["black"])
            painter.drawText(
                QRectF(board.left() + 18, board.top() + 10, board.width() - 36, 28),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                scene.title,
            )

        self._paint_grid_and_axes(painter, plot, mapper, scene)

        painter.save()
        painter.setClipRect(plot.adjusted(-6, -6, 6, 6))
        for item in scene.frame(t):
            self._paint_item(painter, mapper, item)
        painter.restore()

        caption = scene.caption_at(t)
        if caption is not None:
            text, alpha = caption
            painter.save()
            painter.setOpacity(painter.opacity() * alpha)
            painter.setFont(self._caption_font)
            painter.setPen(COLORS["black"])
            painter.drawText(
                QRectF(board.left() + 18, board.bottom() - 34, board.width() - 36, 26),
                Qt.AlignmentFlag.AlignCenter,
                text,
            )
            painter.restore()

    def _paint_grid_and_axes(self, painter: QPainter, plot: QRectF, mapper: WorldMapper, scene: Scene) -> None:
        x_min, x_max, y_min, y_max = scene.world
        x_ticks, y_ticks = nice_ticks(x_min, x_max), nice_ticks(y_min, y_max)
        painter.setPen(QPen(GRID_COLOR, 1))
        for tick in x_ticks:
            x, _ = mapper.to_pixel(tick, y_min)
            painter.drawLine(QPointF(x, plot.top()), QPointF(x, plot.bottom()))
        for tick in y_ticks:
            _, y = mapper.to_pixel(x_min, tick)
            painter.drawLine(QPointF(plot.left(), y), QPointF(plot.right(), y))
        if not scene.axes:
            return
        painter.setPen(QPen(AXIS_COLOR, 1.6))
        painter.drawLine(QPointF(plot.left(), plot.bottom()), QPointF(plot.right(), plot.bottom()))
        painter.drawLine(QPointF(plot.left(), plot.top()), QPointF(plot.left(), plot.bottom()))
        painter.setFont(self._tick_font)
        metrics = QFontMetricsF(self._tick_font)
        for tick in x_ticks:
            x, _ = mapper.to_pixel(tick, y_min)
            text = f"{tick:g}"
            painter.drawText(QPointF(x - metrics.horizontalAdvance(text) / 2, plot.bottom() + 14), text)
        for tick in y_ticks:
            _, y = mapper.to_pixel(x_min, tick)
            text = f"{tick:g}"
            painter.drawText(QPointF(plot.left() - metrics.horizontalAdvance(text) - 6, y + 4), text)
        x_label, y_label = scene.axes
        painter.setFont(self._label_font)
        if x_label:
            painter.drawText(
                QRectF(plot.left(), plot.bottom() + 16, plot.width(), 20), Qt.AlignmentFlag.AlignCenter, x_label
            )
        if y_label:
            painter.save()
            painter.translate(plot.left() - 44, plot.center().y())
            painter.rotate(-90)
            painter.drawText(QRectF(-plot.height() / 2, -10, plot.height(), 20), Qt.AlignmentFlag.AlignCenter, y_label)
            painter.restore()

    def _paint_item(self, painter: QPainter, mapper: WorldMapper, item: DrawItem) -> None:
        values = item.values
        color = _color(item.color, item.alpha)
        pen = QPen(
            color,
            3,
            Qt.PenStyle.DashLine if item.dashed else Qt.PenStyle.SolidLine,
            Qt.PenCapStyle.RoundCap,
            Qt.PenJoinStyle.RoundJoin,
        )

        if item.trail and len(item.trail) > 1:
            trail_color = _color(item.color, item.alpha * 0.35)
            painter.setPen(QPen(trail_color, 2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            points = [QPointF(*mapper.to_pixel(x, y)) for x, y in item.trail]
            painter.drawPolyline(QPolygonF(points))

        label_anchor: QPointF | None = None
        if item.kind in ("circle", "point"):
            center = QPointF(*mapper.to_pixel(values["x"], values["y"]))
            radius = max(1.0, min(80.0, values.get("r", 10.0)))
            painter.setPen(QPen(QColor(255, 255, 255, int(230 * item.alpha)), 1.6))
            painter.setBrush(color)
            painter.drawEllipse(center, radius, radius)
            label_anchor = QPointF(center.x() + radius + 4, center.y() - radius)
        elif item.kind == "rect":
            x1, y1 = mapper.to_pixel(values["x"], values["y"])
            x2, y2 = mapper.to_pixel(values["x"] + values["w"], values["y"] + values["h"])
            rect = QRectF(QPointF(min(x1, x2), min(y1, y2)), QPointF(max(x1, x2), max(y1, y2)))
            fill = QColor(color)
            fill.setAlphaF(fill.alphaF() * 0.55)
            painter.setPen(QPen(color, 2))
            painter.setBrush(fill)
            painter.drawRoundedRect(rect, 4, 4)
            label_anchor = QPointF(rect.left(), rect.top() - 6)
        elif item.kind == "line":
            painter.setPen(pen)
            painter.drawLine(
                QPointF(*mapper.to_pixel(values["x1"], values["y1"])),
                QPointF(*mapper.to_pixel(values["x2"], values["y2"])),
            )
        elif item.kind == "arrow":
            start = QPointF(*mapper.to_pixel(values["x"], values["y"]))
            vector_x, vector_y = mapper.vector_to_pixel(values["dx"], values["dy"])
            end = QPointF(start.x() + vector_x, start.y() + vector_y)
            painter.setPen(pen)
            painter.drawLine(start, end)
            length = math.hypot(vector_x, vector_y)
            if length > 4:
                angle = math.atan2(vector_y, vector_x)
                size = min(12.0, length * 0.4)
                left = QPointF(end.x() - size * math.cos(angle - 0.45), end.y() - size * math.sin(angle - 0.45))
                right = QPointF(end.x() - size * math.cos(angle + 0.45), end.y() - size * math.sin(angle + 0.45))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(color)
                painter.drawPolygon(QPolygonF([end, left, right]))
            label_anchor = QPointF(end.x() + 6, end.y() - 4)
        elif item.kind == "text":
            font = _handwriting_font(int(max(9, min(40, values.get("size", 15)))))
            painter.setFont(font)
            painter.setPen(color)
            painter.drawText(QPointF(*mapper.to_pixel(values["x"], values["y"])), item.text)
        elif item.kind == "plot":
            painter.setPen(
                QPen(
                    color,
                    2.6,
                    Qt.PenStyle.DashLine if item.dashed else Qt.PenStyle.SolidLine,
                    Qt.PenCapStyle.RoundCap,
                    Qt.PenJoinStyle.RoundJoin,
                )
            )
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for segment in item.segments:
                painter.drawPolyline(QPolygonF([QPointF(*mapper.to_pixel(x, y)) for x, y in segment]))
                label_anchor = QPointF(*mapper.to_pixel(*segment[-1]))

        if item.label and label_anchor is not None:
            painter.setFont(self._label_font)
            painter.setPen(color)
            painter.drawText(label_anchor, item.label)
