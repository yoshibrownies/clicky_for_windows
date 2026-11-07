"""Draws an animation scene (scene.py) into any rectangle: axes, plots, arrows, shapes, text, captions.

Shared by the lesson card (inline animations) and anything else that shows scenes.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPen, QPolygonF, QTransform

from clicky.fonts import mono_font, ui_font
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


ICON_FILL_ALPHA = 0.14  # icons get a soft wash of their colour unless a fill is given
PATH_FILL_ALPHA = 0.35
FIGURE_PEN_WIDTH = 2.6


def _fill_color(item: DrawItem, default_alpha: float) -> QColor | None:
    """The brush for a fillable shape: its `fill` colour, nothing for "none", or its own colour at default_alpha."""
    if item.fill == "none":
        return None
    if item.fill:
        color = _color(item.fill, item.alpha)
        color.setAlphaF(color.alphaF() * max(default_alpha, PATH_FILL_ALPHA))
        return color
    if default_alpha <= 0:
        return None
    color = _color(item.color, item.alpha)
    color.setAlphaF(color.alphaF() * default_alpha)
    return color


def figure_pixel_points(item: DrawItem, mapper: WorldMapper) -> list[list[QPointF]]:
    """A path's or icon's outline in pixels: scaled uniformly (by the y axis), rotated counter-clockwise, then
    placed at (x, y)."""
    anchor_x, anchor_y = mapper.to_pixel(item.values["x"], item.values["y"])
    size = item.values.get("size", item.values.get("scale", 1.0))
    pixel_scale = max(-PIXEL_LIMIT, min(PIXEL_LIMIT, size * mapper.scale_y))
    angle = math.radians(item.values.get("rotate", 0.0))
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    outlines: list[list[QPointF]] = []
    for segment in item.segments:
        outline = []
        for local_x, local_y in segment:
            rotated_x = local_x * cos_a - local_y * sin_a
            rotated_y = local_x * sin_a + local_y * cos_a
            pixel_x = max(-PIXEL_LIMIT, min(PIXEL_LIMIT, anchor_x + rotated_x * pixel_scale))
            pixel_y = max(-PIXEL_LIMIT, min(PIXEL_LIMIT, anchor_y - rotated_y * pixel_scale))
            outline.append(QPointF(pixel_x, pixel_y))
        outlines.append(outline)
    return outlines


HIGHLIGHT_SECONDS = 3.0
HIGHLIGHT_GROW_SECONDS = 0.4
HIGHLIGHT_FADE_SECONDS = 0.4
HIGHLIGHT_PADDING = 9.0
HIGHLIGHT_COLOR = QColor(229, 72, 77)


class ScenePainter:
    """Holds the fonts and paints scenes. `focus_point` is where the action is in the last frame painted.

    A highlight (label, seconds since it began) rings the object with that label wherever it is in this frame, so
    the ring follows moving objects. `highlight_rect` is the ring drawn in the last frame (None if none).
    """

    def __init__(self) -> None:
        self._hand_font = ui_font(14, QFont.Weight.Medium)
        self._caption_font = ui_font(14, QFont.Weight.Medium)
        self._tick_font = mono_font(10)
        self._label_font = ui_font(12, QFont.Weight.Medium)
        self.focus_point: QPointF | None = None
        self.highlight_rect: QRectF | None = None

    def paint(
        self, painter: QPainter, area: QRectF, scene: Scene, t: float, highlight: tuple[str, float] | None = None
    ) -> None:
        self.focus_point = None
        self.highlight_rect = None
        self._paint_scene(painter, area, scene, t, highlight)
        if self.focus_point is not None:
            # The buddy follows this point: keep it inside the panel, whatever the scene's numbers were.
            self.focus_point = QPointF(
                max(area.left(), min(area.right(), self.focus_point.x())),
                max(area.top(), min(area.bottom(), self.focus_point.y())),
            )

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

    def _paint_scene(
        self, painter: QPainter, board: QRectF, scene: Scene, t: float, highlight: tuple[str, float] | None = None
    ) -> None:
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

        wanted = highlight[0].casefold().strip() if highlight is not None else ""
        target: QRectF | None = None
        painter.save()
        painter.setClipRect(plot.adjusted(-6, -6, 6, 6))
        for item in scene.frame(t):
            bounds = self._paint_item(painter, mapper, item)
            if (
                wanted
                and target is None
                and bounds is not None
                and wanted in (item.label.casefold(), item.text.casefold())
            ):
                target = bounds
        painter.restore()
        if highlight is not None and target is not None:
            self._paint_highlight(painter, target, highlight[1], board)

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

    def _paint_highlight(self, painter: QPainter, target: QRectF, elapsed: float, board: QRectF) -> None:
        """A red ring that draws itself around the target, holds, then fades."""
        if elapsed < 0 or elapsed >= HIGHLIGHT_SECONDS:
            return
        grow = min(1.0, elapsed / HIGHLIGHT_GROW_SECONDS)
        fade = min(1.0, (HIGHLIGHT_SECONDS - elapsed) / HIGHLIGHT_FADE_SECONDS)
        # An ellipse that hugs the object (a tall bar gets a tall ring), never smaller than a small circle, kept
        # inside the animation panel so it can't spill over the card's notes.
        center = target.center()
        width = max(target.width(), 14.0) + 2 * HIGHLIGHT_PADDING
        height = max(target.height(), 14.0) + 2 * HIGHLIGHT_PADDING
        ring = QRectF(center.x() - width / 2, center.y() - height / 2, width, height)
        ring = ring.intersected(board.adjusted(3, 3, -3, -3))
        if ring.isEmpty():
            return
        color = QColor(HIGHLIGHT_COLOR)
        color.setAlphaF(fade)
        painter.save()
        painter.setPen(QPen(color, 3.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawArc(ring, 90 * 16, -int(360 * 16 * grow))
        painter.restore()
        self.highlight_rect = ring
        self.focus_point = ring.center()

    def _paint_item(self, painter: QPainter, mapper: WorldMapper, item: DrawItem) -> QRectF | None:
        """Paint one object; returns its bounds on screen (for highlights), or None if it has none."""
        values = item.values
        bounds: QRectF | None = None
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
            if item.fill:
                brush = _fill_color(item, 1.0)
                painter.setPen(QPen(color, 2))
                painter.setBrush(brush if brush is not None else Qt.BrushStyle.NoBrush)
            else:
                painter.setPen(QPen(QColor(255, 255, 255, int(230 * item.alpha)), 1.6))
                painter.setBrush(color)
            painter.drawEllipse(center, radius, radius)
            label_anchor = QPointF(center.x() + radius + 4, center.y() - radius)
            bounds = QRectF(center.x() - radius, center.y() - radius, 2 * radius, 2 * radius)
            if self.focus_point is None:
                self.focus_point = QPointF(center)
        elif item.kind == "rect":
            x1, y1 = mapper.to_pixel(values["x"], values["y"])
            x2, y2 = mapper.to_pixel(values["x"] + values["w"], values["y"] + values["h"])
            rect = QRectF(QPointF(min(x1, x2), min(y1, y2)), QPointF(max(x1, x2), max(y1, y2)))
            fill = _fill_color(item, 0.55)
            painter.setPen(QPen(color, 2))
            painter.setBrush(fill if fill is not None else Qt.BrushStyle.NoBrush)
            rotation = values.get("rotate", 0.0)
            if rotation:
                pivot = {
                    "bottom-right": rect.bottomRight(),
                    "center": rect.center(),
                }.get(item.pivot, rect.bottomLeft())
                transform = (
                    QTransform().translate(pivot.x(), pivot.y()).rotate(-rotation).translate(-pivot.x(), -pivot.y())
                )
                painter.save()
                painter.setTransform(transform, True)
                painter.drawRoundedRect(rect, 4, 4)
                painter.restore()
                rect = transform.mapRect(rect)
            else:
                painter.drawRoundedRect(rect, 4, 4)
            label_anchor = QPointF(rect.left(), rect.top() - 6)
            bounds = rect
        elif item.kind == "line":
            line_start = QPointF(*mapper.to_pixel(values["x1"], values["y1"]))
            line_end = QPointF(*mapper.to_pixel(values["x2"], values["y2"]))
            painter.setPen(pen)
            painter.drawLine(line_start, line_end)
            bounds = QRectF(line_start, line_end).normalized()
        elif item.kind == "arrow":
            start = QPointF(*mapper.to_pixel(values["x"], values["y"]))
            vector_x, vector_y = mapper.vector_to_pixel(values["dx"], values["dy"])
            end = QPointF(start.x() + vector_x, start.y() + vector_y)
            bounds = QRectF(start, end).normalized()
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
            font = ui_font(int(max(9, min(40, values.get("size", 14)))), QFont.Weight.Medium)
            painter.setFont(font)
            painter.setPen(color)
            baseline = QPointF(*mapper.to_pixel(values["x"], values["y"]))
            painter.drawText(baseline, item.text)
            text_rect = QFontMetricsF(font).boundingRect(item.text)
            bounds = text_rect.translated(baseline)
        elif item.kind in ("path", "icon"):
            outlines = [outline for outline in figure_pixel_points(item, mapper) if len(outline) > 1]
            if outlines:
                fill = _fill_color(item, ICON_FILL_ALPHA if item.kind == "icon" else 0.0)
                draw_progress = max(0.0, min(1.0, values.get("draw", 1.0)))
                if fill is not None:
                    fill.setAlphaF(fill.alphaF() * draw_progress)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(fill)
                    for outline in outlines:
                        closed = len(outline) > 2 and (outline[0] - outline[-1]).manhattanLength() < 0.5
                        if closed:
                            shape = QPainterPath()
                            shape.addPolygon(QPolygonF(outline))
                            painter.drawPath(shape)
                painter.setPen(
                    QPen(
                        color,
                        FIGURE_PEN_WIDTH,
                        Qt.PenStyle.SolidLine,
                        Qt.PenCapStyle.RoundCap,
                        Qt.PenJoinStyle.RoundJoin,
                    )
                )
                painter.setBrush(Qt.BrushStyle.NoBrush)
                for outline in outlines:
                    painter.drawPolyline(QPolygonF(outline))
                all_points = [point for outline in outlines for point in outline]
                xs = [point.x() for point in all_points]
                ys = [point.y() for point in all_points]
                bounds = QRectF(QPointF(min(xs), min(ys)), QPointF(max(xs), max(ys)))
                label_anchor = QPointF(bounds.right() + 4, bounds.top() + 12)
                if self.focus_point is None:
                    # While an outline sketches itself in, the pen is at its newest point.
                    self.focus_point = QPointF(outlines[-1][-1]) if draw_progress < 1.0 else bounds.center()
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
                bounds = QRectF(label_anchor.x() - 6, label_anchor.y() - 6, 12, 12)  # the plot's moving head
                if self.focus_point is None:
                    self.focus_point = QPointF(label_anchor)

        if item.label and label_anchor is not None:
            painter.setFont(self._label_font)
            painter.setPen(color)
            painter.drawText(label_anchor, item.label)
        return bounds
