"""Built-in general-purpose figures for illustrations (pure Python, no Qt). Kept small and topic-free on purpose:
anything specific to a subject is drawn by the model with `path`, so illustrations fit whatever is asked.

Each icon is sketched roughly in a unit box (y up) and normalised when built: its bottom centre is (0, 0) and its
longer side is 1, so a scene places it exactly with x, y and a size (its longer side in world units). Icons are
made of several short path pieces.
"""

from __future__ import annotations

import math
from functools import cache

from clicky.paths import Subpaths, parse_path_data

CIRCLE_HANDLE = 0.5523  # cubic-Bézier handle length for a quarter circle, as a fraction of the radius


def _circle(center_x: float, center_y: float, radius: float) -> str:
    k = radius * CIRCLE_HANDLE
    x, y, r = center_x, center_y, radius
    return (
        f"M {x + r} {y} C {x + r} {y + k} {x + k} {y + r} {x} {y + r} "
        f"C {x - k} {y + r} {x - r} {y + k} {x - r} {y} "
        f"C {x - r} {y - k} {x - k} {y - r} {x} {y - r} "
        f"C {x + k} {y - r} {x + r} {y - k} {x + r} {y} Z"
    )


def _gear(teeth: int = 8, outer: float = 0.45, inner: float = 0.35, center_y: float = 0.5) -> str:
    points = []
    for index in range(teeth * 4):
        angle = 2 * math.pi * index / (teeth * 4)
        radius = outer if index % 4 in (1, 2) else inner
        points.append(f"{radius * math.cos(angle):.3f} {center_y + radius * math.sin(angle):.3f}")
    return "M " + " L ".join(points) + " Z"


_ICON_PIECES: dict[str, tuple[str, ...]] = {
    "person": (
        _circle(0, 0.84, 0.13),
        "M -0.3 0 L -0.3 0.42 C -0.3 0.6 -0.18 0.66 0 0.66 C 0.18 0.66 0.3 0.6 0.3 0.42 L 0.3 0 Z",
    ),
    "head": (
        "M -0.18 0 L -0.18 0.3 C -0.4 0.4 -0.42 0.85 -0.1 0.97 C 0.15 1.04 0.38 0.9 0.38 0.65 "
        "L 0.46 0.5 L 0.38 0.46 L 0.38 0.36 C 0.38 0.28 0.3 0.25 0.18 0.25 L 0.18 0",
    ),
    "lightbulb": (
        "M -0.12 0.25 C -0.12 0.4 -0.32 0.5 -0.32 0.7 C -0.32 0.88 -0.17 1 0 1 "
        "C 0.17 1 0.32 0.88 0.32 0.7 C 0.32 0.5 0.12 0.4 0.12 0.25 Z",
        "M -0.12 0.18 L 0.12 0.18",
        "M -0.1 0.1 L 0.1 0.1",
        "M -0.05 0.02 L 0.05 0.02",
        "M -0.06 0.3 L -0.06 0.55 L 0 0.62 L 0.06 0.55 L 0.06 0.3",
    ),
    "clock": (
        _circle(0, 0.5, 0.45),
        "M 0 0.5 L 0 0.8",
        "M 0 0.5 L 0.2 0.5",
        "M 0 0.88 L 0 0.94",
        "M 0.38 0.5 L 0.44 0.5",
        "M 0 0.12 L 0 0.06",
        "M -0.38 0.5 L -0.44 0.5",
    ),
    "gear": (_gear(), _circle(0, 0.5, 0.13)),
    "eye": (
        "M -0.48 0.5 Q 0 0.86 0.48 0.5 Q 0 0.14 -0.48 0.5 Z",
        _circle(0, 0.5, 0.17),
        _circle(0, 0.5, 0.07),
    ),
    "die": (
        "M -0.32 0.1 L 0.32 0.1 Q 0.4 0.1 0.4 0.18 L 0.4 0.82 Q 0.4 0.9 0.32 0.9 L -0.32 0.9 "
        "Q -0.4 0.9 -0.4 0.82 L -0.4 0.18 Q -0.4 0.1 -0.32 0.1 Z",
        _circle(0, 0.5, 0.06),
        _circle(-0.2, 0.3, 0.06),
        _circle(0.2, 0.3, 0.06),
        _circle(-0.2, 0.7, 0.06),
        _circle(0.2, 0.7, 0.06),
    ),
    "heart": (
        "M 0 0.1 C -0.35 0.4 -0.5 0.6 -0.42 0.8 C -0.34 0.98 -0.08 0.98 0 0.78 "
        "C 0.08 0.98 0.34 0.98 0.42 0.8 C 0.5 0.6 0.35 0.4 0 0.1 Z",
    ),
}

ICON_NAMES: tuple[str, ...] = tuple(_ICON_PIECES)


def icon_subpaths(name) -> Subpaths | None:
    """The icon's normalised outline (bottom centre at 0, 0; longer side 1), or None for an unknown name."""
    if not isinstance(name, str) or name not in _ICON_PIECES:
        return None
    return _build_icon(name)


@cache
def _build_icon(name: str) -> Subpaths | None:
    subpaths: Subpaths = []
    for piece in _ICON_PIECES[name]:
        parsed = parse_path_data(piece)
        if parsed:
            subpaths.extend(parsed)
    if not subpaths:
        return None
    # Normalise to what the drawing really covers, so every figure stands exactly on its anchor (bottom centre)
    # and its longer side is 1 — however much of its sketch box the artwork happens to use.
    xs = [x for points in subpaths for x, _ in points]
    ys = [y for points in subpaths for _, y in points]
    longest = max(max(xs) - min(xs), max(ys) - min(ys)) or 1.0
    centre_x, bottom = (min(xs) + max(xs)) / 2, min(ys)
    return [[((x - centre_x) / longest, (y - bottom) / longest) for x, y in points] for points in subpaths]
