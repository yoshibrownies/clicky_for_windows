import math

import pytest

from clicky.paths import MAX_PATH_COMMANDS, parse_path_data, partial_subpaths, polyline_length


def test_absolute_and_relative_lines():
    assert parse_path_data("M 0 0 L 3 4") == [[(0.0, 0.0), (3.0, 4.0)]]
    assert parse_path_data("m 1 1 l 2 0 l 0 2") == [[(1.0, 1.0), (3.0, 1.0), (3.0, 3.0)]]


def test_horizontal_vertical_and_implicit_lineto():
    assert parse_path_data("M0,0 H2 V3 h-1 v-1") == [[(0.0, 0.0), (2.0, 0.0), (2.0, 3.0), (1.0, 3.0), (1.0, 2.0)]]
    assert parse_path_data("M 0 0 1 1 2 0") == [[(0.0, 0.0), (1.0, 1.0), (2.0, 0.0)]]


def test_curves_end_where_they_should():
    cubic = parse_path_data("M 0 0 C 0 1 1 1 1 0")[0]
    assert cubic[0] == (0.0, 0.0) and cubic[-1] == pytest.approx((1.0, 0.0))
    assert max(y for _, y in cubic) == pytest.approx(0.75, abs=0.01)  # a real bulge, not a straight line
    quadratic = parse_path_data("M 0 0 q 1 2 2 0")[0]
    assert quadratic[-1] == pytest.approx((2.0, 0.0))


def test_close_returns_to_the_start_and_new_moves_start_new_subpaths():
    subpaths = parse_path_data("M 0 0 L 1 0 L 1 1 Z M 5 5 L 6 5")
    assert subpaths[0][-1] == (0.0, 0.0)
    assert subpaths[1] == [(5.0, 5.0), (6.0, 5.0)]


def test_exponents_and_packed_numbers():
    assert parse_path_data("M1e1-2L.5.5") == [[(10.0, -2.0), (0.5, 0.5)]]


@pytest.mark.parametrize(
    "bad",
    ["", "L 1 1", "M 0", "M 0 0 X 1 1", "M 0 0 L 1", "M nan 0 L 1 1", "M 0 0 L 1e999 1", None, 42],
)
def test_invalid_path_data_is_rejected(bad):
    assert parse_path_data(bad) is None


def test_limits():
    assert parse_path_data("M 0 0" + " L 1 1" * (MAX_PATH_COMMANDS + 5)) is None
    assert parse_path_data("M 0 0 " + "L 1 1 " * 10) is not None


def test_partial_drawing_follows_length():
    subpaths = [[(0.0, 0.0), (4.0, 0.0)], [(0.0, 1.0), (0.0, 5.0)]]
    assert polyline_length(subpaths) == 8.0
    assert partial_subpaths(subpaths, 0.0) == []
    assert partial_subpaths(subpaths, 1.0) == subpaths
    half = partial_subpaths(subpaths, 0.25)
    assert half == [[(0.0, 0.0), (2.0, 0.0)]]
    three_quarters = partial_subpaths(subpaths, 0.75)
    assert three_quarters[0] == subpaths[0]
    assert three_quarters[1][-1] == pytest.approx((0.0, 3.0))
    assert math.isclose(polyline_length(three_quarters), 6.0)
