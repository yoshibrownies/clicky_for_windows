"""Clicky's notepad: a paper panel where key points are hand-written live and diagrams draw themselves.

Click-through, always on top and excluded from screen capture, docked at the right of the cursor's monitor.
Notes are typed one after another in a handwriting font; a diagram (boxes, then arrows) draws below them.
It lingers after the reply ends, then fades. The frame timer runs only while something is moving.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontDatabase,
    QFontMetricsF,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
)
from PySide6.QtWidgets import QWidget

from clicky.animation import ease_in_out
from clicky.diagram import Diagram, layout_diagram, parse_diagram
from clicky.overlay import exclude_window_from_capture

logger = logging.getLogger(__name__)

PAPER_WIDTH = 340
SHADOW = 12
HEADER_HEIGHT = 46
LINE_HEIGHT = 28
TEXT_LEFT = 58  # just right of the red margin line
TEXT_RIGHT_PADDING = 20
DIAGRAM_HEIGHT = 200
BOTTOM_PADDING = 18
NODE_APPEAR_SECONDS = 0.22
EDGE_DRAW_SECONDS = 0.3
DEFAULT_CHARACTERS_PER_SECOND = 45.0
DEFAULT_LINGER_SECONDS = 20.0
DEFAULT_FADE_SECONDS = 0.6
CLEAR_FADE_SECONDS = 0.2
FRAME_INTERVAL_MS = 16
IDLE_CHECK_INTERVAL_MS = 200
HANDWRITING_FONTS = ("Ink Free", "Segoe Print", "Comic Sans MS")

PAPER_COLOR = QColor(255, 251, 235)
RULE_COLOR = QColor(191, 219, 254, 170)
MARGIN_COLOR = QColor(248, 113, 113, 160)
INK_COLOR = QColor(30, 41, 59)
NODE_FILL = QColor(219, 234, 254)
NODE_BORDER = QColor(59, 130, 246)
ARROW_COLOR = QColor(71, 85, 105)


def wrap_text(text: str, measure: Callable[[str], float], max_width: float) -> list[str]:
    """Greedy word wrap; words longer than a line are split."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if measure(candidate) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = ""
        while measure(word) > max_width and len(word) > 1:
            cut = len(word)
            while cut > 1 and measure(word[:cut]) > max_width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        lines.append(current)
    return lines


def typed_characters(elapsed_seconds: float, characters_per_second: float, total_characters: int) -> int:
    if elapsed_seconds <= 0:
        return 0
    return min(total_characters, int(elapsed_seconds * characters_per_second))


def _handwriting_font(pixel_size: int) -> QFont:
    available = set(QFontDatabase.families())
    family = next((name for name in HANDWRITING_FONTS if name in available), "Segoe UI")
    font = QFont(family)
    font.setPixelSize(pixel_size)
    return font


@dataclass
class _Note:
    text: str
    wrapped_lines: list[str]
    starts_at: float

    def ends_at(self, characters_per_second: float) -> float:
        return self.starts_at + len(self.text) / characters_per_second


@dataclass
class _DrawnDiagram:
    diagram: Diagram
    starts_at: float

    @property
    def ends_at(self) -> float:
        return (
            self.starts_at
            + len(self.diagram.nodes) * NODE_APPEAR_SECONDS
            + len(self.diagram.edges) * EDGE_DRAW_SECONDS
            + 0.05
        )


