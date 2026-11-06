"""Follow-up chips: green pill buttons under the lesson card after an answer ("Explain terminal speed").

Like the lesson card it takes clicks but never keyboard focus (WA_ShowWithoutActivating +
WindowDoesNotAcceptFocus), so clicking a chip leaves your app focused. Clicking one emits `chosen(text)` and hides.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QCursor, QFont, QFontMetricsF, QGuiApplication, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from clicky.fonts import ui_font
from clicky.overlay import exclude_window_from_capture

MAX_CHIPS = 3
MAX_CHIP_TEXT = 40
CHIP_HEIGHT = 40
CHIP_GAP = 10
CHIP_PADDING_X = 18
ICON_SPACE = 24
SHADOW = 6

CHIP_FILL = QColor(208, 234, 216)
CHIP_FILL_HOVER = QColor(186, 224, 199)
CHIP_BORDER = QColor(47, 158, 103)
CHIP_TEXT = QColor(28, 61, 44)
CARD_GAP = 8


def chips_reserve(count: int = MAX_CHIPS) -> int:
    """Vertical room the chips need under the card (gap, chips and a small bottom margin)."""
    return CARD_GAP + 2 * SHADOW + count * CHIP_HEIGHT + (count - 1) * CHIP_GAP + 8


def _screen_for(rect: QRect):
    return QGuiApplication.screenAt(rect.center()) or QGuiApplication.primaryScreen()


class FollowUpChips(QWidget):
    chosen = Signal(str)
    appeared = Signal()  # shown (the buddy is raised above the chips)

    def __init__(self) -> None:
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
        self.setMouseTracking(True)
        self.setWindowTitle("Clicky follow-ups")
        self._font = ui_font(14, QFont.Weight.Medium)
        self._metrics = QFontMetricsF(self._font)
        self._options: list[str] = []
        self._chip_rects: list[QRectF] = []
        self._hovered = -1
        self._capture_exclusion_applied = False
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide_options)

    def options(self) -> list[str]:
        return list(self._options)

    def show_options(self, options: list[str], below: QRect, hide_after: float | None = None) -> None:
        """Lay the chips out under (or, near the screen bottom, inside the bottom of) the card's rectangle.

        `hide_after` (seconds) hides them on their own; used when there is no card whose fade would hide them.
        """
        self._hide_timer.stop()
        cleaned = [" ".join(option.split())[:MAX_CHIP_TEXT] for option in options if option and option.strip()]
        self._options = cleaned[:MAX_CHIPS]
        if not self._options:
            self.hide_options()
            return
        width = below.width()
        self._chip_rects = []
        y = SHADOW
        for option in self._options:
            chip_width = min(
                width - 2 * SHADOW, self._metrics.horizontalAdvance(option) + 2 * CHIP_PADDING_X + ICON_SPACE
            )
            self._chip_rects.append(QRectF(SHADOW + 12, y, chip_width, CHIP_HEIGHT))
            y += CHIP_HEIGHT + CHIP_GAP
        self.resize(QSize(width, int(y - CHIP_GAP + SHADOW)))
        screen = _screen_for(below)  # the screen the card is on, not wherever this window was last
        top = below.bottom() + CARD_GAP
        left = below.left()
        if screen is not None:
            available = screen.availableGeometry()
            if top + self.height() > available.bottom():
                top = below.bottom() - self.height() - 12  # overlap the card's bottom edge rather than fall off-screen
            top = max(available.top(), top)
            left = max(available.left(), min(left, available.right() - self.width()))
        self.move(left, top)
        self._hovered = -1
        self.show()
        if not self._capture_exclusion_applied:
            self._capture_exclusion_applied = exclude_window_from_capture(int(self.winId()))
        self.update()
        self.appeared.emit()
        if hide_after is not None:
            self._hide_timer.start(int(hide_after * 1000))

    def hide_options(self) -> None:
        self._hide_timer.stop()
        self._options = []
        self._chip_rects = []
        if self.isVisible():
            self.hide()

    def click_option(self, index: int) -> None:
        if 0 <= index < len(self._options):
            text = self._options[index]
            self.hide_options()
            self.chosen.emit(text)

    # ----- mouse -----

    def _index_at(self, point: QPointF) -> int:
        for index, rect in enumerate(self._chip_rects):
            if rect.contains(point):
                return index
        return -1

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        hovered = self._index_at(event.position())
        if hovered != self._hovered:
            self._hovered = hovered
            self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor if hovered >= 0 else Qt.CursorShape.ArrowCursor))
            self.update()

    def leaveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        self._hovered = -1
        self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if event.button() == Qt.MouseButton.LeftButton:
            self.click_option(self._index_at(event.position()))

    # ----- painting -----

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.setFont(self._font)
        for index, (rect, text) in enumerate(zip(self._chip_rects, self._options, strict=False)):
            path = QPainterPath()
            path.addRoundedRect(rect, CHIP_HEIGHT / 2, CHIP_HEIGHT / 2)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(0, 0, 0, 22))
            painter.drawPath(path.translated(0, 2))
            painter.setPen(QPen(CHIP_BORDER, 1.4))
            painter.setBrush(CHIP_FILL_HOVER if index == self._hovered else CHIP_FILL)
            painter.drawPath(path)
            # A small speech-bubble icon, then the question.
            icon_center = QPointF(rect.left() + CHIP_PADDING_X, rect.center().y())
            painter.setPen(QPen(CHIP_TEXT, 1.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(icon_center, 7, 6)
            painter.setPen(CHIP_TEXT)
            text_rect = QRectF(
                rect.left() + CHIP_PADDING_X + 14, rect.top(), rect.width() - CHIP_PADDING_X - 22, rect.height()
            )
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                self._metrics.elidedText(text, Qt.TextElideMode.ElideRight, text_rect.width()),
            )
        painter.end()
