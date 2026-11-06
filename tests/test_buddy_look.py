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


def test_reply_text_is_never_shown_next_to_the_cursor(qt_app):
    overlay = BuddyOverlay()
    try:
        assert not hasattr(overlay, "show_reply")
        overlay.set_state("listening")
        overlay.show_transcript("why does a ball orbit")
        assert overlay.has_bubble  # your own words show while you talk
        overlay.set_state("processing")
        overlay.set_state("responding")
        assert not overlay.has_bubble  # nothing by the cursor while Clicky explains
        overlay.show_notice("couldn't reach the worker")
        assert overlay.has_bubble  # short notices still show
    finally:
        overlay.close()


def test_status_pill_announces_when_it_appears(qt_app):
    from clicky.status_pill import StatusPill

    pill = StatusPill()
    appeared = []
    pill.appeared.connect(lambda: appeared.append(True))
    try:
        pill.set_state("listening")
        pill.set_state("processing")  # already up: no second announcement
        assert appeared == [True]
    finally:
        pill.close()


def test_long_notices_stay_up_long_enough_to_read(qt_app):
    import time

    overlay = BuddyOverlay()
    try:
        overlay.show_notice("short")
        short_left = overlay._bubble.expires_at - time.monotonic()
        overlay.show_notice("a whole spoken answer that has to be read instead of heard. " * 6)
        long_left = overlay._bubble.expires_at - time.monotonic()
        assert short_left <= 6
        assert long_left >= 15
    finally:
        overlay.close()


def test_a_long_notice_keeps_its_beginning(qt_app):
    overlay = BuddyOverlay()
    try:
        answer = "couldn't play the voice: tts failed. here's my answer: " + "this sentence explains a thing. " * 40
        fitted = overlay._fit_bubble_text(answer, 200, keep="start")
        assert fitted.startswith("couldn't play the voice")
        assert fitted.endswith("…")
        transcript = overlay._fit_bubble_text("word " * 300 + "LAST", 200, keep="end")
        assert transcript.endswith("LAST")  # your own words keep their newest part
    finally:
        overlay.close()
