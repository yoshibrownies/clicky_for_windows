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
        assert card.scroll_offset(time.monotonic() + 60) > 0  # once everything is written, it scrolls
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


def test_pen_and_scroll_follow_written_content_not_queued_blocks(qt_app):
    from clicky.lesson_card import SHADOW, TITLE_BAR_HEIGHT

    card = make_card(max_height=400, characters_per_second=40)
    try:
        card.add_heading("What slows you down?")
        for index in range(8):
            card.add_note(f"note number {index} about drag")
        card.add_formula("F = 1/2 rho C A v^2")
        pump(0.05)
        assert card.scroll_offset() == 0  # only the heading has started: nothing to scroll past yet
        pen = card._pen_position(time.monotonic())
        assert pen is not None
        assert SHADOW + TITLE_BAR_HEIGHT <= pen.y() <= card.height() - SHADOW
    finally:
        card.close()


def test_pen_prefers_new_writing_over_a_playing_animation(qt_app):
    card = make_card(characters_per_second=20)
    try:
        card.play_animation(tiny_scene(duration=6.0))
        card.add_note("the ball keeps rolling along")
        pump(0.9)  # the animation is still playing; the note started typing at 0.6 s
        pen = card._pen_position(time.monotonic())
        assert pen is not None
        note_top = card._block_tops()[1]
        assert pen.y() >= note_top
    finally:
        card.close()


def test_animation_alone_still_gives_the_pen_a_place(qt_app):
    card = make_card()
    try:
        card.play_animation(tiny_scene(duration=6.0))  # never painted here, so the scene has no focus point
        pump(0.1)
        assert card._pen_position(time.monotonic()) is not None
    finally:
        card.close()


def test_card_emits_faded_when_it_goes_away(qt_app):
    card = LessonCard(characters_per_second=400, linger_seconds=0.1, fade_seconds=0.1)
    faded = []
    card.faded.connect(lambda: faded.append(True))
    try:
        card.add_note("hello")
        pump(0.1)
        card.finish()
        pump(0.5)
        assert not card.isVisible()
        assert faded
    finally:
        card.close()


def test_height_cap_leaves_room_for_the_follow_up_chips(qt_app):
    from PySide6.QtGui import QGuiApplication

    from clicky.followup_chips import CHIP_GAP, CHIP_HEIGHT, MAX_CHIPS
    from clicky.followup_chips import SHADOW as CHIP_SHADOW

    card = LessonCard()
    try:
        available = QGuiApplication.primaryScreen().availableGeometry()
        chips_height = 2 * CHIP_SHADOW + MAX_CHIPS * CHIP_HEIGHT + (MAX_CHIPS - 1) * CHIP_GAP
        assert 56 + card._height_cap() + 8 + chips_height <= available.height()
    finally:
        card.close()


def test_highlight_rings_the_newest_animation_that_has_that_object(qt_app):
    import json

    from clicky.scene import parse_scene

    def labelled_scene(label):
        return parse_scene(json.dumps({"duration": 2, "objects": [{"type": "circle", "x": 1, "y": 1, "label": label}]}))

    card = make_card()
    try:
        card.start_reply()
        card.play_animation(labelled_scene("first cause"))
        card.play_animation(labelled_scene("you"))
        card.highlight("first cause")  # mentioned again while the later picture is up
        assert card._highlight is not None and card._highlight[2].scene.objects[0].label == "first cause"
        card.highlight("you")
        assert card._highlight[2].scene.objects[0].label == "you"
        card.highlight("nowhere")  # unknown labels still go to the newest picture (it may be a text object)
        assert card._highlight[2].scene.objects[0].label == "you"
    finally:
        card.close()


def test_a_diagram_with_long_labels_gets_a_taller_block_and_keeps_every_word(qt_app):
    card = make_card()
    try:
        card.start_reply()
        card.set_diagram(
            "sensory input arrives -> attention filters it -> working memory holds it -> sleep consolidates it"
        )
        block = card._blocks[-1]
        assert 190 < block.height <= 340
        layout = block.diagram_layout
        assert layout is not None
        for node, label in enumerate(block.diagram.nodes):
            assert " ".join(layout.lines[node]) == label  # wrapped, never cut
    finally:
        card.close()


# ---------- finished animations become still pictures ----------


def _dot_scene():
    import json

    from clicky.scene import parse_scene

    return parse_scene(
        json.dumps(
            {
                "duration": 1,
                "world": {"x": [0, 10], "y": [0, 10]},
                "objects": [{"type": "circle", "x": 5, "y": 5, "r": 30, "color": "red", "label": "dot"}],
            }
        )
    )


def _paint_block(card, block, now):
    from PySide6.QtGui import QImage, QPainter

    image = QImage(card.width(), card.height(), QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    card._paint_animation(painter, block, 60.0, now)
    painter.end()
    return image


def _counting_frames(scene):
    calls = []
    original = scene.frame

    def counted(t):
        calls.append(t)
        return original(t)

    scene.frame = counted
    return calls


def test_a_finished_animation_is_drawn_from_a_still_picture(qt_app):
    card = make_card()
    try:
        card.start_reply()
        card.play_animation(_dot_scene())
        block = card._blocks[-1]
        calls = _counting_frames(block.scene)
        done = block.starts_at + 2.0
        _paint_block(card, block, done)
        assert block.still is not None
        calls.clear()
        _paint_block(card, block, done + 0.5)
        assert calls == []  # not re-evaluated: the still picture was drawn
    finally:
        card.close()


def test_a_highlight_on_a_finished_animation_paints_live(qt_app):
    import time

    card = make_card()
    try:
        card.start_reply()
        card.play_animation(_dot_scene())
        block = card._blocks[-1]
        block.starts_at = time.monotonic() - 5.0  # long finished
        _paint_block(card, block, time.monotonic())
        assert block.still is not None
        calls = _counting_frames(block.scene)
        card.highlight("dot")
        _paint_block(card, block, time.monotonic() + 0.5)
        assert calls, "a ringed animation paints live so the ring can follow its object"
        assert card._scene_painter.highlight_rect is not None
    finally:
        card.close()


def test_the_still_picture_looks_like_the_live_drawing(qt_app):
    card = make_card()
    try:
        card.start_reply()
        card.play_animation(_dot_scene())
        block = card._blocks[-1]
        live = _paint_block(card, block, block.starts_at + block.scene.duration - 1e-3 + 0.0)  # last live frame
        block.still = None
        still = _paint_block(card, block, block.starts_at + 3.0)
        different = 0
        samples = 0
        for x in range(0, card.width(), 4):
            for y in range(0, card.height(), 4):
                a, b = live.pixelColor(x, y), still.pixelColor(x, y)
                samples += 1
                if (
                    max(
                        abs(a.red() - b.red()),
                        abs(a.green() - b.green()),
                        abs(a.blue() - b.blue()),
                        abs(a.alpha() - b.alpha()),
                    )
                    > 8
                ):
                    different += 1
        assert different / samples < 0.02
    finally:
        card.close()
