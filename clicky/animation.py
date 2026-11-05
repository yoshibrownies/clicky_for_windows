"""Pure maths for the buddy's flight: a quadratic bezier arc with ease-in-out timing."""

from __future__ import annotations

import math

Point = tuple[float, float]

MIN_FLIGHT_SECONDS = 0.45
MAX_FLIGHT_SECONDS = 1.1
FLIGHT_PIXELS_PER_SECOND = 1600.0
ARC_LIFT_RATIO = 0.22


def ease_in_out(progress: float) -> float:
    """Cubic ease-in-out on 0..1 (clamped)."""
    progress = min(1.0, max(0.0, progress))
    if progress < 0.5:
        return 4 * progress**3
    return 1 - (-2 * progress + 2) ** 3 / 2


def quadratic_bezier(start: Point, control: Point, end: Point, progress: float) -> Point:
    remaining = 1 - progress
    x = remaining * remaining * start[0] + 2 * remaining * progress * control[0] + progress * progress * end[0]
    y = remaining * remaining * start[1] + 2 * remaining * progress * control[1] + progress * progress * end[1]
    return x, y


def arc_control_point(start: Point, end: Point) -> Point:
    """Control point above the midpoint so the flight curves upward like a thrown ball."""
    distance = math.dist(start, end)
    middle_x = (start[0] + end[0]) / 2
    middle_y = (start[1] + end[1]) / 2
    return middle_x, middle_y - distance * ARC_LIFT_RATIO


def flight_duration_seconds(start: Point, end: Point) -> float:
    return min(MAX_FLIGHT_SECONDS, max(MIN_FLIGHT_SECONDS, math.dist(start, end) / FLIGHT_PIXELS_PER_SECOND))


class Flight:
    """One flight from start to end, sampled by elapsed time."""

    def __init__(self, start: Point, end: Point, started_at: float) -> None:
        self.start = start
        self.end = end
        self.control = arc_control_point(start, end)
        self.started_at = started_at
        self.duration = flight_duration_seconds(start, end)

    def position_at(self, now: float) -> Point:
        progress = (now - self.started_at) / self.duration
        return quadratic_bezier(self.start, self.control, self.end, ease_in_out(progress))

    def is_finished(self, now: float) -> bool:
        return now - self.started_at >= self.duration
