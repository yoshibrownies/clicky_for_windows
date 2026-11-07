import pytest

from clicky.icons import ICON_NAMES, icon_subpaths

EXPECTED = {
    "person",
    "head",
    "lightbulb",
    "clock",
    "gear",
    "eye",
    "die",
    "heart",
}


def test_the_library_has_the_planned_figures():
    assert set(ICON_NAMES) == EXPECTED


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_icon_parses_and_fits_its_unit_box(name):
    subpaths = icon_subpaths(name)
    assert subpaths
    points = [point for points in subpaths for point in points]
    assert all(-0.56 <= x <= 0.56 and -0.06 <= y <= 1.06 for x, y in points)
    assert max(y for _, y in points) > 0.6  # uses the box, not a speck in a corner


def test_unknown_icons_are_none():
    assert icon_subpaths("dragon") is None
    assert icon_subpaths(None) is None
