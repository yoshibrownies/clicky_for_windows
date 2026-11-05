import itertools

import pytest

from clicky.diagram import MAX_EDGES, MAX_NODES, layout_diagram, parse_diagram


def boxes_overlap(first, second) -> bool:
    ax, ay, aw, ah = first
    bx, by, bw, bh = second
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def test_chain_parses_in_order():
    diagram = parse_diagram("Input -> Process -> Output")
    assert diagram.nodes == ("Input", "Process", "Output")
    assert diagram.edges == ((0, 1), (1, 2))


def test_branches_reuse_nodes_case_insensitively():
    diagram = parse_diagram("browser -> server; Server -> database; server -> cache")
    assert diagram.nodes == ("browser", "server", "database", "cache")
    assert set(diagram.edges) == {(0, 1), (1, 2), (1, 3)}


def test_self_loops_duplicates_and_empty_labels_are_dropped():
    diagram = parse_diagram("A -> A; A -> B; A -> B;  -> C; B -> ")
    assert diagram.nodes == ("A", "B")
    assert diagram.edges == ((0, 1),)


def test_limits_and_label_truncation():
    spec = "; ".join(f"node{index} -> node{index + 1}" for index in range(20))
    diagram = parse_diagram(spec)
    assert len(diagram.nodes) == MAX_NODES
    assert len(diagram.edges) <= MAX_EDGES
    long_label = parse_diagram("x" * 60 + " -> y").nodes[0]
    assert len(long_label) <= 24


def test_cycles_do_not_hang_and_get_a_layout():
    diagram = parse_diagram("A -> B -> C -> A")
    layout = layout_diagram(diagram, 300, 200)
    assert len(layout.boxes) == 3


def test_chain_lays_out_left_to_right_inside_bounds():
    layout = layout_diagram(parse_diagram("one -> two -> three"), 300, 160)
    assert layout.horizontal
    xs = [layout.boxes[index][0] for index in range(3)]
    assert xs == sorted(xs) and len(set(xs)) == 3


def test_branch_children_share_a_layer_without_overlapping():
    layout = layout_diagram(parse_diagram("hub -> left; hub -> right; hub -> middle"), 300, 200)
    child_boxes = [layout.boxes[index] for index in (1, 2, 3)]
    assert len({box[0] for box in child_boxes}) == 1
    for first, second in itertools.combinations(child_boxes, 2):
        assert not boxes_overlap(first, second)


@pytest.mark.parametrize("spec", ["a -> b -> c -> d -> e -> f -> g -> h", "a -> b; a -> c; c -> d; b -> d"])
@pytest.mark.parametrize("size", [(300, 200), (180, 400)])
def test_every_box_fits_and_none_overlap(spec, size):
    width, height = size
    layout = layout_diagram(parse_diagram(spec), width, height)
    for x, y, box_width, box_height in layout.boxes.values():
        assert x >= 0 and y >= 0 and x + box_width <= width + 0.01 and y + box_height <= height + 0.01
        assert box_width > 10 and box_height > 10
    for first, second in itertools.combinations(layout.boxes.values(), 2):
        assert not boxes_overlap(first, second)


def test_long_chain_in_narrow_space_switches_to_top_to_bottom():
    layout = layout_diagram(parse_diagram("a -> b -> c -> d -> e -> f"), 180, 400)
    assert not layout.horizontal


def test_empty_spec_gives_empty_layout():
    assert layout_diagram(parse_diagram(""), 300, 200).boxes == {}
