import json

import pytest

from clicky.scene import parse_scene
from clicky.scene_painter import WorldMapper, nice_ticks


def short_scene(duration: float = 1.0):
    return parse_scene(
        json.dumps(
            {
                "title": "test",
                "duration": duration,
                "world": {"x": [0, 10], "y": [0, 50]},
                "axes": {"x": "time (s)", "y": "height (m)"},
                "objects": [
                    {"type": "circle", "x": "t*5", "y": "50 - 4.9*t^2", "trail": True, "label": "ball"},
                    {"type": "arrow", "x": 2, "y": 10, "dx": 3, "dy": "t*10", "label": "v"},
                    {"type": "plot", "fn": "x*4", "from": 0, "to": "t*10"},
                    {"type": "rect", "x": 7, "y": 0, "w": 1, "h": [[0, 5], [1, 40]]},
                    {"type": "line", "x1": 0, "y1": 25, "x2": 10, "y2": 25, "dashed": True},
                    {"type": "text", "x": 6, "y": 45, "text": "d = ½gt²"},
                    {"type": "point", "x": 9, "y": 9, "label": "p"},
                ],
                "captions": [{"at": 0, "text": "watch"}],
            }
        )
    )


def test_world_mapper_puts_origin_bottom_left_and_y_up():
    mapper = WorldMapper((0, 10, 0, 50), (100, 50, 400, 300))
    assert mapper.to_pixel(0, 0) == pytest.approx((100, 350))
    assert mapper.to_pixel(10, 50) == pytest.approx((500, 50))
    assert mapper.to_pixel(5, 25) == pytest.approx((300, 200))
    assert mapper.vector_to_pixel(1, 5) == pytest.approx((40, -30))


def test_world_mapper_clamps_absurd_values():
    mapper = WorldMapper((0, 10, 0, 10), (0, 0, 100, 100))
    x, y = mapper.to_pixel(1e9, -1e9)
    assert abs(x) < 1e5 and abs(y) < 1e5


@pytest.mark.parametrize(
    "low, high, expected",
    [(0, 50, [0, 10, 20, 30, 40, 50]), (0, 10, [0, 2, 4, 6, 8, 10]), (0, 3.2, [0, 0.5, 1, 1.5, 2, 2.5, 3])],
)
def test_nice_ticks(low, high, expected):
    assert nice_ticks(low, high) == pytest.approx(expected)


def test_nice_ticks_handles_negative_and_tiny_ranges():
    ticks = nice_ticks(-5, 5)
    assert 0 in ticks and ticks[0] >= -5 and ticks[-1] <= 5
    assert 2 <= len(nice_ticks(0, 0.001)) <= 12


def test_scene_painter_draws_into_any_rect_and_reports_a_focus_point(qt_app):
    from PySide6.QtCore import QRectF
    from PySide6.QtGui import QImage, QPainter

    from clicky.scene_painter import ScenePainter

    image = QImage(500, 320, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    scene_painter = ScenePainter()
    scene_painter.paint(painter, QRectF(20, 20, 460, 280), short_scene(), 0.5)
    painter.end()
    painted = sum(1 for x in range(0, 500, 5) for y in range(0, 320, 5) if image.pixelColor(x, y).alpha() > 0)
    assert painted > 100
    assert scene_painter.focus_point is not None
    assert 20 <= scene_painter.focus_point.x() <= 480 and 20 <= scene_painter.focus_point.y() <= 300
