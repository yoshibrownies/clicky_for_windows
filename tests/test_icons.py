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


def test_unknown_icons_are_none():
    assert icon_subpaths("dragon") is None
    assert icon_subpaths(None) is None


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_every_icon_sits_on_its_anchor_and_fills_its_size(name):
    points = [point for points in icon_subpaths(name) for point in points]
    xs, ys = [x for x, _ in points], [y for _, y in points]
    assert min(ys) == pytest.approx(0.0, abs=1e-9)  # stands exactly on its anchor
    assert max(max(ys) - min(ys), max(xs) - min(xs)) == pytest.approx(1.0, abs=1e-9)  # size = longer side
    assert (min(xs) + max(xs)) / 2 == pytest.approx(0.0, abs=1e-9)  # centred on x


def test_the_prompt_describes_icon_size_as_the_longer_side():
    from clicky.prompts import COMPANION_SYSTEM_PROMPT

    lowered = COMPANION_SYSTEM_PROMPT.lower()
    assert "longer side" in lowered and "exactly at x, y" in lowered
