import pytest

from clicky.screens import (
    ScreenGeometry,
    build_screen_label,
    fit_within,
    map_image_point_to_screen,
    order_screens_cursor_first,
)


def test_fit_within_downscales_landscape():
    assert fit_within(3840, 2160, 1600) == (1600, 900)


def test_fit_within_downscales_portrait():
    assert fit_within(1440, 2560, 1600) == (900, 1600)


def test_fit_within_never_upscales():
    assert fit_within(1280, 720, 1600) == (1280, 720)


def test_order_screens_cursor_first_keeps_others_in_order():
    assert order_screens_cursor_first(["a", "b", "c"], cursor_index=2) == ["c", "a", "b"]
    assert order_screens_cursor_first(["a", "b"], cursor_index=0) == ["a", "b"]


def test_single_screen_label():
    label = build_screen_label(index=0, count=1, is_cursor_screen=True, width=1600, height=900)
    assert label == "user's screen (cursor is here) (image dimensions: 1600x900 pixels)"


def test_multi_screen_labels():
    primary = build_screen_label(index=0, count=2, is_cursor_screen=True, width=1600, height=900)
    other = build_screen_label(index=1, count=2, is_cursor_screen=False, width=1280, height=1024)
    assert primary == (
        "screen 1 of 2 — cursor is on this screen (primary focus) (image dimensions: 1600x900 pixels)"
    )
    assert other == "screen 2 of 2 — secondary screen (image dimensions: 1280x1024 pixels)"


def test_map_point_on_scaled_primary_monitor():
    # 4K panel at 150% scaling: Qt reports 2560x1440 logical. Screenshot sent at 1600x900.
    geometry = ScreenGeometry(x=0, y=0, width=2560, height=1440)
    assert map_image_point_to_screen((800, 450), (1600, 900), geometry) == (1280, 720)


def test_map_point_on_secondary_monitor_with_negative_origin():
    geometry = ScreenGeometry(x=-1920, y=-200, width=1920, height=1080)
    assert map_image_point_to_screen((1600, 900), (1600, 900), geometry) == (-1, 879)
    assert map_image_point_to_screen((0, 0), (1600, 900), geometry) == (-1920, -200)


def test_map_point_clamps_out_of_range_coordinates():
    geometry = ScreenGeometry(x=0, y=0, width=1920, height=1080)
    assert map_image_point_to_screen((5000, -40), (1600, 900), geometry) == (1919, 0)


def test_map_point_rejects_empty_image():
    with pytest.raises(ValueError):
        map_image_point_to_screen((1, 1), (0, 900), ScreenGeometry(0, 0, 10, 10))
