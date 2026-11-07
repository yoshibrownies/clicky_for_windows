"""Tiny flow diagrams for the lesson card: parse "A -> B -> C; B -> D" and lay the boxes out in layers.

Pure Python (no Qt) so it can be tested directly. Boxes are (x, y, width, height) in the drawing area.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from clicky.handwriting import wrap_text

MAX_NODES = 8
MAX_EDGES = 10
MAX_LABEL_LENGTH = 24
MIN_BOX_WIDTH = 64.0
MAX_BOX_WIDTH = 130.0
BOX_HEIGHT = 34.0
LAYER_GAP = 26.0
SIBLING_GAP = 12.0
# Labels wrap onto up to MAX_LABEL_LINES lines; only then does the font shrink (down to 11 px from 13 px).
MAX_LABEL_LINES = 3
LABEL_LINE_HEIGHT = 17.0
LABEL_PADDING = 10.0
BOX_VERTICAL_PADDING = 12.0
MIN_FONT_SCALE = 11 / 13
FONT_SCALES = (1.0, 0.92, MIN_FONT_SCALE)
ELLIPSIS = "…"


@dataclass(frozen=True)
class Diagram:
    nodes: tuple[str, ...]
    edges: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class DiagramLayout:
    boxes: dict[int, tuple[float, float, float, float]]
    horizontal: bool  # True: layers run left to right; False: top to bottom
    back_edges: frozenset[tuple[int, int]] = frozenset()  # edges that loop back; drawn as curves
    lines: dict[int, tuple[str, ...]] = field(default_factory=dict)  # each box's label, wrapped
    font_scale: float = 1.0  # relative to the normal label font
    needed_height: float = 0.0  # height the boxes take, gaps included


def _clean_label(raw_label: str) -> str:
    label = " ".join(raw_label.split())
    if len(label) > MAX_LABEL_LENGTH:
        label = label[: MAX_LABEL_LENGTH - 1].rstrip() + "…"
    return label


def parse_diagram(spec: str) -> Diagram:
    nodes: list[str] = []
    node_index_by_key: dict[str, int] = {}
    edges: list[tuple[int, int]] = []

    def node_index(label: str) -> int | None:
        key = label.casefold()
        if key in node_index_by_key:
            return node_index_by_key[key]
        if len(nodes) >= MAX_NODES:
            return None
        node_index_by_key[key] = len(nodes)
        nodes.append(label)
        return node_index_by_key[key]

    for chain in re.split(r"[;\n]", spec):
        labels = [_clean_label(part) for part in chain.split("->")]
        if len(labels) < 2:
            continue
        for source_label, target_label in zip(labels, labels[1:], strict=False):
            if not source_label or not target_label:
                continue
            source = node_index(source_label)
            target = node_index(target_label)
            if source is None or target is None or source == target:
                continue
            if (source, target) in edges or len(edges) >= MAX_EDGES:
                continue
            edges.append((source, target))

    # Keep only nodes that ended up in an edge (a dropped edge can leave an orphan label).
    used = sorted({index for edge in edges for index in edge})
    remap = {old: new for new, old in enumerate(used)}
    return Diagram(
        nodes=tuple(nodes[index] for index in used),
        edges=tuple((remap[source], remap[target]) for source, target in edges),
    )


def find_back_edges(diagram: Diagram) -> frozenset[tuple[int, int]]:
    """Edges that close a loop, found by depth-first search in the order nodes were written."""
    outgoing: dict[int, list[int]] = {index: [] for index in range(len(diagram.nodes))}
    for source, target in diagram.edges:
        outgoing[source].append(target)
    state = [0] * len(diagram.nodes)  # 0 = unvisited, 1 = on the current path, 2 = done
    back_edges: set[tuple[int, int]] = set()
    for root in range(len(diagram.nodes)):
        if state[root]:
            continue
        stack = [(root, iter(outgoing[root]))]
        state[root] = 1
        while stack:
            node, children = stack[-1]
            child = next(children, None)
            if child is None:
                state[node] = 2
                stack.pop()
            elif state[child] == 1:
                back_edges.add((node, child))
            elif state[child] == 0:
                state[child] = 1
                stack.append((child, iter(outgoing[child])))
    return frozenset(back_edges)


def _layers(diagram: Diagram, back_edges: frozenset[tuple[int, int]] = frozenset()) -> list[list[int]]:
    """Longest-path layering over the forward edges (loops don't push nodes rightwards)."""
    node_count = len(diagram.nodes)
    forward_edges = [edge for edge in diagram.edges if edge not in back_edges]
    layer_of = [0] * node_count
    for _ in range(node_count):
        changed = False
        for source, target in forward_edges:
            candidate = layer_of[source] + 1
            if candidate > layer_of[target] and candidate < node_count:
                layer_of[target] = candidate
                changed = True
        if not changed:
            break
    used_layers = sorted(set(layer_of))
    compact = {layer: index for index, layer in enumerate(used_layers)}
    layers: list[list[int]] = [[] for _ in used_layers]
    for node in range(node_count):
        layers[compact[layer_of[node]]].append(node)
    return layers


def _elide(text: str, measure: Callable[[str], float], max_width: float) -> str:
    while text and measure(text + ELLIPSIS) > max_width:
        text = text[:-1]
    return text.rstrip() + ELLIPSIS


def layout_diagram(
    diagram: Diagram,
    width: float,
    height: float,
    measure: Callable[[str], float] | None = None,
    max_height: float | None = None,
) -> DiagramLayout:
    """Lay boxes out in layers. With `measure` (label width in px at the normal font), labels wrap onto up to three
    lines and boxes grow to hold them; the font shrinks only when wrapping isn't enough, and an ellipsis is a last
    resort. Boxes are centred in max(height, needed_height); `max_height` caps how tall the diagram may grow."""
    if not diagram.nodes:
        return DiagramLayout(boxes={}, horizontal=True)
    back_edges = find_back_edges(diagram)
    layers = _layers(diagram, back_edges)
    layer_count = len(layers)
    widest_layer = max(len(layer) for layer in layers)

    def fit(length: float, count: int, preferred_gap: float, cap: float) -> tuple[float, float]:
        """Box size and gap for `count` boxes along `length`; gaps shrink (to at most 20% of space) when tight."""
        gap = 0.0 if count == 1 else min(preferred_gap, length * 0.2 / (count - 1))
        return min(cap, (length - gap * (count - 1)) / count), gap

    def stacked(count: int, box_height: float, gap: float) -> float:
        return count * box_height + gap * (count - 1)

    # Layers along x (left to right) or along y (top to bottom): prefer whichever gives the roomier boxes.
    h_box_width, h_layer_gap = fit(width, layer_count, LAYER_GAP, MAX_BOX_WIDTH)
    h_box_height, h_sibling_gap = fit(height, widest_layer, SIBLING_GAP, BOX_HEIGHT)
    v_box_height, v_layer_gap = fit(height, layer_count, LAYER_GAP, BOX_HEIGHT)
    v_box_width, v_sibling_gap = fit(width, widest_layer, SIBLING_GAP, MAX_BOX_WIDTH)
    horizontal_score = min(h_box_width / MIN_BOX_WIDTH, h_box_height / BOX_HEIGHT)
    vertical_score = min(v_box_width / MIN_BOX_WIDTH, v_box_height / BOX_HEIGHT)
    prefer_horizontal = h_box_width >= MIN_BOX_WIDTH or horizontal_score >= vertical_score

    if measure is None:
        horizontal = prefer_horizontal
        box_width = h_box_width if horizontal else v_box_width
        box_height = h_box_height if horizontal else v_box_height
        layer_gap = h_layer_gap if horizontal else v_layer_gap
        sibling_gap = h_sibling_gap if horizontal else v_sibling_gap
        lines = {node: (label,) for node, label in enumerate(diagram.nodes)}
        font_scale = 1.0
    else:

        def wrapped(box_width: float, scale: float) -> dict[int, tuple[str, ...]]:
            available = box_width - LABEL_PADDING
            return {
                node: tuple(wrap_text(label, lambda text: measure(text) * scale, available) or [label])
                for node, label in enumerate(diagram.nodes)
            }

        def box_height_for(line_count: int, scale: float) -> float:
            return max(BOX_HEIGHT, line_count * LABEL_LINE_HEIGHT * scale + BOX_VERTICAL_PADDING)

        def total_height(horizontal: bool, box_height: float) -> float:
            if horizontal:
                return stacked(widest_layer, box_height, SIBLING_GAP)
            return stacked(layer_count, box_height, LAYER_GAP)

        chosen = None
        for scale in FONT_SCALES:
            candidates = []
            for candidate_horizontal, candidate_width in ((True, h_box_width), (False, v_box_width)):
                candidate_lines = wrapped(candidate_width, scale)
                line_count = max(len(node_lines) for node_lines in candidate_lines.values())
                candidate_height = box_height_for(line_count, scale)
                fits_cap = max_height is None or total_height(candidate_horizontal, candidate_height) <= max_height
                if line_count <= MAX_LABEL_LINES and fits_cap:
                    preference = 0 if candidate_horizontal == prefer_horizontal else 1
                    candidates.append(
                        (
                            line_count,
                            preference,
                            candidate_horizontal,
                            candidate_width,
                            candidate_height,
                            candidate_lines,
                        )
                    )
            if candidates:
                _, _, horizontal, box_width, box_height, lines = min(candidates, key=lambda item: item[:2])
                chosen = scale
                break
        if chosen is None:
            # Last resort: the smallest font, the roomier direction, at most three lines, an ellipsis on the rest.
            chosen = MIN_FONT_SCALE
            horizontal = h_box_width >= v_box_width
            box_width = h_box_width if horizontal else v_box_width

            def small_measure(text: str) -> float:
                return measure(text) * MIN_FONT_SCALE

            lines = {}
            for node, node_lines in wrapped(box_width, chosen).items():
                if len(node_lines) > MAX_LABEL_LINES:
                    rest = " ".join(node_lines[MAX_LABEL_LINES - 1 :])
                    node_lines = (
                        *node_lines[: MAX_LABEL_LINES - 1],
                        _elide(rest, small_measure, box_width - LABEL_PADDING),
                    )
                lines[node] = node_lines
            box_height = box_height_for(MAX_LABEL_LINES, chosen)
        font_scale = chosen
        layer_gap = h_layer_gap if horizontal else LAYER_GAP
        sibling_gap = SIBLING_GAP if horizontal else v_sibling_gap

    count, gap = (widest_layer, sibling_gap) if horizontal else (layer_count, layer_gap)
    needed_height = stacked(count, box_height, gap)
    if max_height is not None and needed_height > max_height:
        # Past every other step: squeeze the boxes into the cap rather than spill out of the card.
        box_height = max(1.0, (max_height - gap * (count - 1)) / count)
        needed_height = stacked(count, box_height, gap)
    area_height = max(height, needed_height)

    boxes: dict[int, tuple[float, float, float, float]] = {}
    if horizontal:
        total_width = box_width * layer_count + layer_gap * (layer_count - 1)
        start_x = (width - total_width) / 2
        for layer_index, layer in enumerate(layers):
            start_y = (area_height - stacked(len(layer), box_height, sibling_gap)) / 2
            x = start_x + layer_index * (box_width + layer_gap)
            for position, node in enumerate(layer):
                boxes[node] = (x, start_y + position * (box_height + sibling_gap), box_width, box_height)
    else:
        start_y = (area_height - stacked(layer_count, box_height, layer_gap)) / 2
        for layer_index, layer in enumerate(layers):
            row_width = box_width * len(layer) + sibling_gap * (len(layer) - 1)
            start_x = (width - row_width) / 2
            y = start_y + layer_index * (box_height + layer_gap)
            for position, node in enumerate(layer):
                boxes[node] = (start_x + position * (box_width + sibling_gap), y, box_width, box_height)
    return DiagramLayout(
        boxes=boxes,
        horizontal=horizontal,
        back_edges=back_edges,
        lines=lines,
        font_scale=font_scale,
        needed_height=needed_height,
    )
