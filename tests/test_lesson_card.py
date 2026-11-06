import json
import time

import pytest
from PySide6.QtWidgets import QApplication

from clicky.lesson_card import DEFAULT_TITLE, LessonCard
from clicky.scene import parse_scene


def pump(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)


def make_card(**options) -> LessonCard:
    card = LessonCard(**{"characters_per_second": 400, "linger_seconds": 0.2, "fade_seconds": 0.1, **options})
    card.show = lambda: None  # keep tests off the real screen
    return card


def tiny_scene(duration: float = 1.0):
    return parse_scene(
        json.dumps(
            {
                "duration": duration,
                "world": {"x": [0, 10], "y": [0, 10]},
                "objects": [{"type": "circle", "x": "t*5", "y": 5, "label": "ball"}],
            }
        )
    )


def test_blocks_appear_in_order_and_type_out(qt_app):
    card = make_card()
    try:
        card.set_title("drag forces")
        card.add_heading("What slows you down?")
        card.add_note("drag pushes against the motion")
        card.add_formula("F = ½ρCAv²")
        assert card.title == "drag forces"
        assert [kind for kind, _ in card.content_blocks()] == ["heading", "note", "formula"]
        assert card.revealed_fraction() < 1.0
        pump(0.6)
        assert card.revealed_fraction() == pytest.approx(1.0)
        assert not card.is_animating
        assert not card.grab().toImage().isNull()
    finally:
        card.close()


def test_default_title_until_one_is_set(qt_app):
    card = make_card()
    try:
        card.add_note("hello")
        assert card.title == DEFAULT_TITLE
    finally:
        card.close()


def test_writing_point_is_emitted_while_writing(qt_app):
    card = make_card(characters_per_second=60)
    points = []
    card.writing_point.connect(points.append)
    try:
        card.add_heading("What slows you down?")
        card.add_note("drag grows with the square of speed")
        pump(0.5)
        assert len(points) >= 3
        geometry = card.geometry()
        for point in points:
            assert geometry.left() - 5 <= point.x() <= geometry.right() + 5
            assert geometry.top() - 5 <= point.y() <= geometry.bottom() + 5
        assert len({(point.x(), point.y()) for point in points}) > 1  # the pen moves
    finally:
        card.close()


def test_diagram_and_animation_blocks(qt_app):
    card = make_card()
    try:
        card.set_diagram("drag -> slower; motion -> faster")
        card.play_animation(tiny_scene(duration=1.0))
        card.set_diagram("no arrows")  # ignored
        card.play_animation(None)  # ignored
        assert [kind for kind, _ in card.content_blocks()] == ["diagram", "animation"]
        pump(0.3)
        assert card.is_animating
        pump(3.0)  # queued behind the ~1.5 s diagram, then plays for 1 s
        assert not card.is_animating  # animation finished: timer stopped, last frame held
    finally:
        card.close()


def test_height_grows_then_caps_and_scrolls(qt_app):
    card = make_card(max_height=480)
    try:
        start_height = card.height()
        card.add_heading("A heading")
        card.add_note("one note")
        assert card.height() > start_height
        for index in range(12):
            card.add_note(f"note {index} that is long enough to wrap onto a second line on the card")
        assert card.height() <= 480
        assert card.scroll_offset() > 0
    finally:
        card.close()


def test_finish_lingers_then_fades_and_clear_empties(qt_app):
    card = LessonCard(characters_per_second=400, linger_seconds=0.15, fade_seconds=0.1)
    try:
        card.add_note("hello")
        assert card.isVisible()
        pump(0.1)
        card.finish()
        pump(0.6)
        assert not card.isVisible()
        card.add_note("again")
        card.clear()
        pump(0.4)
        assert not card.isVisible()
        assert card.content_blocks() == []
    finally:
        card.close()


def test_disabled_card_ignores_everything(qt_app):
    card = LessonCard()
    try:
        card.set_enabled(False)
        card.add_heading("x")
        card.add_note("y")
        card.play_animation(tiny_scene())
        assert not card.isVisible()
        assert card.content_blocks() == []
    finally:
        card.close()
