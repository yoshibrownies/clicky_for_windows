"""The buddy: a small blue triangle that trails your cursor, shows what it hears and says, and flies to point.

Implementation: one small frameless, translucent, click-through, always-on-top window that moves with the
buddy (cheaper than repainting full-screen overlays, and it crosses monitors with different scaling for
free). The window is excluded from screen capture so it never appears in the screenshots sent to Claude.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QCursor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
)
from PySide6.QtWidgets import QWidget

from clicky.animation import Flight
from clicky.fonts import ui_font

logger = logging.getLogger(__name__)

WINDOW_WIDTH = 440
WINDOW_HEIGHT = 300
EDGE_MARGIN = 26  # distance from the window edge to the triangle tip
FOLLOW_OFFSET = (16.0, 18.0)  # where the buddy sits relative to the system cursor
FOLLOW_SMOOTHING = 0.32
HOLD_AT_TARGET_SECONDS = 3.0
NOTICE_LINGER_SECONDS = 5.0
NOTICE_READING_CHARACTERS_PER_SECOND = 15.0  # long notices stay up long enough to read
NOTICE_MAX_LINGER_SECONDS = 30.0  # the bubble shows at most ~12 lines, so longer is just clutter
IDLE_FADE_DELAY_SECONDS = 1.0
FRAME_INTERVAL_MS = 16
HIDDEN_IDLE_INTERVAL_MS = 120
BUBBLE_MAX_TEXT_WIDTH = 300.0

BUDDY_BLUE = QColor(59, 130, 246)
BUDDY_BLUE_LIGHT = QColor(147, 197, 253)
BUBBLE_BACKGROUND = QColor(17, 24, 39, 236)
TRANSCRIPT_BACKGROUND = QColor(55, 65, 81, 210)
NOTICE_BORDER = QColor(251, 191, 36)
TEXT_COLOR = QColor(249, 250, 251)
WDA_EXCLUDEFROMCAPTURE = 0x00000011


@dataclass
class _Bubble:
    text: str
    kind: str  # "transcript" | "notice"
    expires_at: float | None  # None = while the current state lasts


BUDDY_CORNER_RADIUS = 3.0


def _rounded_triangle(corners: list[QPointF], radius: float) -> QPainterPath:
    """A closed path through the corners with each corner rounded off by `radius` pixels."""
    path = QPainterPath()
    count = len(corners)
    for index, corner in enumerate(corners):
        previous_corner = corners[index - 1]
        next_corner = corners[(index + 1) % count]

        def toward(target: QPointF, origin: QPointF = corner) -> QPointF:
            dx, dy = target.x() - origin.x(), target.y() - origin.y()
            length = math.hypot(dx, dy) or 1.0
            step = min(radius, length / 2) / length
            return QPointF(origin.x() + dx * step, origin.y() + dy * step)

        start, end = toward(previous_corner), toward(next_corner)
        if index == 0:
            path.moveTo(start)
        else:
            path.lineTo(start)
        path.quadTo(corner, end)
    path.closeSubpath()
    return path


def exclude_window_from_capture(window_handle: int) -> bool:
    """Ask Windows (10 2004+) to leave this window out of screenshots and screen recordings."""
    try:
        import ctypes

        set_display_affinity = ctypes.windll.user32.SetWindowDisplayAffinity
        set_display_affinity.argtypes = [ctypes.c_void_p, ctypes.c_uint]
        set_display_affinity.restype = ctypes.c_int
        return bool(set_display_affinity(ctypes.c_void_p(window_handle), WDA_EXCLUDEFROMCAPTURE))
    except (AttributeError, OSError):
        return False


class BuddyOverlay(QWidget):
    def __init__(self) -> None:
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
        self.setWindowTitle("Clicky buddy")
        self.resize(WINDOW_WIDTH, WINDOW_HEIGHT)

        self._bubble_font = ui_font(13)
        self._label_font = ui_font(11, QFont.Weight.DemiBold)
        self._capture_exclusion_applied = False

        self.companion_state = "idle"
        self.always_visible = True
        self._audio_level = 0.0
        self._bubble: _Bubble | None = None
        self._wrapped_bubble_cache: tuple[tuple[str, str], str] = (("", ""), "")

        cursor_position = QCursor.pos()
        self._buddy_position = (
            cursor_position.x() + FOLLOW_OFFSET[0],
            cursor_position.y() + FOLLOW_OFFSET[1],
        )
        self._mode = "follow"  # follow | flying | holding | returning
        self._flight: Flight | None = None
        self._hold_until = 0.0
        self._point_label = ""
        # While the lesson card writes, the buddy follows the pen instead of the mouse ("cursor follows thought").
        self._guide_target: tuple[float, float] | None = None
        self._idle_since = time.monotonic()
        self._opacity = 0.0
        self._flip_horizontal = False
        self._flip_vertical = False

        self._last_painted_signature: tuple | None = None

        # Coarse, not Precise: on Windows a precise sub-20 ms timer raises the system-wide timer resolution
        # (battery drain). While hidden and idle the timer also slows down; any public call wakes it.
        self._frame_timer = QTimer(self)
        self._frame_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._frame_timer.timeout.connect(self._tick)
        self._frame_timer.start(FRAME_INTERVAL_MS)

    def _wake(self) -> None:
        if self._frame_timer.interval() != FRAME_INTERVAL_MS:
            self._frame_timer.setInterval(FRAME_INTERVAL_MS)

    # ----- public API (GUI thread) -----

    def set_state(self, state: str) -> None:
        self._wake()
        previous_state, self.companion_state = self.companion_state, state
        now = time.monotonic()
        if state == "idle":
            self._idle_since = now
            self._audio_level = 0.0
            if self._bubble is not None and self._bubble.expires_at is None:
                self._bubble.expires_at = now
        elif state == "responding" and self._bubble is not None and self._bubble.kind == "transcript":
            self._bubble = None  # the answer is spoken and written on the card, not shown by the cursor
        elif state == "listening" and previous_state != "listening":
            self._bubble = None
            if self._mode in ("flying", "holding"):
                self._start_return_flight(now)

    def set_audio_level(self, level: float) -> None:
        # Fast attack, slow release, so the waveform feels alive but not jittery.
        if level > self._audio_level:
            self._audio_level = level
        else:
            self._audio_level = self._audio_level * 0.7 + level * 0.3

    def show_transcript(self, text: str) -> None:
        if text and self.companion_state in ("listening", "processing"):
            self._wake()
            self._bubble = _Bubble(text, "transcript", None)

    @property
    def has_bubble(self) -> bool:
        return self._bubble is not None

    def dismiss_bubble(self) -> None:
        """Clear-screen: drop the speech bubble and bring the buddy back to the cursor."""
        self._wake()
        self._bubble = None
        self._point_label = ""
        if self._mode in ("flying", "holding"):
            self._start_return_flight(time.monotonic())

    def show_notice(self, text: str) -> None:
        if text:
            self._wake()
            linger = min(
                NOTICE_MAX_LINGER_SECONDS, max(NOTICE_LINGER_SECONDS, len(text) / NOTICE_READING_CHARACTERS_PER_SECOND)
            )
            self._bubble = _Bubble(text, "notice", time.monotonic() + linger)

    def set_always_visible(self, always_visible: bool) -> None:
        self._wake()
        self.always_visible = always_visible

    def fly_to(self, global_x: int, global_y: int, label: str = "") -> None:
        self._wake()
        now = time.monotonic()
        self._flight = Flight(self._buddy_position, (float(global_x), float(global_y)), now)
        self._mode = "flying"
        self._point_label = label

    # ----- animation -----

    @property
    def is_guided(self) -> bool:
        return self._guide_target is not None

    def guide_to(self, global_x: int, global_y: int) -> None:
        """Follow this point (the card's pen) instead of the mouse. A POINT flight in progress takes priority."""
        self._wake()
        self._guide_target = (float(global_x), float(global_y))

    def release_guide(self) -> None:
        """Stop following the pen and glide back to the mouse."""
        if self._guide_target is None:
            return
        self._guide_target = None
        if self._mode == "follow":
            self._start_return_flight(time.monotonic())

    def _follow_target(self) -> tuple[float, float]:
        if self._guide_target is not None:
            # Sit just below-right of the pen so the triangle's tip points at the writing.
            return self._guide_target[0] + 6.0, self._guide_target[1] + 6.0
        cursor_position = QCursor.pos()
        return cursor_position.x() + FOLLOW_OFFSET[0], cursor_position.y() + FOLLOW_OFFSET[1]

    def _start_return_flight(self, now: float) -> None:
        self._flight = Flight(self._buddy_position, self._follow_target(), now)
        self._mode = "returning"
        self._point_label = ""

    def _is_wanted_visible(self, now: float) -> bool:
        if self._bubble is not None and (self._bubble.expires_at is None or now < self._bubble.expires_at):
            return True
        if self._mode != "follow" or self._guide_target is not None:
            return True
        if self.companion_state != "idle":
            return True
        return self.always_visible or now - self._idle_since < IDLE_FADE_DELAY_SECONDS

    def _tick(self) -> None:
        now = time.monotonic()

        if self._bubble is not None and self._bubble.expires_at is not None and now >= self._bubble.expires_at:
            self._bubble = None

        if self._mode == "follow":
            target_x, target_y = self._follow_target()
            current_x, current_y = self._buddy_position
            self._buddy_position = (
                current_x + (target_x - current_x) * FOLLOW_SMOOTHING,
                current_y + (target_y - current_y) * FOLLOW_SMOOTHING,
            )
        elif self._mode in ("flying", "returning") and self._flight is not None:
            self._buddy_position = self._flight.position_at(now)
            if self._flight.is_finished(now):
                if self._mode == "flying":
                    self._mode = "holding"
                    self._hold_until = now + HOLD_AT_TARGET_SECONDS
                else:
                    self._mode = "follow"
                self._flight = None
        elif self._mode == "holding" and now >= self._hold_until and self.companion_state != "responding":
            self._start_return_flight(now)

        target_opacity = 1.0 if self._is_wanted_visible(now) else 0.0
        self._opacity += (target_opacity - self._opacity) * 0.18
        if abs(target_opacity - self._opacity) < 0.02:
            self._opacity = target_opacity

        if self._opacity <= 0.0:
            if self.isVisible():
                self.hide()
            if target_opacity == 0.0 and self._frame_timer.interval() != HIDDEN_IDLE_INTERVAL_MS:
                self._frame_timer.setInterval(HIDDEN_IDLE_INTERVAL_MS)
            return
        if not self.isVisible():
            self.show()
            if not self._capture_exclusion_applied:
                self._capture_exclusion_applied = exclude_window_from_capture(int(self.winId()))
                if not self._capture_exclusion_applied:
                    logger.warning("Couldn't exclude the buddy from screen capture; it may appear in screenshots")

        self._position_window()
        # Moving a layered window keeps its pixels, so only repaint when what's drawn actually changes.
        is_animating = self.companion_state in ("listening", "processing") or self._mode in ("flying", "returning")
        bubble = self._bubble
        paint_signature = (
            round(self._opacity, 2),
            self.companion_state,
            self._mode,
            self._point_label,
            self._flip_horizontal,
            self._flip_vertical,
            (bubble.text, bubble.kind) if bubble is not None else None,
        )
        if is_animating or paint_signature != self._last_painted_signature:
            self._last_painted_signature = paint_signature
            self.update()

    def _position_window(self) -> None:
        buddy_x, buddy_y = self._buddy_position
        screen = (
            QGuiApplication.screenAt(QCursor.pos()) if self._mode == "follow" and self._guide_target is None else None
        )
        if screen is None:
            from PySide6.QtCore import QPoint

            screen = QGuiApplication.screenAt(QPoint(round(buddy_x), round(buddy_y)))
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        available = screen.availableGeometry() if screen is not None else None

        self._flip_horizontal = bool(available is not None and buddy_x + WINDOW_WIDTH - EDGE_MARGIN > available.right())
        self._flip_vertical = bool(available is not None and buddy_y + WINDOW_HEIGHT - EDGE_MARGIN > available.bottom())
        anchor_x, anchor_y = self._anchor_in_window()
        window_x = round(buddy_x - anchor_x)
        window_y = round(buddy_y - anchor_y)
        if self.x() != window_x or self.y() != window_y:
            self.move(window_x, window_y)

    def _anchor_in_window(self) -> tuple[float, float]:
        anchor_x = WINDOW_WIDTH - EDGE_MARGIN if self._flip_horizontal else EDGE_MARGIN
        anchor_y = WINDOW_HEIGHT - EDGE_MARGIN if self._flip_vertical else EDGE_MARGIN
        return anchor_x, anchor_y

    # ----- painting -----

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setOpacity(self._opacity)
        anchor_x, anchor_y = self._anchor_in_window()
        now = time.monotonic()

        self._paint_buddy(painter, anchor_x, anchor_y)
        if self.companion_state == "listening":
            self._paint_waveform(painter, anchor_x, anchor_y, now)
        elif self.companion_state == "processing":
            self._paint_spinner(painter, anchor_x, anchor_y, now)
        if self._point_label and self._mode in ("flying", "holding"):
            self._paint_label(painter, anchor_x, anchor_y)
        if self._bubble is not None:
            self._paint_bubble(painter, anchor_x, anchor_y, self._bubble)
        painter.end()

    def _paint_buddy(self, painter: QPainter, tip_x: float, tip_y: float) -> None:
        glow = QRadialGradient(QPointF(tip_x + 7, tip_y + 9), 22)
        glow_color = QColor(BUDDY_BLUE)
        glow_color.setAlpha(110 if self.companion_state != "idle" else 60)
        glow.setColorAt(0.0, glow_color)
        glow.setColorAt(1.0, QColor(59, 130, 246, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(tip_x + 7, tip_y + 9), 22, 22)

        triangle = _rounded_triangle(
            [QPointF(tip_x, tip_y), QPointF(tip_x + 5.5, tip_y + 19), QPointF(tip_x + 18, tip_y + 8.5)],
            BUDDY_CORNER_RADIUS,
        )
        painter.setPen(Qt.PenStyle.NoPen)
        # A soft shadow (two faint offset layers) instead of an outline, then the blue body.
        for offset, alpha in ((2.2, 22), (1.2, 38)):
            painter.setBrush(QColor(15, 23, 42, alpha))
            painter.drawPath(triangle.translated(offset * 0.4, offset))
        painter.setBrush(BUDDY_BLUE)
        painter.drawPath(triangle)

    def _side_origin(self, anchor_x: float, anchor_y: float, width: float, height: float) -> QPointF:
        """Top-left for a box placed beside the buddy, on whichever side has room."""
        box_x = anchor_x - 28 - width if self._flip_horizontal else anchor_x + 28
        box_y = anchor_y - 6 - height if self._flip_vertical else anchor_y + 14
        return QPointF(box_x, box_y)

    def _paint_waveform(self, painter: QPainter, anchor_x: float, anchor_y: float, now: float) -> None:
        bar_weights = (0.45, 0.75, 1.0, 0.75, 0.45)
        bar_width, bar_gap, max_bar_height = 3.5, 3.0, 20.0
        total_width = len(bar_weights) * (bar_width + bar_gap) - bar_gap
        origin = self._side_origin(anchor_x, anchor_y, total_width, max_bar_height)
        center_y = origin.y() + max_bar_height / 2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BUDDY_BLUE_LIGHT)
        for bar_index, weight in enumerate(bar_weights):
            wobble = 0.75 + 0.25 * math.sin(now * 9 + bar_index * 1.3)
            bar_height = 3.0 + (max_bar_height - 3.0) * self._audio_level * weight * wobble
            bar_x = origin.x() + bar_index * (bar_width + bar_gap)
            painter.drawRoundedRect(QRectF(bar_x, center_y - bar_height / 2, bar_width, bar_height), 1.75, 1.75)

    def _paint_spinner(self, painter: QPainter, anchor_x: float, anchor_y: float, now: float) -> None:
        radius = 8.0
        origin = self._side_origin(anchor_x, anchor_y, radius * 2, radius * 2)
        painter.setPen(QPen(BUDDY_BLUE_LIGHT, 2.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        start_angle = int(-(now * 360 * 1.4) % 360 * 16)
        painter.drawArc(QRectF(origin.x(), origin.y(), radius * 2, radius * 2), start_angle, 270 * 16)

    def _paint_label(self, painter: QPainter, anchor_x: float, anchor_y: float) -> None:
        metrics = QFontMetricsF(self._label_font)
        text_width = metrics.horizontalAdvance(self._point_label)
        pill = QRectF(0, 0, text_width + 14, metrics.height() + 6)
        origin = self._side_origin(anchor_x, anchor_y, pill.width(), pill.height())
        pill.moveTopLeft(origin)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(BUDDY_BLUE)
        painter.drawRoundedRect(pill, pill.height() / 2, pill.height() / 2)
        painter.setPen(TEXT_COLOR)
        painter.setFont(self._label_font)
        painter.drawText(pill, Qt.AlignmentFlag.AlignCenter, self._point_label)

    def _fit_bubble_text(self, text: str, max_height: float, keep: str = "end") -> str:
        """Shorten text that doesn't fit: keep="end" keeps the newest words (your live transcript), keep="start"
        keeps the beginning (a notice reads from its start). Cached per text."""
        if self._wrapped_bubble_cache[0] == (text, keep):
            return self._wrapped_bubble_cache[1]
        metrics = QFontMetricsF(self._bubble_font)
        flags = int(Qt.TextFlag.TextWordWrap)
        fitted_text = text
        words = text.split()
        dropped_word_count = 0
        while (
            metrics.boundingRect(QRectF(0, 0, BUBBLE_MAX_TEXT_WIDTH, 10_000), flags, fitted_text).height() > max_height
            and dropped_word_count < len(words) - 1
        ):
            dropped_word_count += max(1, len(words) // 20)
            if keep == "start":
                fitted_text = " ".join(words[: len(words) - dropped_word_count]) + " …"
            else:
                fitted_text = "… " + " ".join(words[dropped_word_count:])
        self._wrapped_bubble_cache = ((text, keep), fitted_text)
        return fitted_text

    def _paint_bubble(self, painter: QPainter, anchor_x: float, anchor_y: float, bubble: _Bubble) -> None:
        padding = 11.0
        max_text_height = WINDOW_HEIGHT - EDGE_MARGIN - 40 - padding * 2
        text = self._fit_bubble_text(bubble.text, max_text_height, keep="start" if bubble.kind == "notice" else "end")
        metrics = QFontMetricsF(self._bubble_font)
        flags = int(Qt.TextFlag.TextWordWrap)
        text_rect = metrics.boundingRect(QRectF(0, 0, BUBBLE_MAX_TEXT_WIDTH, 10_000), flags, text)
        bubble_width = min(BUBBLE_MAX_TEXT_WIDTH, text_rect.width()) + padding * 2
        bubble_height = text_rect.height() + padding * 2

        # Leave room for the waveform/spinner row above the bubble.
        vertical_offset = 30.0
        origin = self._side_origin(anchor_x, anchor_y, bubble_width, bubble_height)
        if self._flip_vertical:
            origin.setY(origin.y() - vertical_offset + 20)
        else:
            origin.setY(origin.y() + vertical_offset - 6)
        bubble_rect = QRectF(origin.x(), origin.y(), bubble_width, bubble_height)

        path = QPainterPath()
        path.addRoundedRect(bubble_rect, 13, 13)
        background = TRANSCRIPT_BACKGROUND if bubble.kind == "transcript" else BUBBLE_BACKGROUND
        border = QPen(NOTICE_BORDER, 1.4) if bubble.kind == "notice" else QPen(QColor(255, 255, 255, 30), 1.0)
        painter.setPen(border)
        painter.setBrush(background)
        painter.drawPath(path)

        font = QFont(self._bubble_font)
        font.setItalic(bubble.kind == "transcript")
        painter.setFont(font)
        painter.setPen(TEXT_COLOR)
        painter.drawText(bubble_rect.adjusted(padding, padding, -padding, -padding), flags, text)
