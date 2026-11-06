import json
import math
import time

from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter

from clicky.scene import parse_scene
from clicky.scene_painter import ScenePainter

ORBIT = {
    "title": "a ball orbits",
    "duration": 4,
    "world": {"x": [-5, 5], "y": [-5, 5]},
    "objects": [
        {"type": "circle", "x": "4*cos(t)", "y": "4*sin(t)", "r": 10, "color": "blue", "label": "ball"},
        {"type": "point", "x": 0, "y": 0, "color": "gray", "label": "centre"},
    ],
}


def paint(painter_object: ScenePainter, t: float, highlight) -> None:
    image = QImage(400, 300, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    try:
        painter_object.paint(painter, QRectF(0, 0, 400, 300), parse_scene(json.dumps(ORBIT)), t, highlight=highlight)
    finally:
        painter.end()  # an open painter on a freed image crashes the process


def test_highlight_follows_the_object_as_it_moves(qt_app):
    scene_painter = ScenePainter()
    paint(scene_painter, 0.0, ("ball", 1.0))  # ball due east
    east = scene_painter.highlight_rect
    paint(scene_painter, math.pi / 2, ("Ball", 1.0))  # a quarter turn later: due north (label is case-blind)
    north = scene_painter.highlight_rect
    assert east is not None and north is not None
    assert north.center().y() < east.center().y() - 50  # moved up
    assert north.center().x() < east.center().x() - 50  # and left
    assert scene_painter.focus_point is not None
    assert north.contains(scene_painter.focus_point)


def test_highlight_of_an_unknown_label_or_after_it_ends_draws_nothing(qt_app):
    scene_painter = ScenePainter()
    paint(scene_painter, 0.0, ("planet", 1.0))
    assert scene_painter.highlight_rect is None
    paint(scene_painter, 0.0, ("ball", 99.0))  # long over
    assert scene_painter.highlight_rect is None
    paint(scene_painter, 0.0, None)
    assert scene_painter.highlight_rect is None


def test_highlight_tag_is_parsed_and_limited(qt_app):
    from clicky.visuals import parse_visual_reply

    reply = "see the ball [HIGHLIGHT:ball] swing round. " + " ".join(f"[HIGHLIGHT:x{n}]" for n in range(6))
    parsed = parse_visual_reply(reply)
    highlights = [event for event in parsed.events if event.kind == "highlight"]
    assert highlights[0].text == "ball"
    assert 0 < highlights[0].fraction < 1
    assert len(highlights) == 4
    assert "HIGHLIGHT" not in parsed.spoken_text


def test_card_highlight_targets_the_animation_and_keeps_animating(qt_app):
    from clicky.lesson_card import LessonCard

    card = LessonCard(characters_per_second=400)
    card.show = lambda: None
    try:
        card.highlight("ball")  # no animation yet: ignored
        assert card.highlighted_label is None
        card.play_animation(parse_scene(json.dumps({**ORBIT, "duration": 1})))
        time.sleep(1.2)  # the animation has finished playing
        card.highlight("ball")
        assert card.highlighted_label == "ball"
        assert card.is_animating  # the ring needs frames even though the scene is over
    finally:
        card.close()


def test_pen_goes_to_the_ring_even_while_a_note_is_typing(qt_app):
    from clicky.lesson_card import LessonCard

    card = LessonCard(characters_per_second=10)  # slow typing: the note is still being written
    try:
        card.play_animation(parse_scene(json.dumps(ORBIT)))
        card.add_note("the ball keeps going round and round the centre")
        deadline = time.monotonic() + 0.9
        from PySide6.QtWidgets import QApplication

        while time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.005)
        card.highlight("ball")
        for _ in range(5):
            card.repaint()
            QApplication.processEvents()
        ring = card._scene_painter.highlight_rect
        assert ring is not None
        pen = card._pen_position(time.monotonic())
        assert pen is not None and ring.contains(pen)
    finally:
        card.close()


def test_ring_hugs_tall_objects_and_stays_inside_the_panel(qt_app):
    tall = {
        "duration": 2,
        "world": {"x": [0, 10], "y": [0, 10]},
        "objects": [
            {"type": "rect", "x": 4.5, "y": 0, "w": 1, "h": 9, "color": "orange", "label": "5"},
            {"type": "line", "x1": -50, "y1": 5, "x2": 60, "y2": 5, "label": "ground"},
        ],
    }
    scene_painter = ScenePainter()
    image = QImage(400, 300, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(QColor(255, 255, 255))
    area = QRectF(0, 0, 400, 300)
    for label in ("5", "ground"):
        painter = QPainter(image)
        try:
            scene_painter.paint(painter, area, parse_scene(json.dumps(tall)), 0.5, highlight=(label, 1.0))
        finally:
            painter.end()
        ring = scene_painter.highlight_rect
        assert ring is not None
        assert area.contains(ring), label  # never spills outside the animation panel
    # the tall bar gets a tall, narrow ring, not a huge circle that also rings its neighbours
    painter = QPainter(image)
    try:
        scene_painter.paint(painter, area, parse_scene(json.dumps(tall)), 0.5, highlight=("5", 1.0))
    finally:
        painter.end()
    ring = scene_painter.highlight_rect
    assert ring.width() < ring.height() / 2
