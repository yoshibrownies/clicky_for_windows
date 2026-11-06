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
MAX_ANIMATIONS = 1
# Lesson-card text blocks: (limit per reply, maximum characters)
CARD_TEXT_TAGS = {"TITLE": (1, 40), "HEADING": (1, 60), "FORMULA": (3, 60), "FOLLOWUP": (3, 40), "HIGHLIGHT": (4, 40)}
MAX_NOTE_LENGTH = 80

# Any [UPPERCASE:...] tag. Known kinds become events; unknown ones are still stripped from speech.
TAG_PATTERN = re.compile(r"\[([A-Z]{2,12}):([^\[\]]*)\]")
TAG_START_PATTERN = re.compile(r"\[([A-Z]{2,12}):")
KNOWN_TAG_NAMES = frozenset({"POINT", "UNDERLINE", "CIRCLE", "NOTE", "DIAGRAM", "ANIMATE", *CARD_TEXT_TAGS})
# Animation scenes are JSON (which needs square brackets), so they live in blocks rather than inline tags:
# <scene name="roll">{...}</scene>, referenced from the speech by [ANIMATE:roll].
SCENE_BLOCK_PATTERN = re.compile(r"<scene\b([^>]*)>(.*?)</scene\s*>", re.DOTALL | re.IGNORECASE)
SCENE_NAME_PATTERN = re.compile(r"""name\s*=\s*["']([^"'<>]{1,60})["']""", re.IGNORECASE)
UNFINISHED_SCENE_BLOCK_PATTERN = re.compile(r"<scene\b.*$", re.DOTALL | re.IGNORECASE)
PARTIAL_SCENE_OPENING_AT_END_PATTERN = re.compile(r"<(?:s(?:c(?:e(?:n(?:e)?)?)?)?)?$", re.IGNORECASE)
# The start of a tag still being streamed at the very end: "[", "[NO", "[NOTE".
PARTIAL_TAG_START_AT_END_PATTERN = re.compile(r"\[[A-Z]*$")


@dataclass(frozen=True)
class _FoundTag:
    start: int
    end: int
    name: str
    body: str
    closed: bool


def find_tags(text: str) -> list[_FoundTag]:
    """Locate tags. Known kinds may contain brackets (a note like "list[0] is first"), matched by depth.

    A known tag with no closing bracket runs to the end of the text, so it is never spoken.
    """
    found: list[_FoundTag] = []
    search_from = 0
    while True:
        match = TAG_START_PATTERN.search(text, search_from)
        if match is None:
            return found
        name, body_start = match.group(1), match.end()
        if name in KNOWN_TAG_NAMES:
            depth = 0
            close_index = -1
            for index in range(body_start, len(text)):
                character = text[index]
                if character == "[":
                    depth += 1
                elif character == "]":
                    if depth == 0:
                        close_index = index
                        break
                    depth -= 1
            if close_index == -1:
                found.append(_FoundTag(match.start(), len(text), name, text[body_start:], closed=False))
                return found
        else:
            close_index = text.find("]", body_start)
            next_open = text.find("[", body_start)
            if close_index == -1 or (next_open != -1 and next_open < close_index):
                search_from = match.end()
                continue
        found.append(_FoundTag(match.start(), close_index + 1, name, text[body_start:close_index], closed=True))
        search_from = close_index + 1


def extract_scene_blocks(text: str) -> tuple[str, dict[str, str]]:
    """Remove <scene> blocks (and a half-streamed one at the end); return the remaining text and name -> JSON."""
    scenes: dict[str, str] = {}

    def keep(match: re.Match) -> str:
        # Any complete block is removed from speech; it only becomes an animation if it carries a name.
        name_match = SCENE_NAME_PATTERN.search(match.group(1))
        if name_match:
            scenes.setdefault(name_match.group(1).strip(), match.group(2).strip())
        return " "

    without_blocks = SCENE_BLOCK_PATTERN.sub(keep, text)
    without_blocks = UNFINISHED_SCENE_BLOCK_PATTERN.sub(" ", without_blocks)
    return PARTIAL_SCENE_OPENING_AT_END_PATTERN.sub("", without_blocks), scenes


def visible_text(partial_text: str) -> str:
    """Text for the speech bubble while a reply streams in: no tags, not even a half-written last one."""
    partial_text, _ = extract_scene_blocks(partial_text)
    pieces: list[str] = []
    cursor = 0
    for tag in find_tags(partial_text):
        pieces.append(partial_text[cursor : tag.start])
        cursor = tag.end
    pieces.append(partial_text[cursor:])
    return clean_spoken_text(PARTIAL_TAG_START_AT_END_PATTERN.sub("", " ".join(pieces)))


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
    if name in CARD_TEXT_TAGS:
        maximum_length = CARD_TEXT_TAGS[name][1]
        text = " ".join(body.split())
        if not text:
            return None
        if len(text) > maximum_length:
            text = text[: maximum_length - 1].rstrip() + "…"
        # Follow-up questions are offered after the answer, wherever the model wrote them.
        return VisualEvent(kind=name.lower(), fraction=1.0 if name == "FOLLOWUP" else fraction, text=text)
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
    response_text, scenes = extract_scene_blocks(response_text)
    spoken_parts: list[str] = []
    spoken_length = 0
    pending: list[tuple[str, str, int]] = []
    cursor = 0
    for tag in find_tags(response_text):
        segment = response_text[cursor : tag.start]
        spoken_parts.append(segment)
        spoken_length += len(segment)
        if tag.closed:
            pending.append((tag.name, tag.body, spoken_length))
        cursor = tag.end
    spoken_parts.append(response_text[cursor:])
    raw_spoken = "".join(spoken_parts)
    total_length = len(raw_spoken.rstrip())

    limits = {
        "underline": MAX_MARKS,
        "circle": MAX_MARKS,
        "note": MAX_NOTES,
        "diagram": MAX_DIAGRAMS,
        "point": MAX_POINTS,
        "animate": MAX_ANIMATIONS,
        **{name.lower(): limit for name, (limit, _) in CARD_TEXT_TAGS.items()},
    }
    counts = {
        "marks": 0,
        "note": 0,
        "diagram": 0,
        "point": 0,
        "animate": 0,
        **{name.lower(): 0 for name in CARD_TEXT_TAGS},
    }
    events: list[VisualEvent] = []
    for name, body, offset in pending:
        fraction = 0.0 if total_length == 0 else min(1.0, max(0.0, offset / total_length))
        if name == "ANIMATE":
            scene_json = scenes.get(body.strip())
            event = VisualEvent(kind="animate", fraction=fraction, text=scene_json) if scene_json else None
        else:
            event = _parse_tag(name, body, fraction)
        if event is None:
            continue
        counter_key = "marks" if event.kind in ("underline", "circle") else event.kind
        if counts[counter_key] >= limits[event.kind]:
            continue
        counts[counter_key] += 1
        events.append(event)

    return VisualReply(spoken_text=clean_spoken_text(raw_spoken), events=tuple(events))
