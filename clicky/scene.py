"""Clicky's animation language: a JSON scene the model writes, evaluated frame by frame (pure, no Qt).

A scene has a world coordinate system (y points up), optional axes, objects and captions. Every number on an object
can be a constant, a formula in t (see expressions.py) or keyframes [[time, value], ...]; text and colour can be
stepped keyframes. Anything invalid is skipped; a scene with nothing drawable is rejected (None). Nothing here can
raise for bad model output.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field

from clicky.expressions import compile_formula
from clicky.icons import icon_subpaths
from clicky.paths import Subpaths, parse_path_data, partial_subpaths

MAX_SCENE_TEXT_LENGTH = 20_000
MAX_OBJECTS = 40
MAX_CAPTIONS = 8
MAX_KEYFRAMES = 50
MIN_DURATION = 1.0
MAX_DURATION = 30.0
DEFAULT_DURATION = 8.0
DEFAULT_WORLD = (0.0, 10.0, 0.0, 10.0)
FADE_SECONDS = 0.25
CAPTION_FADE_SECONDS = 0.3
TRAIL_SAMPLES = 30
PLOT_SAMPLES = 60
# Per-frame cost cap: plots and trails evaluate formulas dozens of times per frame, at 60 fps on the GUI thread.
MAX_PLOTS = 6
MAX_TRAILS = 6
MAX_TITLE_LENGTH = 60
MAX_TEXT_LENGTH = 80
MAX_LABEL_LENGTH = 30

PALETTE = ("blue", "red", "green", "orange", "purple", "teal", "gray", "black", "yellow")
DEFAULT_COLORS = {
    "circle": "blue",
    "point": "blue",
    "rect": "blue",
    "line": "gray",
    "arrow": "red",
    "text": "black",
    "plot": "green",
    "path": "black",
    "icon": "black",
}
FILL_CHOICES = (*PALETTE, "none")
PIVOTS = ("bottom-left", "bottom-right", "center")
FILLABLE_KINDS = ("rect", "circle", "path", "icon")
REQUIRED_NUMBERS = {
    "circle": ("x", "y"),
    "point": ("x", "y"),
    "rect": ("x", "y", "w", "h"),
    "line": ("x1", "y1", "x2", "y2"),
    "arrow": ("x", "y", "dx", "dy"),
    "text": ("x", "y"),
    "plot": ("from", "to"),
    "path": ("x", "y"),
    "icon": ("x", "y"),
}
# Paths and icons keep their shape: their sizes are in the y axis's units, and the painter scales them uniformly.
OPTIONAL_NUMBERS = {
    "circle": {"r": 10.0},
    "point": {"r": 4.0},
    "text": {"size": 15.0},
    "rect": {"rotate": 0.0},
    "path": {"scale": 1.0, "rotate": 0.0, "draw": 1.0},
    "icon": {"size": 1.0, "rotate": 0.0, "draw": 1.0},
}

NumberValue = Callable[[float, float], "float | None"]


def _is_number(value) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and abs(value) <= 1e9
    except OverflowError:  # a 400-digit JSON integer
        return False


def _number_property(raw) -> NumberValue | None:
    """Constant, formula string or [[time, value], ...] keyframes, as a function of (t, x)."""
    if _is_number(raw):
        constant = float(raw)
        return lambda t, x: constant
    if isinstance(raw, str):
        formula = compile_formula(raw)
        return None if formula is None else formula.evaluate
    if isinstance(raw, list) and 0 < len(raw) <= MAX_KEYFRAMES:
        keyframes: list[tuple[float, float]] = []
        for entry in raw:
            if not (isinstance(entry, list) and len(entry) == 2 and _is_number(entry[0]) and _is_number(entry[1])):
                return None
            keyframes.append((float(entry[0]), float(entry[1])))
        keyframes.sort(key=lambda pair: pair[0])

        def interpolate(t: float, x: float = 0.0) -> float:
            if t <= keyframes[0][0]:
                return keyframes[0][1]
            for (time_a, value_a), (time_b, value_b) in zip(keyframes, keyframes[1:], strict=False):
                if t <= time_b:
                    span = time_b - time_a
                    return value_b if span <= 0 else value_a + (value_b - value_a) * (t - time_a) / span
            return keyframes[-1][1]

        return interpolate
    return None


def _stepped_text_property(raw, max_length: int, allowed: tuple[str, ...] | None = None):
    """String or [[time, string], ...] (stepped). Returns a function of t, or None if invalid."""

    def clean(value: str) -> str | None:
        value = " ".join(value.split())[:max_length]
        if allowed is not None:
            value = value.lower()
            return value if value in allowed else None
        return value

    if isinstance(raw, str):
        cleaned = clean(raw)
        return None if cleaned is None else (lambda t: cleaned)
    if isinstance(raw, list) and 0 < len(raw) <= MAX_KEYFRAMES:
        steps: list[tuple[float, str]] = []
        for entry in raw:
            if not (isinstance(entry, list) and len(entry) == 2 and _is_number(entry[0]) and isinstance(entry[1], str)):
                return None
            cleaned = clean(entry[1])
            if cleaned is None:
                return None
            steps.append((float(entry[0]), cleaned))
        steps.sort(key=lambda pair: pair[0])

        def current(t: float) -> str:
            value = steps[0][1]
            for time, text in steps:
                if t >= time:
                    value = text
            return value

        return current
    return None


@dataclass
class SceneObject:
    kind: str
    numbers: dict[str, NumberValue]
    color: Callable[[float], str]
    text: Callable[[float], str] | None = None
    label: str = ""
    trail: bool = False
    dashed: bool = False
    start: float = 0.0
    end: float | None = None
    plot_function: NumberValue | None = None
    subpaths: Subpaths | None = None  # path and icon outlines, untransformed
    fill: Callable[[float], str] | None = None
    pivot: str = "bottom-left"
    opacity: NumberValue | None = None


@dataclass
class DrawItem:
    kind: str
    alpha: float
    values: dict[str, float]
    color: str
    text: str = ""
    label: str = ""
    dashed: bool = False
    trail: list[tuple[float, float]] = field(default_factory=list)
    segments: list[list[tuple[float, float]]] = field(default_factory=list)
    fill: str = ""  # a palette colour, "none", or "" for the kind's usual look
    pivot: str = "bottom-left"


@dataclass
class Scene:
    title: str
    duration: float
    world: tuple[float, float, float, float]
    axes: tuple[str, str] | None
    objects: list[SceneObject]
    captions: list[tuple[float, str]]

    def caption_at(self, t: float) -> tuple[str, float] | None:
        current = None
        for start, text in self.captions:
            if t >= start:
                current = (text, min(1.0, (t - start) / CAPTION_FADE_SECONDS))
        return current

    def has_label(self, label: str) -> bool:
        """Whether an object is called `label` (its label, or a text object's text at the start or end)."""
        wanted = label.casefold().strip()
        for scene_object in self.objects:
            texts = [scene_object.label]
            if scene_object.text is not None:
                texts += [scene_object.text(0.0), scene_object.text(self.duration)]
            if wanted in (text.casefold().strip() for text in texts):
                return True
        return False

    def frame(self, t: float) -> list[DrawItem]:
        items: list[DrawItem] = []
        for scene_object in self.objects:
            drawn = _draw_object(scene_object, t)
            if drawn is not None:
                items.append(drawn)
        return items


def _visibility(scene_object: SceneObject, t: float) -> float:
    if t < scene_object.start or (scene_object.end is not None and t > scene_object.end):
        return 0.0
    alpha = 1.0
    if scene_object.start > 0:
        alpha = min(alpha, (t - scene_object.start) / FADE_SECONDS)
    if scene_object.end is not None:
        alpha = min(alpha, (scene_object.end - t) / FADE_SECONDS)
    return max(0.0, min(1.0, alpha))


def _draw_object(scene_object: SceneObject, t: float) -> DrawItem | None:
    alpha = _visibility(scene_object, t)
    if scene_object.opacity is not None:
        opacity = scene_object.opacity(t, 0.0)
        alpha *= 0.0 if opacity is None else max(0.0, min(1.0, opacity))
    if alpha <= 0:
        return None
    values: dict[str, float] = {}
    for name, value_function in scene_object.numbers.items():
        value = value_function(t, 0.0)
        if value is None:
            return None  # a formula failed this frame: hide rather than draw garbage
        values[name] = value
    item = DrawItem(
        kind=scene_object.kind,
        alpha=alpha,
        values=values,
        color=scene_object.color(t),
        text=scene_object.text(t) if scene_object.text else "",
        label=scene_object.label,
        dashed=scene_object.dashed,
        fill=scene_object.fill(t) if scene_object.fill else "",
        pivot=scene_object.pivot,
    )
    if scene_object.subpaths is not None:
        item.segments = partial_subpaths(scene_object.subpaths, max(0.0, min(1.0, values.get("draw", 1.0))))
    if scene_object.trail and "x" in scene_object.numbers and "y" in scene_object.numbers:
        trail_start = max(0.0, scene_object.start)
        for index in range(TRAIL_SAMPLES + 1):
            sample_time = trail_start + (t - trail_start) * index / TRAIL_SAMPLES
            x_value = scene_object.numbers["x"](sample_time, 0.0)
            y_value = scene_object.numbers["y"](sample_time, 0.0)
            if x_value is not None and y_value is not None:
                item.trail.append((x_value, y_value))
    if scene_object.kind == "plot" and scene_object.plot_function is not None:
        low, high = values["from"], values["to"]
        if high > low:
            segment: list[tuple[float, float]] = []
            for index in range(PLOT_SAMPLES + 1):
                x_value = low + (high - low) * index / PLOT_SAMPLES
                y_value = scene_object.plot_function(t, x_value)
                if y_value is None:
                    if len(segment) > 1:
                        item.segments.append(segment)
                    segment = []
                else:
                    segment.append((x_value, y_value))
            if len(segment) > 1:
                item.segments.append(segment)
    return item


def _parse_object(raw) -> SceneObject | None:
    if not isinstance(raw, dict):
        return None
    kind = raw.get("type")
    if not isinstance(kind, str) or kind not in REQUIRED_NUMBERS:
        return None
    numbers: dict[str, NumberValue] = {}
    for name in REQUIRED_NUMBERS[kind]:
        value_function = _number_property(raw.get(name))
        if value_function is None:
            return None
        numbers[name] = value_function
    for name, default in OPTIONAL_NUMBERS.get(kind, {}).items():
        value_function = _number_property(raw[name]) if name in raw else None
        numbers[name] = value_function or (lambda t, x, default=default: default)

    default_color = DEFAULT_COLORS[kind]
    color = _stepped_text_property(raw.get("color", default_color), 12, PALETTE) or (lambda t: default_color)
    text = None
    if kind == "text":
        text = _stepped_text_property(raw.get("text"), MAX_TEXT_LENGTH)
        if text is None:
            return None
    subpaths = None
    if kind == "path":
        subpaths = parse_path_data(raw.get("d"))
        if subpaths is None:
            return None
    elif kind == "icon":
        subpaths = icon_subpaths(raw.get("name"))
        if subpaths is None:
            return None
    fill = _stepped_text_property(raw["fill"], 12, FILL_CHOICES) if kind in FILLABLE_KINDS and "fill" in raw else None
    pivot = raw.get("pivot") if raw.get("pivot") in PIVOTS else "bottom-left"
    opacity = _number_property(raw["opacity"]) if "opacity" in raw else None
    plot_function = None
    if kind == "plot":
        formula = compile_formula(raw.get("fn")) if isinstance(raw.get("fn"), str) else None
        if formula is None:
            return None
        plot_function = lambda t, x, formula=formula: formula.evaluate(t, x)  # noqa: E731
    start = float(raw["start"]) if _is_number(raw.get("start")) else 0.0
    end = float(raw["end"]) if _is_number(raw.get("end")) else None
    if end is not None and end <= start:
        end = None
    label = " ".join(str(raw["label"]).split())[:MAX_LABEL_LENGTH] if isinstance(raw.get("label"), str) else ""
    return SceneObject(
        kind=kind,
        numbers=numbers,
        color=color,
        text=text,
        label=label,
        trail=raw.get("trail") is True,
        dashed=raw.get("dashed") is True,
        start=max(0.0, start),
        end=end,
        plot_function=plot_function,
        subpaths=subpaths,
        fill=fill,
        pivot=pivot,
        opacity=opacity,
    )


def _parse_range(raw) -> tuple[float, float] | None:
    if isinstance(raw, list) and len(raw) == 2 and all(_is_number(value) for value in raw) and raw[0] < raw[1]:
        return float(raw[0]), float(raw[1])
    return None


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1 :] if first_newline != -1 else ""
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip()


