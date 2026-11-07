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


def test_cycles_keep_reading_order_and_mark_the_back_edge():
    diagram = parse_diagram("browser -> dns -> server -> browser; server -> database")
    layout = layout_diagram(diagram, 320, 180)
    xs = {diagram.nodes[index]: box[0] for index, box in layout.boxes.items()}
    assert xs["browser"] < xs["dns"] < xs["server"]
    assert layout.back_edges == frozenset({(diagram.nodes.index("server"), diagram.nodes.index("browser"))})


def test_acyclic_diagram_has_no_back_edges():
    assert layout_diagram(parse_diagram("a -> b -> c"), 300, 150).back_edges == frozenset()


# ---------- labels wrap and fit instead of being cut off ----------


def fake_measure(text: str) -> float:
    return 7.0 * len(text)


def test_long_labels_wrap_instead_of_being_cut():
    from clicky.diagram import LABEL_LINE_HEIGHT, LABEL_PADDING

    label = "short term memory store"
    diagram = parse_diagram(" -> ".join(f"{label} {index}" for index in range(5)))
    layout = layout_diagram(diagram, 388, 174, measure=fake_measure)
    for node, name in enumerate(diagram.nodes):
        lines = layout.lines[node]
        assert " ".join(lines) == name and "…" not in name
        _, _, width, height = layout.boxes[node]
        assert all(fake_measure(line) * layout.font_scale <= width - LABEL_PADDING + 1e-6 for line in lines)
        assert height >= len(lines) * LABEL_LINE_HEIGHT * layout.font_scale


def test_one_long_word_breaks_inside_the_word():
    diagram = parse_diagram("electroencephalography -> b -> c -> d")
    layout = layout_diagram(diagram, 388, 174, measure=fake_measure)
    assert "".join(layout.lines[0]) == "electroencephalography"


def test_short_labels_stay_one_line_at_full_size():
    layout = layout_diagram(parse_diagram("start -> loop -> end"), 388, 174, measure=fake_measure)
    assert layout.font_scale == 1.0
    assert all(len(lines) == 1 for lines in layout.lines.values())


def test_needed_height_grows_with_wrapped_boxes():
    short = layout_diagram(parse_diagram("a -> b -> c -> d -> e"), 388, 174, measure=fake_measure)
    long = layout_diagram(
        parse_diagram("quite a long label a -> quite a long label b -> quite a long label c -> quite a long label d"),
        388,
        174,
        measure=fake_measure,
    )
    assert long.needed_height > short.needed_height


def test_eight_boxes_in_a_layer_fit():
    children = "; ".join(f"root -> child number {index}xx" for index in range(7))
    diagram = parse_diagram(children)
    layout = layout_diagram(diagram, 388, 174, measure=fake_measure)
    for node, name in enumerate(diagram.nodes):
        assert "".join(layout.lines[node]).replace(" ", "") == name.replace(" ", "")
    assert layout.needed_height > 0


def test_without_a_measure_layout_is_one_line_per_box():
    layout = layout_diagram(parse_diagram("a -> b"), 388, 174)
    assert layout.lines == {0: ("a",), 1: ("b",)} and layout.font_scale == 1.0


def _text_fits_and_boxes_stay_apart(layout, area_height):
    from clicky.diagram import LABEL_LINE_HEIGHT

    boxes = list(layout.boxes.values())
    for node, (_x, y, _width, height) in layout.boxes.items():
        assert len(layout.lines[node]) * LABEL_LINE_HEIGHT * layout.font_scale <= height + 1e-6, node
        assert y >= -1e-6 and y + height <= area_height + 1e-6
    for first, second in itertools.combinations(boxes, 2):
        assert not boxes_overlap(first, second)


def test_a_squeezed_long_chain_never_spills_text_out_of_its_boxes():
    diagram = parse_diagram(" -> ".join(f"long stage name number {index}" for index in range(8)))
    layout = layout_diagram(diagram, 384, 174, measure=fake_measure, max_height=324)
    assert layout.needed_height <= 324
    _text_fits_and_boxes_stay_apart(layout, max(174, layout.needed_height))


def test_eight_children_with_long_labels_never_overlap():
    diagram = parse_diagram("; ".join(f"root -> a fairly long child label {index}" for index in range(7)))
    layout = layout_diagram(diagram, 384, 174, measure=fake_measure, max_height=324)
    _text_fits_and_boxes_stay_apart(layout, max(174, layout.needed_height))


def test_whole_words_stay_whole_when_some_layout_allows_it():
    diagram = parse_diagram(" -> ".join(f"consolidation stage {index}" for index in range(6)))
    layout = layout_diagram(diagram, 384, 174, measure=fake_measure, max_height=324)
    for node, label in enumerate(diagram.nodes):
        words = set(label.split())
        for line in layout.lines[node]:
            assert set(line.split()) <= words, (label, layout.lines[node])


def test_last_resort_picks_the_direction_that_shows_the_most_text():
    diagram = parse_diagram(" -> ".join(f"long stage name number {index}" for index in range(8)))
    layout = layout_diagram(diagram, 384, 174, measure=fake_measure, max_height=324)
    assert not layout.horizontal  # eight 37 px columns would cut every label
    for node, label in enumerate(diagram.nodes):
        assert " ".join(layout.lines[node]) == label
