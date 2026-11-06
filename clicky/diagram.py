"""Tiny flow diagrams for the lesson card: parse "A -> B -> C; B -> D" and lay the boxes out in layers.

Pure Python (no Qt) so it can be tested directly. Boxes are (x, y, width, height) in the drawing area.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MAX_NODES = 8
MAX_EDGES = 10
MAX_LABEL_LENGTH = 24
MIN_BOX_WIDTH = 64.0
MAX_BOX_WIDTH = 130.0
BOX_HEIGHT = 34.0
LAYER_GAP = 26.0
SIBLING_GAP = 12.0


@dataclass(frozen=True)
class Diagram:
    nodes: tuple[str, ...]
    edges: tuple[tuple[int, int], ...]


@dataclass(frozen=True)
class DiagramLayout:
    boxes: dict[int, tuple[float, float, float, float]]
    horizontal: bool  # True: layers run left to right; False: top to bottom
    back_edges: frozenset[tuple[int, int]] = frozenset()  # edges that loop back; drawn as curves


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


def layout_diagram(diagram: Diagram, width: float, height: float) -> DiagramLayout:
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

    # Layers along x (left to right) or along y (top to bottom): pick whichever gives the roomier boxes.
    h_box_width, h_layer_gap = fit(width, layer_count, LAYER_GAP, MAX_BOX_WIDTH)
    h_box_height, h_sibling_gap = fit(height, widest_layer, SIBLING_GAP, BOX_HEIGHT)
    v_box_height, v_layer_gap = fit(height, layer_count, LAYER_GAP, BOX_HEIGHT)
    v_box_width, v_sibling_gap = fit(width, widest_layer, SIBLING_GAP, MAX_BOX_WIDTH)
    horizontal_score = min(h_box_width / MIN_BOX_WIDTH, h_box_height / BOX_HEIGHT)
    vertical_score = min(v_box_width / MIN_BOX_WIDTH, v_box_height / BOX_HEIGHT)
    horizontal = h_box_width >= MIN_BOX_WIDTH or horizontal_score >= vertical_score

    boxes: dict[int, tuple[float, float, float, float]] = {}
    if horizontal:
        box_width, box_height, layer_gap, sibling_gap = h_box_width, h_box_height, h_layer_gap, h_sibling_gap
        total_width = box_width * layer_count + layer_gap * (layer_count - 1)
        start_x = (width - total_width) / 2
        for layer_index, layer in enumerate(layers):
            column_height = box_height * len(layer) + sibling_gap * (len(layer) - 1)
            start_y = (height - column_height) / 2
            x = start_x + layer_index * (box_width + layer_gap)
            for position, node in enumerate(layer):
                boxes[node] = (x, start_y + position * (box_height + sibling_gap), box_width, box_height)
    else:
        box_width, box_height, layer_gap, sibling_gap = v_box_width, v_box_height, v_layer_gap, v_sibling_gap
        total_height = box_height * layer_count + layer_gap * (layer_count - 1)
        start_y = (height - total_height) / 2
        for layer_index, layer in enumerate(layers):
            row_width = box_width * len(layer) + sibling_gap * (len(layer) - 1)
            start_x = (width - row_width) / 2
            y = start_y + layer_index * (box_height + layer_gap)
            for position, node in enumerate(layer):
                boxes[node] = (start_x + position * (box_width + sibling_gap), y, box_width, box_height)
    return DiagramLayout(boxes=boxes, horizontal=horizontal, back_edges=back_edges)
