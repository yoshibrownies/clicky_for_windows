"""Parses the [POINT:x,y:label:screenN] tag Claude appends to the end of each reply."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Same grammar as the macOS app: [POINT:none] | [POINT:x,y] | [POINT:x,y:label] | [POINT:x,y:label:screenN]
# The tag only counts when it is the last thing in the reply.
POINT_TAG_PATTERN = re.compile(
    r"\[POINT:(?:none|(\d+)\s*,\s*(\d+)(?::([^\]:\s][^\]:]*?))?(?::screen(\d+))?)\]\s*$"
)


@dataclass(frozen=True)
class PointingResult:
    spoken_text: str
    """The reply with the tag removed. This is what gets spoken aloud."""
    coordinate: tuple[int, int] | None
    """Pixel coordinate inside the screenshot image, or None when there is nothing to point at."""
    label: str | None
    """Short element description, "none" for [POINT:none], or None when there was no tag or label."""
    screen_number: int | None
    """1-based screenshot index when Claude points at a screen other than the cursor's."""


def parse_point_tag(response_text: str) -> PointingResult:
    match = POINT_TAG_PATTERN.search(response_text)
    if match is None:
        return PointingResult(spoken_text=response_text, coordinate=None, label=None, screen_number=None)

    spoken_text = response_text[: match.start()].strip()
    x_text, y_text, label_text, screen_text = match.groups()

    if x_text is None or y_text is None:
        return PointingResult(spoken_text=spoken_text, coordinate=None, label="none", screen_number=None)

    return PointingResult(
        spoken_text=spoken_text,
        coordinate=(int(x_text), int(y_text)),
        label=label_text.strip() if label_text else None,
        screen_number=int(screen_text) if screen_text else None,
    )
