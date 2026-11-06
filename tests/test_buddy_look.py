from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter

from clicky.followup_chips import FollowUpChips
from clicky.lesson_card import LessonCard
from clicky.overlay import BuddyOverlay


def render_buddy() -> QImage:
    overlay = BuddyOverlay()
    image = QImage(80, 80, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    overlay._paint_buddy(painter, 20, 20)
    painter.end()
    overlay.close()
    return image.convertToFormat(QImage.Format.Format_ARGB32)


def test_buddy_has_no_white_outline(qt_app):
    image = render_buddy()
    whitish = 0
    for y in range(image.height()):
        for x in range(image.width()):
            color = image.pixelColor(x, y)
            if color.alpha() > 120 and min(color.red(), color.green(), color.blue()) > 200:
                whitish += 1
    assert whitish == 0


def test_buddy_corners_are_soft(qt_app):
    image = render_buddy()
    # The sharp tip used to be a fully opaque point at (20, 20); a rounded tip leaves it translucent.
    assert image.pixelColor(20, 20).alpha() < 200
    # The body is still solid blue.
    body = image.pixelColor(26, 30)
    assert body.alpha() > 200 and body.blue() > body.red()


def test_card_announces_when_it_appears(qt_app):
    card = LessonCard()  # offscreen platform: a real show() is harmless and makes isVisible() true
    appeared = []
    card.appeared.connect(lambda: appeared.append(True))
    try:
        card.add_note("first")
        card.add_note("second")  # same card: no second announcement
        assert appeared == [True]
    finally:
        card.close()


def test_chips_announce_when_they_appear(qt_app):
    chips = FollowUpChips()
    chips.show = lambda: None
    appeared = []
    chips.appeared.connect(lambda: appeared.append(True))
    try:
        chips.show_options(["Go deeper"], below=QRect(0, 0, 400, 300))
        assert appeared == [True]
    finally:
        chips.close()
