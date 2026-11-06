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


def overlaps(card: LessonCard, rect: QRect) -> bool:
    return QRect(card.pos(), card.size()).intersects(rect)


def test_card_glides_out_of_the_way_of_a_mark_under_it(qt_app):
    card = make_card()
    try:
        card.add_note("hello")
        # Clicky underlined something under the card (right half: the 800 px test screen's left dock is clear)
        mark = QRect(card.x() + 220, card.y() + 60, 120, 24)
        assert overlaps(card, mark)
        card.avoid(mark)
        pump(0.5)
        assert not overlaps(card, mark)
        assert card.isVisible()
    finally:
        card.close()


def test_a_mark_elsewhere_does_not_move_the_card(qt_app):
    card = make_card()
    try:
        card.add_note("hello")
        start = card.pos()
        card.avoid(QRect(10, 700, 100, 20))
        pump(0.4)
        assert card.pos() == start
    finally:
        card.close()


def test_a_new_card_docks_away_from_marks_already_on_screen(qt_app):
    available = QApplication.primaryScreen().availableGeometry()
    card = make_card()
    try:
        mark = QRect(available.right() - 120, available.top() + 100, 100, 24)  # where the card usually docks
        card.avoid(mark)
        card.add_note("hello")
        assert not overlaps(card, mark)
    finally:
        card.close()


def test_expired_marks_are_forgotten(qt_app):
    available = QApplication.primaryScreen().availableGeometry()
    card = make_card()
    try:
        mark = QRect(available.right() - 120, available.top() + 100, 100, 24)
        card.avoid(mark, seconds=0.05)
        pump(0.1)
        card.add_note("hello")
        assert overlaps(card, mark)  # the mark is gone, so the usual top-right spot is fine
    finally:
        card.close()


def test_a_mark_under_a_spot_you_dragged_it_to_still_wins(qt_app):
    card = make_card()
    try:
        card.add_note("hello")
        card._user_position = card.pos()
        card.avoid(QRect(card.x() + 220, card.y() + 60, 120, 24))
        pump(0.5)
        assert card.pos() != card._user_position
    finally:
        card.close()


def test_marks_are_kept_until_forgotten_not_for_a_fixed_time(qt_app):
    available = QApplication.primaryScreen().availableGeometry()
    card = make_card()
    try:
        mark = QRect(available.right() - 120, available.top() + 100, 100, 24)
        card.avoid(mark)
        card._marks = [(rect, expires - 60) for rect, expires in card._marks]  # a minute later: still on screen
        card.add_note("hello")
        assert not overlaps(card, mark)
        card.clear()
        pump(0.4)
        card.forget_marks()  # the marks were cleared or faded
        card.add_note("again")
        assert overlaps(card, mark)  # back at the usual top-right spot
    finally:
        card.close()


def test_a_card_dragged_low_keeps_its_bottom_on_screen(qt_app):
    available = QApplication.primaryScreen().availableGeometry()
    card = make_card()
    try:
        card.add_note("hello")
        card._user_position = QPoint(available.left() + 40, available.bottom() - 150)
        card.clear()
        pump(0.4)
        for index in range(10):
            card.add_note(f"note number {index} that is long enough to wrap onto a second line")
        assert card.geometry().bottom() <= available.bottom()
    finally:
        card.close()


def test_close_button_dismisses_the_card_for_the_rest_of_the_reply(qt_app):
    card = make_card()
    closed = []
    card.closed.connect(lambda: closed.append(True))
    try:
        card.add_note("hello")
        button = card.close_button_rect().center().toPoint()
        QTest.mouseClick(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, button)
        pump(0.4)
        assert closed
        card.add_note("a later note from the same answer")  # must not bring the card back
        assert not card.isVisible()
        card.start_reply()  # the next question
        card.add_note("next answer")
        assert card.isVisible()
    finally:
        card.close()


def test_pressing_the_title_bar_stops_a_glide(qt_app):
    card = make_card()
    try:
        card.add_note("hello")
        card.avoid(QRect(card.x() + 220, card.y() + 60, 120, 24))  # starts gliding left
        grab = title_point(card)
        QTest.mousePress(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grab)
        QTest.mouseMove(card, grab + QPoint(0, 200))
        held_at = card.pos()
        pump(0.4)  # longer than the glide
        assert card.pos() == held_at  # the drag wins
        QTest.mouseRelease(card, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, grab + QPoint(0, 200))
    finally:
        card.close()


def test_a_glide_never_carries_over_to_the_next_card(qt_app):
    card = make_card()
    try:
        card.add_note("hello")
        card.avoid(QRect(card.x() + 220, card.y() + 60, 120, 24))
        card.forget_marks()
        card._reset()  # cleared mid-glide
        card.add_note("new card")
        docked = card.pos()
        pump(0.4)
        assert card.pos() == docked
    finally:
        card.close()


def test_using_the_card_holds_off_the_fade(qt_app):
    card = make_card(linger_seconds=0.3)
    try:
        card.add_note("hello")
        pump(0.1)
        card.finish()
        for _ in range(4):  # keep scrolling for longer than the linger
            pump(0.15)
            wheel(card, 120)
        assert card.isVisible()
    finally:
        card.close()