def parse_scene(text: str) -> Scene | None:
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_SCENE_TEXT_LENGTH:
        return None
    try:
        data = json.loads(_strip_code_fence(text))
    except (ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("objects"), list):
        return None

    objects = [parsed for parsed in (_parse_object(raw) for raw in data["objects"][: MAX_OBJECTS * 3]) if parsed]
    objects = objects[:MAX_OBJECTS]
    plots_kept = 0
    trails_kept = 0
    capped_objects: list[SceneObject] = []
    for scene_object in objects:
        if scene_object.kind == "plot":
            if plots_kept >= MAX_PLOTS:
                continue
            plots_kept += 1
        if scene_object.trail:
            if trails_kept >= MAX_TRAILS:
                scene_object.trail = False
            else:
                trails_kept += 1
        capped_objects.append(scene_object)
    objects = capped_objects
    if not objects:
        return None

    duration = float(data["duration"]) if _is_number(data.get("duration")) else DEFAULT_DURATION
    duration = max(MIN_DURATION, min(MAX_DURATION, duration))

    world = DEFAULT_WORLD
    raw_world = data.get("world")
    if isinstance(raw_world, dict):
        x_range, y_range = _parse_range(raw_world.get("x")), _parse_range(raw_world.get("y"))
        if x_range and y_range:
            world = (*x_range, *y_range)

    axes = None
    raw_axes = data.get("axes")
    if isinstance(raw_axes, dict):
        x_label = raw_axes.get("x") if isinstance(raw_axes.get("x"), str) else ""
        y_label = raw_axes.get("y") if isinstance(raw_axes.get("y"), str) else ""
        axes = (x_label[:MAX_LABEL_LENGTH], y_label[:MAX_LABEL_LENGTH])

    captions: list[tuple[float, str]] = []
    if isinstance(data.get("captions"), list):
        for raw in data["captions"]:
            if isinstance(raw, dict) and _is_number(raw.get("at")) and isinstance(raw.get("text"), str):
                captions.append((max(0.0, float(raw["at"])), " ".join(raw["text"].split())[:MAX_TEXT_LENGTH]))
            if len(captions) >= MAX_CAPTIONS:
                break
    captions.sort(key=lambda pair: pair[0])

    title = " ".join(data["title"].split())[:MAX_TITLE_LENGTH] if isinstance(data.get("title"), str) else ""
    return Scene(title=title, duration=duration, world=world, axes=axes, objects=objects, captions=captions)
