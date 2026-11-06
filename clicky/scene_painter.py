"""Draws an animation scene (scene.py) into any rectangle: axes, plots, arrows, shapes, text, captions.

Shared by the lesson card (inline animations) and anything else that shows scenes.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPen, QPolygonF

from clicky.handwriting import _handwriting_font
from clicky.scene import DrawItem, Scene

PIXEL_LIMIT = 10_000.0
BOARD_COLOR = QColor(255, 255, 255)

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


class ScenePainter:
    """Holds the fonts and paints scenes. `focus_point` is where the action is in the last frame painted."""

    def __init__(self) -> None:
        self._hand_font = _handwriting_font(16)
        self._caption_font = _handwriting_font(17)
        self._tick_font = QFont("Segoe UI", 8)
        self._label_font = _handwriting_font(14)
        self.focus_point: QPointF | None = None

    def paint(self, painter: QPainter, area: QRectF, scene: Scene, t: float) -> None:
        self.focus_point = None
        self._paint_scene(painter, area, scene, t)

    def _plot_rect(self, board: QRectF, scene: Scene) -> QRectF:
        left_margin = 58 if scene.axes else 20
        # Room at the bottom for tick labels (axes) and the caption line, only when they exist.
        bottom_margin = (66 if scene.axes else 14) + (0 if scene.axes or not scene.captions else 30)
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
        if not scene.axes:
            return  # a free-form scene (no axes) reads more like a sketch without grid lines
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
            if self.focus_point is None:
                self.focus_point = QPointF(center)
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
            # Label above the middle of the arrow, so it never sits on the arrow itself.
            label_width = QFontMetricsF(self._label_font).horizontalAdvance(item.label)
            label_anchor = QPointF((start.x() + end.x()) / 2 - label_width / 2, min(start.y(), end.y()) - 8)
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
                if self.focus_point is None:
                    self.focus_point = QPointF(label_anchor)

        if item.label and label_anchor is not None:
            painter.setFont(self._label_font)
            painter.setPen(color)
            painter.drawText(label_anchor, item.label)
