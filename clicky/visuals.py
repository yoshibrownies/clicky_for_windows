"""Parses the visual tags the model writes inline in its reply.

The model places tags where in the sentence they should appear, for example
"this word [UNDERLINE:120,340,260,362] is the variable name". Each tag becomes a VisualEvent whose `fraction`
(0..1) says how far through the spoken reply it belongs; playback progress then fires it at the right moment.
Tags never reach the voice or the speech bubble. Malformed or unknown tags are dropped, never raised.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_MARKS = 6  # underlines + circles
MAX_NOTES = 8
MAX_DIAGRAMS = 1
MAX_POINTS = 4
MAX_NOTE_LENGTH = 80

# Any [UPPERCASE:...] tag. Known kinds become events; unknown ones are still stripped from speech.
TAG_PATTERN = re.compile(r"\[([A-Z]{2,12}):([^\[\]]*)\]")
SCREEN_SUFFIX_PATTERN = re.compile(r"^screen(\d+)$")


@dataclass(frozen=True)
class VisualEvent:
    kind: str  # "point" | "underline" | "circle" | "note" | "diagram"
    fraction: float
    box: tuple[int, int, int, int] | None = None  # underline/circle, screenshot pixels, (left, top, right, bottom)
    point: tuple[int, int] | None = None  # point, screenshot pixels
    label: str = ""  # point label
    text: str = ""  # note text or diagram spec
    screen_number: int | None = None  # 1-based screenshot index; None = the cursor's screen


@dataclass(frozen=True)
class VisualReply:
    spoken_text: str
    events: tuple[VisualEvent, ...]


def _parse_integers(parts: list[str], count: int) -> list[int] | None:
    if len(parts) < count:
        return None
    try:
        return [int(part.strip()) for part in parts[:count]]
    except ValueError:
        return None


def _split_screen_suffix(body: str) -> tuple[str, int | None, bool]:
    """Split a trailing ':screenN'. Returns (rest, screen_number, is_valid)."""
    if ":" not in body:
        return body, None, True
    rest, _, last = body.rpartition(":")
    last = last.strip()
    if last.lower().startswith("screen"):
        match = SCREEN_SUFFIX_PATTERN.match(last.lower())
        if match is None:
            return body, None, False
        return rest, int(match.group(1)), True
    return body, None, True


def _parse_box_tag(kind: str, body: str, fraction: float) -> VisualEvent | None:
    coordinates_text, screen_number, valid = _split_screen_suffix(body)
    if not valid:
        return None
    numbers = _parse_integers(coordinates_text.split(","), 4)
    if numbers is None or len(coordinates_text.split(",")) != 4:
        return None
    x1, y1, x2, y2 = numbers
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))
    if right - left < 2 or min(left, top) < 0:
        return None
    if kind == "circle" and bottom - top < 2:
        return None
    return VisualEvent(kind=kind, fraction=fraction, box=(left, top, right, bottom), screen_number=screen_number)


def _parse_point_tag(body: str, fraction: float) -> VisualEvent | None:
    if body.strip().lower() == "none":
        return None
    parts = body.split(":")
    numbers = _parse_integers(parts[0].split(","), 2)
    if numbers is None or len(parts[0].split(",")) != 2 or min(numbers) < 0:
        return None
    label = ""
    screen_number = None
    for extra in parts[1:]:
        extra = extra.strip()
        match = SCREEN_SUFFIX_PATTERN.match(extra.lower())
        if match:
            screen_number = int(match.group(1))
        elif extra and not label:
            label = extra[:40]
    return VisualEvent(
        kind="point", fraction=fraction, point=(numbers[0], numbers[1]), label=label, screen_number=screen_number
    )


def _parse_tag(name: str, body: str, fraction: float) -> VisualEvent | None:
    if name in ("UNDERLINE", "CIRCLE"):
        return _parse_box_tag(name.lower(), body, fraction)
    if name == "POINT":
        return _parse_point_tag(body, fraction)
    if name == "NOTE":
        text = " ".join(body.split())
        if not text:
            return None
        if len(text) > MAX_NOTE_LENGTH:
            text = text[: MAX_NOTE_LENGTH - 1].rstrip() + "…"
        return VisualEvent(kind="note", fraction=fraction, text=text)
    if name == "DIAGRAM":
        text = " ".join(body.split())
        if "->" not in text:
            return None
        return VisualEvent(kind="diagram", fraction=fraction, text=text)
    return None


def clean_spoken_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+([.,!?;:])", r"\1", text)
    return text.strip()


def parse_visual_reply(response_text: str) -> VisualReply:
    spoken_parts: list[str] = []
    spoken_length = 0
    pending: list[tuple[str, str, int]] = []
    cursor = 0
    for match in TAG_PATTERN.finditer(response_text):
        segment = response_text[cursor : match.start()]
        spoken_parts.append(segment)
        spoken_length += len(segment)
        pending.append((match.group(1), match.group(2), spoken_length))
        cursor = match.end()
    spoken_parts.append(response_text[cursor:])
    raw_spoken = "".join(spoken_parts)
    total_length = len(raw_spoken.rstrip())

    limits = {
        "underline": MAX_MARKS,
        "circle": MAX_MARKS,
        "note": MAX_NOTES,
        "diagram": MAX_DIAGRAMS,
        "point": MAX_POINTS,
    }
    counts = {"marks": 0, "note": 0, "diagram": 0, "point": 0}
    events: list[VisualEvent] = []
    for name, body, offset in pending:
        fraction = 0.0 if total_length == 0 else min(1.0, max(0.0, offset / total_length))
        event = _parse_tag(name, body, fraction)
        if event is None:
            continue
        counter_key = "marks" if event.kind in ("underline", "circle") else event.kind
        if counts[counter_key] >= limits[event.kind]:
            continue
        counts[counter_key] += 1
        events.append(event)

    return VisualReply(spoken_text=clean_spoken_text(raw_spoken), events=tuple(events))
