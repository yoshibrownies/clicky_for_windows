"""The lesson card: one soft-green card where Clicky writes its explanation while it talks.

A title bar, then blocks in the order the model wrote them: a big heading, notes, formulas, a
boxes-and-arrows diagram and an inline animation. Text types out, diagrams pop in box by box, animations play.
`writing_point` reports where the "pen" is so the buddy cursor can follow it. Always on top, excluded from screen
capture; it lingers after the reply, then fades. The timer runs only while something moves.
You can drag it by its title bar, close it with the x, and scroll it with the mouse wheel; it never takes keyboard
focus, so the app you're working in keeps it.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

from PySide6.QtCore import QEasingCurve, QPoint, QPointF, QPropertyAnimation, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
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
from clicky.followup_chips import chips_reserve
from clicky.fonts import mono_font, ui_font
from clicky.handwriting import typed_characters, wrap_text
from clicky.overlay import exclude_window_from_capture
from clicky.scene import Scene
from clicky.scene_painter import HIGHLIGHT_SECONDS, ScenePainter

logger = logging.getLogger(__name__)

DEFAULT_TITLE = "clicky's notes"
DOCK_TOP_MARGIN = 56
CARD_WIDTH = 420
SHADOW = 12
TITLE_BAR_HEIGHT = 40
PADDING_X = 26
PADDING_TOP = 18
PADDING_BOTTOM = 22
BLOCK_GAP = 10
NOTE_INDENT = 18
EMPTY_CONTENT_HEIGHT = 60
DIAGRAM_BLOCK_HEIGHT = 190
ANIMATION_BLOCK_HEIGHT = 250
BLOCK_FADE_SECONDS = 0.25
ANIMATION_REVEAL_SECONDS = 0.6
NODE_APPEAR_SECONDS = 0.22
EDGE_DRAW_SECONDS = 0.3
DEFAULT_CHARACTERS_PER_SECOND = 45.0
DEFAULT_LINGER_SECONDS = 20.0
DEFAULT_FADE_SECONDS = 0.6
CLEAR_FADE_SECONDS = 0.2
FRAME_INTERVAL_MS = 16
IDLE_CHECK_INTERVAL_MS = 200
WRITING_POINT_INTERVAL_SECONDS = 1 / 30
CLOSE_BUTTON_SIZE = 24
WHEEL_PIXELS_PER_NOTCH = 40
GLIDE_MS = 260
DOCK_MARGIN = 16

PAPER_COLOR = QColor(238, 243, 238)
TITLE_BAR_COLOR = QColor(213, 224, 214)
TITLE_TEXT_COLOR = QColor(98, 112, 104)
INK_COLOR = QColor(31, 41, 51)
SOFT_INK_COLOR = QColor(84, 97, 92)
GREEN = QColor(47, 158, 103)
NODE_FILL = QColor(222, 239, 228)
ARROW_COLOR = QColor(84, 97, 92)
ANIMATION_PANEL = QColor(255, 255, 255, 130)

# kind -> (font pixel size, weight, line height, typing speed factor). Inter for words, Geist Mono for formulas.
TEXT_STYLES = {
    "heading": (24, QFont.Weight.DemiBold, 34, 0.8),
    "note": (16, QFont.Weight.Normal, 26, 1.0),
    "formula": (19, QFont.Weight.Medium, 32, 0.7),
}


@dataclass
class _Block:
    kind: str
    text: str
    starts_at: float
    reveal_seconds: float
    height: float
    lines: list[str]
    diagram: Diagram | None = None
    scene: Scene | None = None

    def progress(self, now: float) -> float:
        if self.reveal_seconds <= 0:
            return 1.0 if now >= self.starts_at else 0.0
        return max(0.0, min(1.0, (now - self.starts_at) / self.reveal_seconds))

    def is_moving(self, now: float) -> bool:
        if now < self.starts_at:
            return True  # queued: still to be written
        if self.progress(now) < 1.0:
            return True
        return self.scene is not None and now < self.starts_at + self.scene.duration


class LessonCard(QWidget):
    writing_point = Signal(object)  # QPoint, global: where the pen is right now
    faded = Signal()  # the card went away (faded out or cleared)
    appeared = Signal()  # a new card just came up (the buddy is raised above it)
    moved = Signal()  # the card's window moved (dragged, or glided out of a mark's way)
    closed = Signal()  # closed with the x: stays away for the rest of this reply

    def __init__(
        self,
        linger_seconds: float = DEFAULT_LINGER_SECONDS,
        fade_seconds: float = DEFAULT_FADE_SECONDS,
        characters_per_second: float = DEFAULT_CHARACTERS_PER_SECOND,
        max_height: int | None = None,
    ) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMouseTracking(True)
        self._user_position: QPoint | None = None  # where Yoshi last dropped the card (this session only)
        self._drag_offset: QPoint | None = None
        self._user_scroll = 0.0  # pixels scrolled back up with the wheel; 0 = follow the newest line
        self._close_hovered = False
        self._marks: list[tuple[QRect, float]] = []  # screen marks to keep clear of: (global rect, expires at)
        self._glide = QPropertyAnimation(self, b"pos", self)
        self._glide.setDuration(GLIDE_MS)
        self._glide.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.setWindowTitle("Clicky's lesson card")
        self._linger_seconds = linger_seconds
        self._fade_seconds = fade_seconds
        self._characters_per_second = characters_per_second
        self._max_height_override = max_height
        self._enabled = True
        self._dismissed = False  # closed with the x during this reply
        self._title = DEFAULT_TITLE
        self._blocks: list[_Block] = []
        self._fade_at: float | None = None
        self._active_fade_seconds = fade_seconds
        self._capture_exclusion_applied = False
        self._last_writing_emit = 0.0
        self._last_writing_point: tuple[int, int] | None = None
        self._fonts = {kind: self._make_font(kind, size, weight) for kind, (size, weight, _, _) in TEXT_STYLES.items()}
        self._metrics = {kind: QFontMetricsF(font) for kind, font in self._fonts.items()}
        self._title_font = ui_font(14, QFont.Weight.DemiBold)
        self._label_font = ui_font(13, QFont.Weight.Medium)
        self._scene_painter = ScenePainter()
        # (label, start time, animation block): a ring around a named object in that animation, following it.
        self._highlight: tuple[str, float, _Block] | None = None
        self.resize(CARD_WIDTH + 2 * SHADOW, self._content_height())
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._timer.setInterval(FRAME_INTERVAL_MS)
        self._timer.timeout.connect(self._tick)

    @staticmethod
    def _make_font(kind: str, pixel_size: int, weight: QFont.Weight) -> QFont:
        return mono_font(pixel_size, weight) if kind == "formula" else ui_font(pixel_size, weight)

    # ----- public API (GUI thread) -----

    @property
    def title(self) -> str:
        return self._title

    @property
    def is_animating(self) -> bool:
        return self._timer.isActive() and self._timer.interval() == FRAME_INTERVAL_MS

    def content_blocks(self) -> list[tuple[str, str]]:
        return [(block.kind, block.text) for block in self._blocks]

    def revealed_fraction(self) -> float:
        if not self._blocks:
            return 1.0
        now = time.monotonic()
        return sum(block.progress(now) for block in self._blocks) / len(self._blocks)

    @property
    def _accepting(self) -> bool:
        return self._enabled and not self._dismissed

    def start_reply(self) -> None:
        """A new question: a card closed with the x during the last answer may come back."""
        self._dismissed = False

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled
        if not enabled:
            self.clear()

    def set_title(self, text: str) -> None:
        if self._accepting and text.strip():
            self._title = " ".join(text.split())
            self.update()

    def add_heading(self, text: str) -> None:
        self._add_text_block("heading", text)

    def add_note(self, text: str) -> None:
        self._add_text_block("note", text)

    def add_formula(self, text: str) -> None:
        self._add_text_block("formula", text)

    def set_diagram(self, spec: str) -> None:
        if not self._accepting:
            return
        diagram = parse_diagram(spec)
        if not diagram.nodes:
            return
        reveal = len(diagram.nodes) * NODE_APPEAR_SECONDS + len(diagram.edges) * EDGE_DRAW_SECONDS
        self._append(_Block("diagram", spec, self._next_start(), reveal, DIAGRAM_BLOCK_HEIGHT, [], diagram=diagram))

    def play_animation(self, scene: Scene | None) -> None:
        if not self._accepting or scene is None:
            return
        self._append(
            _Block(
                "animation",
                scene.title,
                self._next_start(),
                ANIMATION_REVEAL_SECONDS,
                ANIMATION_BLOCK_HEIGHT,
                [],
                scene=scene,
            )
        )

    def avoid(self, rect: QRect, seconds: float | None = None) -> None:
        """A mark was drawn on screen at `rect` (global). Keep the card off it so you can see what Clicky means.

        Kept until `forget_marks()` (the marks were cleared or faded), or for `seconds` if given.
        """
        expires = math.inf if seconds is None else time.monotonic() + seconds
        self._marks.append((QRect(rect), expires))
        self._dodge_marks()

    def forget_marks(self) -> None:
        self._marks = []

    def _hold_fade(self) -> None:
        """You're using the card (scrolling, dragging, pointing at it): don't fade it away under you."""
        if self._fade_at is None or self._active_fade_seconds == CLEAR_FADE_SECONDS:
            return
        self._fade_at = max(self._fade_at, time.monotonic() + self._linger_seconds)

    def _live_marks(self) -> list[QRect]:
        now = time.monotonic()
        self._marks = [(rect, expires) for rect, expires in self._marks if expires > now]
        return [rect for rect, _ in self._marks]

    def _overlap_with_marks(self, top_left: QPoint, marks: list[QRect]) -> int:
        spot = QRect(top_left, self.size())
        total = 0
        for mark in marks:
            shared = spot.intersected(mark)
            if not shared.isEmpty():
                total += max(1, shared.width() * shared.height())
        return total

    def _dock_spots(self, screen) -> list[QPoint]:
        """Where a card can dock on this screen: top right (usual), then top left."""
        available = screen.availableGeometry()
        top = available.top() + DOCK_TOP_MARGIN
        return [
            QPoint(available.right() - self.width() - DOCK_MARGIN, top),
            QPoint(available.left() + DOCK_MARGIN, top),
        ]

    def _clear_spot(self, preferred: QPoint, screen) -> QPoint:
        """`preferred` if no live mark is under it, else the dock spot with the least mark under it."""
        marks = self._live_marks()
        if not marks or self._overlap_with_marks(preferred, marks) == 0:
            return preferred
        spots = self._dock_spots(screen)
        return min(spots, key=lambda spot: (self._overlap_with_marks(spot, marks), spot != preferred))

    def _dodge_marks(self) -> None:
        """If the visible card covers a live mark, glide to a spot that doesn't."""
        if not self.isVisible() or not self._blocks or self._drag_offset is not None:
            return  # never yank the card out from under your mouse
        marks = self._live_marks()
        here = self._glide.endValue() if self._glide.state() == QPropertyAnimation.State.Running else self.pos()
        if not marks or self._overlap_with_marks(here, marks) == 0:
            return
        screen = QGuiApplication.screenAt(QRect(here, self.size()).center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        target = self._clear_spot(here, screen)
        if target == here:
            return
        self._glide.stop()
        self._glide.setStartValue(self.pos())
        self._glide.setEndValue(target)
        self._glide.start()

    @property
    def highlighted_label(self) -> str | None:
        return self._highlight[0] if self._highlight is not None else None

    def highlight(self, label: str) -> None:
        """Ring the object called `label` in the newest animation, following it as it moves, for a few seconds."""
        label = " ".join(label.split())
        animation = next((block for block in reversed(self._blocks) if block.kind == "animation"), None)
        if not self._accepting or not label or animation is None:
            return
        self._highlight = (label, max(time.monotonic(), animation.starts_at), animation)
        self._timer.start(FRAME_INTERVAL_MS)

    def _highlight_active(self, now: float) -> bool:
        return self._highlight is not None and now < self._highlight[1] + HIGHLIGHT_SECONDS

    def finish(self) -> None:
        """The reply ended: keep the card up a while (after anything still playing), then fade."""
        if not self._blocks:
            return
        last_motion = max(
            block.starts_at + max(block.reveal_seconds, block.scene.duration if block.scene else 0.0)
            for block in self._blocks
        )
        self._fade_at = max(time.monotonic(), last_motion) + self._linger_seconds
        self._active_fade_seconds = self._fade_seconds
        self._timer.start(FRAME_INTERVAL_MS)

    def clear(self) -> None:
        if self._blocks and self.isVisible():
            self._fade_at = time.monotonic()
            self._active_fade_seconds = CLEAR_FADE_SECONDS
            self._timer.start(FRAME_INTERVAL_MS)
        else:
            self._reset()

    def scroll_offset(self, now: float | None = None) -> float:
        """How far the content is scrolled up. Only blocks that have started count, so the newest written line
        stays at the bottom of the card and queued (unwritten) blocks never push it off the top."""
        now = time.monotonic() if now is None else now
        started = [block for block in self._blocks if block.starts_at <= now]
        if not started:
            return 0.0
        written = sum(block.height for block in started) + BLOCK_GAP * (len(started) - 1)
        inner_visible = self.height() - 2 * SHADOW - TITLE_BAR_HEIGHT - PADDING_TOP - PADDING_BOTTOM
        bottom = max(0.0, written - inner_visible)
        return max(0.0, bottom - self._user_scroll)

    def close_button_rect(self) -> QRectF:
        paper = self._paper_rect()
        return QRectF(
            paper.right() - CLOSE_BUTTON_SIZE - 10,
            paper.top() + (TITLE_BAR_HEIGHT - CLOSE_BUTTON_SIZE) / 2,
            CLOSE_BUTTON_SIZE,
            CLOSE_BUTTON_SIZE,
        )

    def _title_bar_rect(self) -> QRectF:
        paper = self._paper_rect()
        return QRectF(paper.left(), paper.top(), paper.width(), TITLE_BAR_HEIGHT)

    # ----- building -----

    def _add_text_block(self, kind: str, text: str) -> None:
        text = " ".join(text.split())
        if not self._accepting or not text:
            return
        _, _, line_height, speed = TEXT_STYLES[kind]
        indent = NOTE_INDENT if kind == "note" else 0
        width = CARD_WIDTH - 2 * PADDING_X - indent
        lines = wrap_text(text, self._metrics[kind].horizontalAdvance, width) or [text]
        reveal = len(text) / (self._characters_per_second * speed)
        self._append(_Block(kind, text, self._next_start(), reveal, len(lines) * line_height + 4, lines))

    def _next_start(self) -> float:
        now = time.monotonic()
        if not self._blocks:
            return now
        last = self._blocks[-1]
        return max(now, last.starts_at + last.reveal_seconds)

    def _append(self, block: _Block) -> None:
        if self._fade_at is not None and self._fade_at <= time.monotonic():
            self._reset()  # a fade was already running: start a fresh card rather than resurrect the old one
            block.starts_at = time.monotonic()
        self._blocks.append(block)
        self._fade_at = None
        self._user_scroll = 0.0
        was_visible = self.isVisible()
        if not was_visible:
            self._dock()
        height = self._content_height()
        if height > self.height():
            self.resize(self.width(), height)
            self._keep_bottom_on_screen()
            self._dodge_marks()  # a taller card may now cover a mark
        if not was_visible:
            self.show()
            if not self._capture_exclusion_applied:
                self._capture_exclusion_applied = exclude_window_from_capture(int(self.winId()))
            self.appeared.emit()
        self._timer.start(FRAME_INTERVAL_MS)
        self.update()

    def _dock(self) -> None:
        self._glide.stop()
        if self._user_position is not None:
            spot = QRect(self._user_position, self.size())
            screen = QGuiApplication.screenAt(spot.center())
            if screen is not None:
                available = screen.availableGeometry()
                x = max(available.left(), min(spot.left(), available.right() - self.width()))
                y = max(available.top(), min(spot.top(), available.bottom() - 120))
                self.move(self._clear_spot(QPoint(x, y), screen))
                return
            self._user_position = None  # that screen is gone: dock normally
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        self.move(self._clear_spot(self._dock_spots(screen)[0], screen))

    def _keep_bottom_on_screen(self) -> None:
        """A card dragged low slides up as it grows, so the newest line (written at the bottom) stays visible."""
        screen = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        lowest_top = available.bottom() - chips_reserve() - self.height()
        if self.y() > lowest_top:
            self._glide.stop()
            self.move(self.x(), max(available.top(), lowest_top))

    def _blocks_height(self) -> float:
        if not self._blocks:
            return EMPTY_CONTENT_HEIGHT
        return sum(block.height for block in self._blocks) + BLOCK_GAP * (len(self._blocks) - 1)

    def _height_cap(self) -> int:
        if self._max_height_override is not None:
            return self._max_height_override
        screen = QGuiApplication.screenAt(self.geometry().center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return 900
        available_height = screen.availableGeometry().height()
        # Leave room under the card for the follow-up chips, so they never cover the newest notes.
        return int(min(available_height * 0.88, available_height - DOCK_TOP_MARGIN - chips_reserve()))

    def _content_height(self) -> int:
        height = 2 * SHADOW + TITLE_BAR_HEIGHT + PADDING_TOP + self._blocks_height() + PADDING_BOTTOM
        return int(min(self._height_cap(), height))

    # ----- animation loop -----

    def _opacity(self, now: float) -> float:
        if self._fade_at is None or now < self._fade_at:
            return 1.0
        return max(0.0, 1.0 - (now - self._fade_at) / self._active_fade_seconds)

    def _reset(self) -> None:
        had_content = bool(self._blocks)
        self._blocks = []
        self._user_scroll = 0.0
        self._drag_offset = None
        self._glide.stop()
        self.unsetCursor()
        self._highlight = None
        self._title = DEFAULT_TITLE
        self._fade_at = None
        self._last_writing_point = None
        self._timer.stop()
        if self.isVisible():
            self.hide()
        self.resize(CARD_WIDTH + 2 * SHADOW, self._content_height())
        if had_content:
            self.faded.emit()

    def _tick(self) -> None:
        now = time.monotonic()
        if self._fade_at is not None and self._opacity(now) <= 0:
            self._reset()
            return
        moving = any(block.is_moving(now) for block in self._blocks) or self._highlight_active(now)
        fading = self._fade_at is not None and now >= self._fade_at
        if moving or fading:
            self._timer.setInterval(FRAME_INTERVAL_MS)
            self.update()
            if moving and not fading:
                self._emit_writing_point(now)
        elif self._fade_at is not None:
            self._timer.setInterval(IDLE_CHECK_INTERVAL_MS)
        else:
            self.update()
            self._timer.stop()

    def _emit_writing_point(self, now: float) -> None:
        if now - self._last_writing_emit < WRITING_POINT_INTERVAL_SECONDS:
            return
        local = self._pen_position(now)
        if local is None:
            return
        global_point = self.mapToGlobal(local.toPoint())
        key = (global_point.x(), global_point.y())
        if key != self._last_writing_point:
            self._last_writing_point = key
            self._last_writing_emit = now
            self.writing_point.emit(global_point)

    # ----- geometry shared by painting and the pen -----

    def _paper_rect(self) -> QRectF:
        return QRectF(SHADOW, SHADOW, self.width() - 2 * SHADOW, self.height() - 2 * SHADOW)

    def _block_tops(self, now: float | None = None) -> list[float]:
        paper = self._paper_rect()
        y = paper.top() + TITLE_BAR_HEIGHT + PADDING_TOP - self.scroll_offset(now)
        tops = []
        for block in self._blocks:
            tops.append(y)
            y += block.height + BLOCK_GAP
        return tops

    def _text_left(self, block: _Block) -> float:
        return self._paper_rect().left() + PADDING_X + (NOTE_INDENT if block.kind == "note" else 0)

    def _typed_count(self, block: _Block, now: float) -> int:
        speed = TEXT_STYLES[block.kind][3]
        return typed_characters(now - block.starts_at, self._characters_per_second * speed, len(block.text))

    def _pen_position(self, now: float) -> QPointF | None:
        """Where the pen is: the newest text or diagram still being written, otherwise a playing animation."""
        started = [
            (block, top)
            for block, top in zip(self._blocks, self._block_tops(now), strict=False)
            if block.starts_at <= now and block.is_moving(now)
        ]
        if self._highlight_active(now) and self._scene_painter.highlight_rect is not None:
            return self._scene_painter.highlight_rect.center()  # a ringed object beats the writing
        for block, top in reversed(started):
            if block.progress(now) >= 1.0:
                continue
            if block.kind in TEXT_STYLES:
                return self._text_pen(block, top, now)
            if block.kind == "diagram" and block.diagram is not None:
                area = self._diagram_area(top)
                layout = layout_diagram(block.diagram, area.width(), area.height())
                shown = min(len(block.diagram.nodes) - 1, int((now - block.starts_at) / NODE_APPEAR_SECONDS))
                x, y, width, height = layout.boxes[max(0, shown)]
                return QPointF(area.left() + x + width / 2, area.top() + y + height)
        for block, top in reversed(started):
            if block.kind == "animation":
                # The scene's busiest object when it has one (circles, plots), otherwise the panel's middle.
                return self._scene_painter.focus_point or self._animation_area(top).center()
        return None

    def _text_pen(self, block: _Block, top: float, now: float) -> QPointF:
        line_height = TEXT_STYLES[block.kind][2]
        remaining = self._typed_count(block, now)
        metrics = self._metrics[block.kind]
        for index, line in enumerate(block.lines):
            visible = line[: max(0, remaining)]
            if remaining <= len(line) or index == len(block.lines) - 1:
                x = self._text_left(block) + metrics.horizontalAdvance(visible)
                return QPointF(x + 4, top + (index + 1) * line_height - 8)
            remaining -= len(line) + 1
        return QPointF(self._text_left(block), top)

    def _diagram_area(self, top: float) -> QRectF:
        paper = self._paper_rect()
        return QRectF(
            paper.left() + PADDING_X - 8, top + 6, paper.width() - 2 * PADDING_X + 16, DIAGRAM_BLOCK_HEIGHT - 16
        )

    def _animation_area(self, top: float) -> QRectF:
        paper = self._paper_rect()
        return QRectF(paper.left() + PADDING_X - 10, top, paper.width() - 2 * PADDING_X + 20, ANIMATION_BLOCK_HEIGHT)

    # ----- mouse: drag by the title bar, x to close, wheel to scroll -----

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        position = event.position()
        if self.close_button_rect().contains(position):
            return  # handled on release, so a press that slides off doesn't close
        if self._title_bar_rect().contains(position):
            self._glide.stop()  # your drag wins over a glide out of a mark's way
            self._hold_fade()
            self._drag_offset = event.globalPosition().toPoint() - self.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        position = event.position()
        self._hold_fade()
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            return
        hovered = self.close_button_rect().contains(position)
        if hovered != self._close_hovered:
            self._close_hovered = hovered
            self.update()
        if hovered:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._title_bar_rect().contains(position):
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.unsetCursor()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._drag_offset is not None:
            self._drag_offset = None
            self._user_position = self.pos()
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        if self.close_button_rect().contains(event.position()):
            self._dismissed = True  # gone for the rest of this answer
            self.clear()
            self.closed.emit()

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if self._close_hovered:
            self._close_hovered = False
            self.update()

    def wheelEvent(self, event) -> None:  # noqa: N802 (Qt override)
        notches = event.angleDelta().y() / 120
        if not notches or not self._blocks:
            return
        self._hold_fade()
        now = time.monotonic()
        previous_scroll = self._user_scroll
        self._user_scroll = 0.0
        bottom = self.scroll_offset(now)  # how far down the newest line is
        self._user_scroll = max(0.0, min(bottom, previous_scroll + notches * WHEEL_PIXELS_PER_NOTCH))
        self.update()
        event.accept()

    def moveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().moveEvent(event)
        self.moved.emit()

    # ----- painting -----

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        now = time.monotonic()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setOpacity(self._opacity(now))
        paper = self._paper_rect()
        for spread in range(SHADOW, 0, -3):
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, int(10 * (1 - spread / SHADOW)) + 3))
            painter.drawRoundedRect(paper.adjusted(-spread / 2, -spread / 4, spread / 2, spread), 18, 18)
        card_shape = QPainterPath()
        card_shape.addRoundedRect(paper, 16, 16)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(PAPER_COLOR)
        painter.drawPath(card_shape)

        painter.save()
        painter.setClipPath(card_shape)
        painter.fillRect(QRectF(paper.left(), paper.top(), paper.width(), TITLE_BAR_HEIGHT), TITLE_BAR_COLOR)
        painter.restore()
        painter.setFont(self._title_font)
        painter.setPen(TITLE_TEXT_COLOR)
        painter.drawText(
            QRectF(paper.left() + 16, paper.top(), paper.width() - 32, TITLE_BAR_HEIGHT),
            Qt.AlignmentFlag.AlignCenter,
            self._title,
        )
        self._paint_close_button(painter)

        painter.save()
        painter.setClipRect(
            QRectF(paper.left(), paper.top() + TITLE_BAR_HEIGHT, paper.width(), paper.height() - TITLE_BAR_HEIGHT)
        )
        for block, top in zip(self._blocks, self._block_tops(now), strict=False):
            if now < block.starts_at or top > paper.bottom() or top + block.height < paper.top():
                continue
            try:
                if block.kind in TEXT_STYLES:
                    self._paint_text(painter, block, top, now)
                elif block.kind == "diagram":
                    self._paint_diagram(painter, block, top, now)
                elif block.kind == "animation":
                    self._paint_animation(painter, block, top, now)
            except Exception:  # one bad block must never take the card (or the app) down
                logger.exception("Painting a %s block failed", block.kind)
        painter.restore()
        painter.end()

    def _paint_close_button(self, painter: QPainter) -> None:
        button = self.close_button_rect()
        painter.save()
        if self._close_hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 22))
            painter.drawEllipse(button)
        painter.setPen(QPen(TITLE_TEXT_COLOR, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        inset = button.width() * 0.32
        cross = button.adjusted(inset, inset, -inset, -inset)
        painter.drawLine(cross.topLeft(), cross.bottomRight())
        painter.drawLine(cross.topRight(), cross.bottomLeft())
        painter.restore()

    def _paint_text(self, painter: QPainter, block: _Block, top: float, now: float) -> None:
        _, _, line_height, _ = TEXT_STYLES[block.kind]
        painter.setFont(self._fonts[block.kind])
        painter.setPen(SOFT_INK_COLOR if block.kind == "note" else INK_COLOR)
        remaining = self._typed_count(block, now)
        left = self._text_left(block)
        if block.kind == "note" and remaining > 0:
            painter.save()
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(GREEN)
            painter.drawEllipse(QPointF(left - 10, top + line_height - 14), 3.2, 3.2)
            painter.restore()
        for index, line in enumerate(block.lines):
            visible = line[: max(0, remaining)]
            remaining -= len(line) + 1
            if visible:
                painter.drawText(QPointF(left, top + (index + 1) * line_height - 8), visible)

    def _paint_diagram(self, painter: QPainter, block: _Block, top: float, now: float) -> None:
        diagram = block.diagram
        assert diagram is not None
        area = self._diagram_area(top)
        layout = layout_diagram(diagram, area.width(), area.height())
        elapsed = now - block.starts_at
        node_count = len(diagram.nodes)
        for edge_index, (source, target) in enumerate(diagram.edges):
            edge_progress = (elapsed - node_count * NODE_APPEAR_SECONDS - edge_index * EDGE_DRAW_SECONDS) / (
                EDGE_DRAW_SECONDS
            )
            if edge_progress <= 0:
                continue
            progress = ease_in_out(min(1.0, edge_progress))
            painter.setPen(QPen(ARROW_COLOR, 1.8, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            start, end, control = self._edge_geometry(layout, source, target, area)
            if control is None:
                tip = QPointF(
                    start.x() + (end.x() - start.x()) * progress, start.y() + (end.y() - start.y()) * progress
                )
                painter.drawLine(start, tip)
                if progress >= 1.0:
                    self._paint_arrowhead(painter, start, end)
            else:
                path = QPainterPath(start)
                steps = max(2, int(24 * progress))
                for step in range(1, steps + 1):
                    u = progress * step / steps
                    path.lineTo(
                        QPointF(
                            (1 - u) ** 2 * start.x() + 2 * (1 - u) * u * control.x() + u * u * end.x(),
                            (1 - u) ** 2 * start.y() + 2 * (1 - u) * u * control.y() + u * u * end.y(),
                        )
                    )
                painter.drawPath(path)
                if progress >= 1.0:
                    self._paint_arrowhead(painter, control, end)
        painter.setFont(self._label_font)
        label_metrics = QFontMetricsF(self._label_font)
        for node_index, label in enumerate(diagram.nodes):
            appear = (elapsed - node_index * NODE_APPEAR_SECONDS) / NODE_APPEAR_SECONDS
            if appear <= 0:
                continue
            appear = ease_in_out(min(1.0, appear))
            x, y, width, height = layout.boxes[node_index]
            scale = 0.85 + 0.15 * appear
            box = QRectF(
                area.left() + x + width * (1 - scale) / 2,
                area.top() + y + height * (1 - scale) / 2,
                width * scale,
                height * scale,
            )
            painter.save()
            painter.setOpacity(painter.opacity() * appear)
            path = QPainterPath()
            path.addRoundedRect(box, 10, 10)
            painter.setPen(QPen(GREEN, 1.6))
            painter.setBrush(NODE_FILL)
            painter.drawPath(path)
            painter.setPen(INK_COLOR)
            painter.drawText(
                box,
                Qt.AlignmentFlag.AlignCenter,
                label_metrics.elidedText(label, Qt.TextElideMode.ElideRight, box.width() - 8),
            )
            painter.restore()

    @staticmethod
    def _edge_geometry(layout, source: int, target: int, area: QRectF):
        """(start, end, control or None): straight edges between box borders; loop-backs as a curve."""
        sx, sy, sw, sh = layout.boxes[source]
        tx, ty, tw, th = layout.boxes[target]
        if (source, target) in layout.back_edges:
            if layout.horizontal:
                start = QPointF(area.left() + sx + sw / 2, area.top() + sy)
                end = QPointF(area.left() + tx + tw / 2, area.top() + ty)
                lift = max(18.0, abs(start.x() - end.x()) * 0.25)
                return start, end, QPointF((start.x() + end.x()) / 2, min(start.y(), end.y()) - lift)
            start = QPointF(area.left() + sx + sw, area.top() + sy + sh / 2)
            end = QPointF(area.left() + tx + tw, area.top() + ty + th / 2)
            lift = max(18.0, abs(start.y() - end.y()) * 0.25)
            return start, end, QPointF(max(start.x(), end.x()) + lift, (start.y() + end.y()) / 2)
        source_center = QPointF(area.left() + sx + sw / 2, area.top() + sy + sh / 2)
        target_center = QPointF(area.left() + tx + tw / 2, area.top() + ty + th / 2)

        def boundary(center: QPointF, width: float, height: float, toward: QPointF) -> QPointF:
            dx, dy = toward.x() - center.x(), toward.y() - center.y()
            if dx == 0 and dy == 0:
                return center
            scale = min((width / 2) / abs(dx) if dx else math.inf, (height / 2) / abs(dy) if dy else math.inf)
            return QPointF(center.x() + dx * scale, center.y() + dy * scale)

        return boundary(source_center, sw, sh, target_center), boundary(target_center, tw, th, source_center), None

    @staticmethod
    def _paint_arrowhead(painter: QPainter, start: QPointF, end: QPointF) -> None:
        angle = math.atan2(end.y() - start.y(), end.x() - start.x())
        size = 8.0
        left = QPointF(end.x() - size * math.cos(angle - 0.45), end.y() - size * math.sin(angle - 0.45))
        right = QPointF(end.x() - size * math.cos(angle + 0.45), end.y() - size * math.sin(angle + 0.45))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ARROW_COLOR)
        painter.drawPolygon(QPolygonF([end, left, right]))

    def _paint_animation(self, painter: QPainter, block: _Block, top: float, now: float) -> None:
        scene = block.scene
        assert scene is not None
        area = self._animation_area(top)
        appear = min(1.0, (now - block.starts_at) / BLOCK_FADE_SECONDS)
        painter.save()
        painter.setOpacity(painter.opacity() * appear)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(ANIMATION_PANEL)
        painter.drawRoundedRect(area, 12, 12)
        scene_time = max(0.0, min(scene.duration, now - block.starts_at))
        highlight = None
        if self._highlight is not None and self._highlight[2] is block:
            highlight = (self._highlight[0], now - self._highlight[1])
        self._scene_painter.paint(painter, area, scene, scene_time, highlight=highlight)
        painter.restore()