class NotepadWindow(QWidget):
    def __init__(
        self,
        linger_seconds: float = DEFAULT_LINGER_SECONDS,
        fade_seconds: float = DEFAULT_FADE_SECONDS,
        characters_per_second: float = DEFAULT_CHARACTERS_PER_SECOND,
    ) -> None:
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
        self.setWindowTitle("Clicky's notes")
        self._linger_seconds = linger_seconds
        self._fade_seconds = fade_seconds
        self._characters_per_second = characters_per_second
        self._note_font = _handwriting_font(17)
        self._label_font = _handwriting_font(14)
        self._header_font = QFont("Segoe UI", 9, QFont.Weight.DemiBold)
        self._note_metrics = QFontMetricsF(self._note_font)
        self._enabled = True
        self._notes: list[_Note] = []
        self._diagram: _DrawnDiagram | None = None
        self._fade_at: float | None = None
        self._active_fade_seconds = fade_seconds
        self._capture_exclusion_applied = False
        self.resize(PAPER_WIDTH + 2 * SHADOW, self._content_height())

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.setInterval(FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    # ----- public API (GUI thread) -----

    @property
    def is_animating(self) -> bool:
        return self._timer.isActive() and self._timer.interval() == FRAME_INTERVAL_MS

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self.clear()

    def add_note(self, text: str) -> None:
        if not self._enabled or not text.strip():
            return
        available_width = PAPER_WIDTH - TEXT_LEFT - TEXT_RIGHT_PADDING - 12
        wrapped = wrap_text(text, self._note_metrics.horizontalAdvance, available_width) or [text]
        self._notes.append(_Note(text=text, wrapped_lines=wrapped, starts_at=self._next_start_time()))
        self._reveal()

    def set_diagram(self, spec: str) -> None:
        if not self._enabled:
            return
        diagram = parse_diagram(spec)
        if not diagram.nodes:
            return
        self._diagram = _DrawnDiagram(diagram=diagram, starts_at=self._next_start_time())
        self._reveal()

    def finish(self) -> None:
        """The reply ended: keep the notes up a while, then fade."""
        if self._notes or self._diagram:
            self._fade_at = time.monotonic() + self._linger_seconds
            self._active_fade_seconds = self._fade_seconds
            self._timer.start(FRAME_INTERVAL_MS)

    def clear(self) -> None:
        if self.isVisible() and (self._notes or self._diagram):
            self._fade_at = time.monotonic()
            self._active_fade_seconds = CLEAR_FADE_SECONDS
            self._timer.start(FRAME_INTERVAL_MS)
        else:
            self._reset()

    def typed_character_count(self) -> int:
        now = time.monotonic()
        return sum(
            typed_characters(now - note.starts_at, self._characters_per_second, len(note.text)) for note in self._notes
        )

    def diagram_node_count(self) -> int:
        return len(self._diagram.diagram.nodes) if self._diagram else 0

    def diagram_fully_drawn(self) -> bool:
        return self._diagram is not None and time.monotonic() >= self._diagram.ends_at

    # ----- internals -----

    def _next_start_time(self) -> float:
        now = time.monotonic()
        latest_end = now
        if self._notes:
            latest_end = max(latest_end, self._notes[-1].ends_at(self._characters_per_second))
        if self._diagram:
            latest_end = max(latest_end, self._diagram.ends_at)
        return latest_end

    def _reveal(self) -> None:
        self._fade_at = None
        height = self._content_height()
        was_visible = self.isVisible()
        if not was_visible:
            self._dock()
        if height > self.height():
            self.resize(self.width(), height)
        if not was_visible:
            self.show()
            if not self._capture_exclusion_applied:
                self._capture_exclusion_applied = exclude_window_from_capture(int(self.winId()))
        self._timer.start(FRAME_INTERVAL_MS)

    def _dock(self) -> None:
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        self.move(available.right() - self.width() - 16, available.top() + 72)

    def _note_line_count(self) -> int:
        return sum(len(note.wrapped_lines) for note in self._notes)

    def _content_height(self) -> int:
        lines = max(2, self._note_line_count())
        height = HEADER_HEIGHT + lines * LINE_HEIGHT + BOTTOM_PADDING
        if self._diagram:
            height += DIAGRAM_HEIGHT
        screen = QGuiApplication.primaryScreen()
        maximum = int(screen.availableGeometry().height() * 0.85) if screen else 900
        return min(height + 2 * SHADOW, maximum)

    def _opacity(self, now: float) -> float:
        if self._fade_at is None or now < self._fade_at:
            return 1.0
        return max(0.0, 1.0 - (now - self._fade_at) / self._active_fade_seconds)

    def _reset(self) -> None:
        self._notes = []
        self._diagram = None
        self._fade_at = None
        self._timer.stop()
        if self.isVisible():
            self.hide()
        self.resize(PAPER_WIDTH + 2 * SHADOW, self._content_height())

    def _tick(self) -> None:
        now = time.monotonic()
        if self._fade_at is not None and self._opacity(now) <= 0:
            self._reset()
            return
        typing = bool(self._notes) and now < self._notes[-1].ends_at(self._characters_per_second)
        drawing = self._diagram is not None and now < self._diagram.ends_at
        fading = self._fade_at is not None and now >= self._fade_at
        if typing or drawing or fading:
            self._timer.setInterval(FRAME_INTERVAL_MS)
            self.update()
        elif self._fade_at is not None:
            self._timer.setInterval(IDLE_CHECK_INTERVAL_MS)  # lingering: wait for the fade, no repaints
        else:
            self.update()  # final frame with everything fully drawn
            self._timer.stop()

    # ----- painting -----

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        now = time.monotonic()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setOpacity(self._opacity(now))
        paper = QRectF(SHADOW, SHADOW, self.width() - 2 * SHADOW, self.height() - 2 * SHADOW)

        for spread in range(SHADOW, 0, -3):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, int(10 * (1 - spread / SHADOW)) + 3))
            painter.drawRoundedRect(paper.adjusted(-spread / 2, -spread / 4, spread / 2, spread), 16, 16)
        painter.setBrush(PAPER_COLOR)
        painter.drawRoundedRect(paper, 14, 14)

        painter.save()
        painter.setClipRect(paper)
        painter.setPen(QPen(RULE_COLOR, 1))
        y = paper.top() + HEADER_HEIGHT + LINE_HEIGHT
        while y < paper.bottom() - 8:
            painter.drawLine(QPointF(paper.left() + 10, y), QPointF(paper.right() - 10, y))
            y += LINE_HEIGHT
        painter.setPen(QPen(MARGIN_COLOR, 1.4))
        margin_x = paper.left() + TEXT_LEFT - 12
        painter.drawLine(QPointF(margin_x, paper.top() + 8), QPointF(margin_x, paper.bottom() - 8))
        painter.restore()

        painter.setFont(self._header_font)
        painter.setPen(QColor(100, 116, 139))
        painter.drawText(
            QRectF(paper.left() + TEXT_LEFT, paper.top() + 12, 220, 24), Qt.AlignmentFlag.AlignVCenter, "clicky's notes"
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(NODE_BORDER)
        painter.drawEllipse(QPointF(paper.left() + TEXT_LEFT - 26, paper.top() + 24), 5, 5)

        self._paint_notes(painter, paper, now)
        if self._diagram is not None:
            self._paint_diagram(painter, paper, now)
        painter.end()

    def _paint_notes(self, painter: QPainter, paper: QRectF, now: float) -> None:
        painter.setFont(self._note_font)
        painter.setPen(INK_COLOR)
        line_index = 0
        for note in self._notes:
            remaining = typed_characters(now - note.starts_at, self._characters_per_second, len(note.text))
            for wrapped_index, wrapped_line in enumerate(note.wrapped_lines):
                baseline = paper.top() + HEADER_HEIGHT + (line_index + 1) * LINE_HEIGHT - 6
                if wrapped_index == 0 and remaining > 0:
                    painter.drawText(QPointF(paper.left() + TEXT_LEFT - 2, baseline), "•")
                visible = wrapped_line[: max(0, remaining)]
                remaining -= len(wrapped_line) + 1  # +1 for the space eaten by the wrap
                if visible:
                    painter.drawText(QPointF(paper.left() + TEXT_LEFT + 12, baseline), visible)
                line_index += 1

    def _paint_diagram(self, painter: QPainter, paper: QRectF, now: float) -> None:
        drawn = self._diagram
        assert drawn is not None
        top = paper.top() + HEADER_HEIGHT + max(2, self._note_line_count()) * LINE_HEIGHT + 10
        area = QRectF(paper.left() + 16, top, paper.width() - 32, min(DIAGRAM_HEIGHT - 20, paper.bottom() - top - 10))
        if area.height() < 40:
            return
        layout = layout_diagram(drawn.diagram, area.width(), area.height())
        elapsed = now - drawn.starts_at
        node_count = len(drawn.diagram.nodes)

        for edge_index, (source, target) in enumerate(drawn.diagram.edges):
            edge_progress = (
                elapsed - node_count * NODE_APPEAR_SECONDS - edge_index * EDGE_DRAW_SECONDS
            ) / EDGE_DRAW_SECONDS
            if edge_progress <= 0:
                continue
            progress = ease_in_out(min(1.0, edge_progress))
            painter.setPen(QPen(ARROW_COLOR, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            if (source, target) in layout.back_edges:
                self._paint_loop_back(
                    painter, layout.boxes[source], layout.boxes[target], area, layout.horizontal, progress
                )
                continue
            start, end = self._edge_endpoints(layout.boxes[source], layout.boxes[target], area, layout.horizontal)
            tip = QPointF(start.x() + (end.x() - start.x()) * progress, start.y() + (end.y() - start.y()) * progress)
            painter.drawLine(start, tip)
            if progress >= 1.0:
                self._paint_arrowhead(painter, start, end)

        painter.setFont(self._label_font)
        label_metrics = QFontMetricsF(self._label_font)
        for node_index, label in enumerate(drawn.diagram.nodes):
            appear = (elapsed - node_index * NODE_APPEAR_SECONDS) / NODE_APPEAR_SECONDS
            if appear <= 0:
                continue
            appear = ease_in_out(min(1.0, appear))
            x, y, width, height = layout.boxes[node_index]
            box = QRectF(area.left() + x, area.top() + y, width, height)
            scale = 0.85 + 0.15 * appear
            box = QRectF(
                box.center().x() - box.width() * scale / 2,
                box.center().y() - box.height() * scale / 2,
                box.width() * scale,
                box.height() * scale,
            )
            painter.save()
            painter.setOpacity(painter.opacity() * appear)
            path = QPainterPath()
            path.addRoundedRect(box, 9, 9)
            painter.setPen(QPen(NODE_BORDER, 1.6))
            painter.setBrush(NODE_FILL)
            painter.drawPath(path)
            painter.setPen(INK_COLOR)
            text = label_metrics.elidedText(label, Qt.TextElideMode.ElideRight, box.width() - 8)
            painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
            painter.restore()

    @staticmethod
    def _edge_endpoints(source_box, target_box, area: QRectF, horizontal: bool) -> tuple[QPointF, QPointF]:
        sx, sy, sw, sh = source_box
        tx, ty, tw, th = target_box
        source_center = QPointF(area.left() + sx + sw / 2, area.top() + sy + sh / 2)
        target_center = QPointF(area.left() + tx + tw / 2, area.top() + ty + th / 2)

        def boundary(center: QPointF, width: float, height: float, toward: QPointF) -> QPointF:
            dx, dy = toward.x() - center.x(), toward.y() - center.y()
            if dx == 0 and dy == 0:
                return center
            scale = min(
                (width / 2) / abs(dx) if dx else math.inf,
                (height / 2) / abs(dy) if dy else math.inf,
            )
            return QPointF(center.x() + dx * scale, center.y() + dy * scale)

        return boundary(source_center, sw, sh, target_center), boundary(target_center, tw, th, source_center)

    def _paint_loop_back(
        self, painter: QPainter, source_box, target_box, area: QRectF, horizontal: bool, progress: float
    ) -> None:
        """A loop-back arrow arcs over the top (or round the side) so it doesn't cross the forward arrows."""
        sx, sy, sw, sh = source_box
        tx, ty, tw, th = target_box
        if horizontal:
            start = QPointF(area.left() + sx + sw / 2, area.top() + sy)
            end = QPointF(area.left() + tx + tw / 2, area.top() + ty)
            lift = max(18.0, abs(start.x() - end.x()) * 0.25)
            control = QPointF((start.x() + end.x()) / 2, min(start.y(), end.y()) - lift)
        else:
            start = QPointF(area.left() + sx + sw, area.top() + sy + sh / 2)
            end = QPointF(area.left() + tx + tw, area.top() + ty + th / 2)
            lift = max(18.0, abs(start.y() - end.y()) * 0.25)
            control = QPointF(max(start.x(), end.x()) + lift, (start.y() + end.y()) / 2)
        steps = max(2, int(24 * progress))
        path = QPainterPath(start)
        last = start
        for step in range(1, steps + 1):
            t = progress * step / steps
            last = QPointF(
                (1 - t) ** 2 * start.x() + 2 * (1 - t) * t * control.x() + t * t * end.x(),
                (1 - t) ** 2 * start.y() + 2 * (1 - t) * t * control.y() + t * t * end.y(),
            )
            path.lineTo(last)
        painter.drawPath(path)
        if progress >= 1.0:
            # Arrowhead along the curve's final direction (from the control point into the target).
            self._paint_arrowhead(painter, control, end)

    @staticmethod
    def _paint_arrowhead(painter: QPainter, start: QPointF, end: QPointF) -> None:
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        size = 8.0
        left = QPointF(end.x() - size * math.cos(angle - 0.45), end.y() - size * math.sin(angle - 0.45))
        right = QPointF(end.x() - size * math.cos(angle + 0.45), end.y() - size * math.sin(angle + 0.45))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ARROW_COLOR)
        painter.drawPolygon(QPolygonF([end, left, right]))
