import time

from PySide6.QtCore import QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from clicky.lesson_card import SHADOW, TITLE_BAR_HEIGHT, LessonCard


def pump(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)


def make_card(**options) -> LessonCard:
    return LessonCard(**{"characters_per_second": 400, "linger_seconds": 5, "fade_seconds": 0.1, **options})


def title_point(card: LessonCard) -> QPoint:
    return QPoint(SHADOW + 60, SHADOW + TITLE_BAR_HEIGHT // 2)


def test_card_takes_the_mouse_but_never_the_keyboard(qt_app):
    card = make_card()
    try:
        flags = card.windowFlags()
        assert not flags & Qt.WindowType.WindowTransparentForInput
        assert not card.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
        assert card.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    finally:
        card.close()


def test_dragging_the_title_bar_moves_the_card_and_is_remembered(qt_app):
    card = make_card()
    moved = []
    card.moved.connect(lambda: moved.append(True))
    try:
        card.add_note("hello")
        start = card.pos()
        grab = title_point(card)
        QTest.mousePress(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grab)
        QTest.mouseMove(card, grab + QPoint(-120, 80))
        QTest.mouseRelease(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grab + QPoint(-120, 80))
        assert card.pos() == start + QPoint(-120, 80)
        assert moved
        dropped_at = card.pos()
        card.clear()
        pump(0.4)
        assert not card.isVisible()
        card.add_note("a new card")  # docks where Yoshi left the last one
        assert card.pos() == dropped_at
    finally:
        card.close()


def test_dragging_the_body_does_not_move_the_card(qt_app):
    card = make_card()
    try:
        card.add_note("hello")
        start = card.pos()
        body = QPoint(SHADOW + 60, SHADOW + TITLE_BAR_HEIGHT + 30)
        QTest.mousePress(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, body)
        QTest.mouseMove(card, body + QPoint(-100, 50))
        QTest.mouseRelease(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, body + QPoint(-100, 50))
        assert card.pos() == start
    finally:
        card.close()


def test_close_button_clears_the_card(qt_app):
    card = make_card()
    try:
        card.add_note("hello")
        button = card.close_button_rect().center().toPoint()
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, button)
        pump(0.4)
        assert not card.isVisible()
        assert card.content_blocks() == []
    finally:
        card.close()


def wheel(card: LessonCard, delta_y: int) -> None:
    position = QPointF(SHADOW + 60, SHADOW + TITLE_BAR_HEIGHT + 40)
    event = QWheelEvent(
        position,
        QPointF(card.mapToGlobal(position.toPoint())),
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(card, event)


def test_wheel_scrolls_back_and_new_writing_follows_again(qt_app):
    card = make_card(max_height=360)
    try:
        for index in range(10):
            card.add_note(f"note number {index} that is long enough to wrap onto a second line")
        pump(2.0)  # let every note finish writing: you can only scroll back over what's written
        later = time.monotonic() + 60
        bottom = card.scroll_offset(later)
        assert bottom > 0
        wheel(card, 120)  # wheel up: look at earlier notes
        assert card.scroll_offset(later) < bottom
        wheel(card, 10_000)  # can't scroll past the top
        assert card.scroll_offset(later) == 0
        card.add_note("a fresh note")  # new writing: follow the newest line again
        assert card.scroll_offset(time.monotonic() + 120) > 0
    finally:
        card.close()


def test_remembered_spot_is_kept_on_a_screen(qt_app):
    card = make_card()
    try:
        card.add_note("hello")
        card._user_position = QPoint(-5000, -5000)  # e.g. a monitor that was unplugged
        card.clear()
        pump(0.4)
        card.add_note("again")
        available = QApplication.primaryScreen().availableGeometry()
        assert available.intersects(QRect(card.pos(), card.size()))
    finally:
        card.close()
