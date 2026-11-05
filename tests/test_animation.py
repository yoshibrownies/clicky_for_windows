import pytest

from clicky.animation import (
    MAX_FLIGHT_SECONDS,
    MIN_FLIGHT_SECONDS,
    Flight,
    arc_control_point,
    ease_in_out,
    flight_duration_seconds,
    quadratic_bezier,
)


def test_ease_in_out_endpoints_midpoint_and_clamping():
    assert ease_in_out(0) == 0
    assert ease_in_out(1) == 1
    assert ease_in_out(0.5) == pytest.approx(0.5)
    assert ease_in_out(-3) == 0
    assert ease_in_out(7) == 1
    samples = [ease_in_out(step / 20) for step in range(21)]
    assert samples == sorted(samples)


def test_bezier_hits_endpoints():
    assert quadratic_bezier((0, 0), (50, -40), (100, 0), 0) == (0, 0)
    assert quadratic_bezier((0, 0), (50, -40), (100, 0), 1) == (100, 0)


def test_arc_bulges_upward():
    control = arc_control_point((0, 100), (200, 100))
    assert control[0] == 100
    assert control[1] < 100
    middle = quadratic_bezier((0, 100), control, (200, 100), 0.5)
    assert middle[1] < 100


def test_duration_is_clamped():
    assert flight_duration_seconds((0, 0), (1, 1)) == MIN_FLIGHT_SECONDS
    assert flight_duration_seconds((0, 0), (100000, 0)) == MAX_FLIGHT_SECONDS


def test_flight_starts_and_lands_exactly():
    flight = Flight((10, 20), (900, 400), started_at=5.0)
    assert flight.position_at(5.0) == pytest.approx((10, 20))
    assert not flight.is_finished(5.1)
    landing_time = 5.0 + flight.duration
    assert flight.is_finished(landing_time)
    assert flight.position_at(landing_time + 1) == pytest.approx((900, 400))
