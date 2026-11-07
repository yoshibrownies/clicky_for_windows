"""SVG-style path data for drawn illustrations: a small whitelisted parser (pure Python, no Qt, never raises).

Supports M L H V C Q Z, absolute (upper case) and relative (lower case), with implicit repeats. Curves are flattened
into points so a figure can be drawn a fraction at a time (`partial_subpaths`): outlines sketch themselves in.
"""

from __future__ import annotations

import math
import re

MAX_PATH_LENGTH = 2000
MAX_PATH_COMMANDS = 200
CURVE_SEGMENTS = 12
MAX_COORDINATE = 1e6

Point = tuple[float, float]
Subpaths = list[list[Point]]

_TOKEN_PATTERN = re.compile(r"[MLHVCQZmlhvcqz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|[\s,]+|.")
_ARGUMENT_COUNTS = {"M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "Q": 4, "Z": 0}


def _tokenize(text: str) -> list[str | float] | None:
    tokens: list[str | float] = []
    for match in _TOKEN_PATTERN.finditer(text):
        token = match.group(0)
        if token.strip(" \t\r\n,") == "":
            continue
        if token in "MLHVCQZmlhvcqz" and len(token) == 1:
            tokens.append(token)
            continue
        try:
            number = float(token)
        except ValueError:
            return None
        if not math.isfinite(number) or abs(number) > MAX_COORDINATE:
            return None
        tokens.append(number)
    return tokens


def _cubic(p0: Point, p1: Point, p2: Point, p3: Point) -> list[Point]:
    points = []
    for step in range(1, CURVE_SEGMENTS + 1):
        t = step / CURVE_SEGMENTS
        u = 1 - t
        points.append(
            (
                u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1],
            )
        )
    return points


def _quadratic(p0: Point, p1: Point, p2: Point) -> list[Point]:
    points = []
    for step in range(1, CURVE_SEGMENTS + 1):
        t = step / CURVE_SEGMENTS
        u = 1 - t
        points.append(
            (u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0], u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1])
        )
    return points


def parse_path_data(data) -> Subpaths | None:
    """Path data → subpaths of points (curves flattened). None if anything is invalid or over the limits."""
    if not isinstance(data, str) or not data.strip() or len(data) > MAX_PATH_LENGTH:
        return None
    tokens = _tokenize(data)
    if not tokens or not isinstance(tokens[0], str) or tokens[0] not in "Mm":
        return None

    subpaths: Subpaths = []
    current: list[Point] = []
    position: Point = (0.0, 0.0)
    subpath_start: Point = (0.0, 0.0)
    command_count = 0
    index = 0
    command = ""
    while index < len(tokens):
        token = tokens[index]
        if isinstance(token, str):
            command = token
            index += 1
        elif command in ("", "Z", "z"):
            return None  # numbers with no command to take them
        upper = command.upper()
        relative = command.islower()
        count = _ARGUMENT_COUNTS[upper]
        arguments = tokens[index : index + count]
        if len(arguments) < count or any(isinstance(argument, str) for argument in arguments):
            return None
        index += count
        command_count += 1
        if command_count > MAX_PATH_COMMANDS:
            return None
        numbers = [float(argument) for argument in arguments]
        origin = position if relative else (0.0, 0.0)

        def absolute(x: float, y: float, origin: Point = origin) -> Point:
            return (origin[0] + x, origin[1] + y)

        if upper == "M":
            if len(current) > 1:
                subpaths.append(current)
            position = absolute(numbers[0], numbers[1])
            subpath_start = position
            current = [position]
            command = "l" if relative else "L"  # extra pairs after a move are line-tos
        elif upper == "L":
            position = absolute(numbers[0], numbers[1])
            current.append(position)
        elif upper == "H":
            position = (position[0] + numbers[0] if relative else numbers[0], position[1])
            current.append(position)
        elif upper == "V":
            position = (position[0], position[1] + numbers[0] if relative else numbers[0])
            current.append(position)
        elif upper == "C":
            control_1 = absolute(numbers[0], numbers[1])
            control_2 = absolute(numbers[2], numbers[3])
            end = absolute(numbers[4], numbers[5])
            current.extend(_cubic(position, control_1, control_2, end))
            position = end
        elif upper == "Q":
            control = absolute(numbers[0], numbers[1])
            end = absolute(numbers[2], numbers[3])
            current.extend(_quadratic(position, control, end))
            position = end
        elif upper == "Z":
            if current and current[-1] != subpath_start:
                current.append(subpath_start)
            if len(current) > 1:
                subpaths.append(current)
            position = subpath_start
            current = [position]
    if len(current) > 1:
        subpaths.append(current)
    return subpaths or None


def polyline_length(subpaths: Subpaths) -> float:
    return sum(math.dist(a, b) for points in subpaths for a, b in zip(points, points[1:], strict=False))


def partial_subpaths(subpaths: Subpaths, fraction: float) -> Subpaths:
    """The first `fraction` of the outline by length, cutting the last segment where the pen has got to."""
    if fraction >= 1.0:
        return subpaths
    budget = max(0.0, fraction) * polyline_length(subpaths)
    if budget <= 0:
        return []
    drawn: Subpaths = []
    for points in subpaths:
        kept = [points[0]]
        for a, b in zip(points, points[1:], strict=False):
            segment = math.dist(a, b)
            if segment <= budget:
                kept.append(b)
                budget -= segment
                continue
            share = budget / segment if segment > 0 else 0.0
            kept.append((a[0] + (b[0] - a[0]) * share, a[1] + (b[1] - a[1]) * share))
            budget = 0.0
            break
        if len(kept) > 1:
            drawn.append(kept)
        if budget <= 0:
            break
    return drawn
