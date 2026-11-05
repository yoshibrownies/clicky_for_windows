import time

import pytest
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from clicky.annotations import AnnotationLayer, ellipse_points, partial_polyline, underline_points
from clicky.controller import ScreenVisualEvent


def pump(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)


def test_underline_runs_left_to_right_just_under_the_text():
    points = underline_points(100, 300, 220, seed=3)
    xs = [x for x, _ in points]
    assert xs[0] == pytest.approx(100, abs=2) and xs[-1] == pytest.approx(300, abs=2)
    assert xs == sorted(xs)
    assert all(220 <= y <= 230 for _, y in points)  # a few px below the text's bottom edge, gentle wobble


def test_underline_is_deterministic_per_seed():
    assert underline_points(0, 50, 10, seed=1) == underline_points(0, 50, 10, seed=1)
    assert underline_points(0, 50, 10, seed=1) != underline_points(0, 50, 10, seed=2)


def test_ellipse_surrounds_the_box_and_overshoots_its_start():
    left, top, right, bottom = 400, 50, 480, 90
    points = ellipse_points((left, top, right, bottom), seed=0)
    xs = [x for x, _ in points]
    ys = [y for _, y in points]
    assert min(xs) < left and max(xs) > right and min(ys) < top and max(ys) > bottom
    assert len(points) > 40


def test_partial_polyline_grows_with_progress():
    points = [(0.0, 0.0), (10.0, 0.0), (20.0, 0.0)]
    assert partial_polyline(points, 0.0) == [(0.0, 0.0)]
    assert partial_polyline(points, 1.0) == points
    half = partial_polyline(points, 0.5)
    assert half[-1] == pytest.approx((10.0, 0.0))
    quarter = partial_polyline(points, 0.25)
    assert quarter[-1] == pytest.approx((5.0, 0.0))


def test_layer_draws_marks_then_fades_and_stops_its_timer(qt_app):
    screen_geometry = QGuiApplication.primaryScreen().geometry()
    origin_x, origin_y = screen_geometry.x(), screen_geometry.y()
    layer = AnnotationLayer(linger_seconds=0.1, fade_seconds=0.1)
    try:
        layer.add_mark(
            ScreenVisualEvent(
                kind="underline", fraction=0, box=(origin_x + 50, origin_y + 40, origin_x + 250, origin_y + 60)
            )
        )
        layer.add_mark(
            ScreenVisualEvent(
                kind="circle", fraction=0, box=(origin_x + 300, origin_y + 100, origin_x + 380, origin_y + 140)
            )
        )
        assert layer.is_animating
        pump(0.8)  # draw-in animations complete
        windows = layer.visible_windows()
        assert len(windows) == 1
        image = windows[0].grab().toImage()
        painted = sum(1 for x in range(40, 400, 4) for y in range(30, 160, 4) if image.pixelColor(x, y).alpha() > 0)
        assert painted > 20
        layer.finish()
        pump(0.6)
        assert layer.visible_windows() == []
        assert not layer.is_animating
    finally:
        layer.close_all()


def test_clear_removes_marks_quickly(qt_app):
    screen_geometry = QGuiApplication.primaryScreen().geometry()
    layer = AnnotationLayer(linger_seconds=10, fade_seconds=0.1)
    try:
        layer.add_mark(
            ScreenVisualEvent(
                kind="underline",
                fraction=0,
                box=(
                    screen_geometry.x() + 10,
                    screen_geometry.y() + 10,
                    screen_geometry.x() + 90,
                    screen_geometry.y() + 20,
                ),
            )
        )
        pump(0.1)
        layer.clear()
        pump(0.5)
        assert layer.visible_windows() == []
    finally:
        layer.close_all()


def test_mark_without_box_is_ignored(qt_app):
    layer = AnnotationLayer()
    try:
        layer.add_mark(ScreenVisualEvent(kind="underline", fraction=0, box=None))
        assert not layer.is_animating
    finally:
        layer.close_all()
