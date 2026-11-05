import json

import pytest

from clicky.scene import MAX_CAPTIONS, MAX_OBJECTS, parse_scene

SPEC_EXAMPLE = {
    "title": "a dropped ball speeds up",
    "duration": 6,
    "world": {"x": [0, 10], "y": [0, 50]},
    "axes": {"x": "time (s)", "y": "distance fallen (m)"},
    "objects": [
        {
            "type": "circle",
            "x": 2,
            "y": "50 - 4.9*t^2",
            "r": 10,
            "color": "blue",
            "label": "ball",
            "trail": True,
            "end": 3.2,
        },
        {"type": "arrow", "x": 2, "y": "50 - 4.9*t^2", "dx": 0, "dy": "-0.5*9.8*t", "color": "red", "label": "v"},
        {"type": "plot", "fn": "4.9*x^2", "from": 0, "to": "min(t, 3.2)", "color": "green"},
        {"type": "text", "x": 6, "y": 44, "text": "d = ½·g·t²", "size": 16},
        {"type": "rect", "x": 1, "y": 0, "w": 2, "h": [[0, 1], [2, 5]], "color": "orange"},
        {"type": "line", "x1": 0, "y1": 25, "x2": 10, "y2": 25, "color": "gray", "dashed": True},
    ],
    "captions": [{"at": 0, "text": "let go…"}, {"at": 1.5, "text": "faster every second"}],
}


def scene_from(data):
    return parse_scene(json.dumps(data))


def item(frame, kind):
    return next(entry for entry in frame if entry.kind == kind)


def test_spec_example_parses_with_metadata():
    scene = scene_from(SPEC_EXAMPLE)
    assert scene is not None
    assert scene.title == "a dropped ball speeds up"
    assert scene.duration == 6
    assert scene.world == (0, 10, 0, 50)
    assert scene.axes == ("time (s)", "distance fallen (m)")
    assert len(scene.objects) == 6


def test_formula_positions_follow_time():
    scene = scene_from(SPEC_EXAMPLE)
    ball = item(scene.frame(1.0), "circle")
    assert ball.values["x"] == 2
    assert ball.values["y"] == pytest.approx(45.1)
    assert ball.values["r"] == 10
    assert ball.color == "blue" and ball.label == "ball"
    arrow = item(scene.frame(2.0), "arrow")
    assert arrow.values["dy"] == pytest.approx(-9.8)


def test_keyframes_interpolate_and_hold():
    scene = scene_from(SPEC_EXAMPLE)
    assert item(scene.frame(0.0), "rect").values["h"] == 1
    assert item(scene.frame(1.0), "rect").values["h"] == pytest.approx(3)
    assert item(scene.frame(5.0), "rect").values["h"] == 5


def test_end_hides_the_object_and_fades_it_out_first():
    scene = scene_from(SPEC_EXAMPLE)
    assert item(scene.frame(1.0), "circle").alpha == 1.0
    assert 0 < item(scene.frame(3.1), "circle").alpha < 1
    assert not any(entry.kind == "circle" for entry in scene.frame(3.3))


def test_start_fades_in():
    scene = scene_from({"objects": [{"type": "point", "x": 1, "y": 1, "start": 2}]})
    assert scene.frame(1.0) == []
    assert 0 < scene.frame(2.1)[0].alpha < 1
    assert scene.frame(2.5)[0].alpha == 1.0


def test_trail_records_where_the_object_has_been():
    scene = scene_from(SPEC_EXAMPLE)
    trail = item(scene.frame(2.0), "circle").trail
    assert len(trail) >= 10
    assert trail[0][1] == pytest.approx(50)
    assert trail[-1][1] == pytest.approx(50 - 4.9 * 4, abs=0.5)


def test_plot_samples_between_from_and_to():
    scene = scene_from(SPEC_EXAMPLE)
    plot = item(scene.frame(1.0), "plot")
    points = [point for segment in plot.segments for point in segment]
    assert points[0] == pytest.approx((0, 0))
    assert points[-1][0] == pytest.approx(1.0)
    assert points[-1][1] == pytest.approx(4.9)


def test_plot_breaks_where_the_function_is_undefined():
    scene = scene_from({"objects": [{"type": "plot", "fn": "sqrt(x)", "from": -2, "to": 2}]})
    segments = scene.frame(0)[0].segments
    assert all(point[0] >= -0.05 for segment in segments for point in segment)


def test_stepped_text_and_colour_keyframes():
    scene = scene_from(
        {
            "objects": [
                {
                    "type": "text",
                    "x": 1,
                    "y": 1,
                    "text": [[0, "compare 5 and 2"], [1, "swap them"]],
                    "color": [[0, "gray"], [1, "red"]],
                },
            ]
        }
    )
    assert scene.frame(0.5)[0].text == "compare 5 and 2"
    assert scene.frame(0.5)[0].color == "gray"
    assert scene.frame(1.5)[0].text == "swap them"
    assert scene.frame(1.5)[0].color == "red"


def test_captions_pick_the_latest_started():
    scene = scene_from(SPEC_EXAMPLE)
    assert scene.caption_at(0.5)[0] == "let go…"
    assert scene.caption_at(2.0)[0] == "faster every second"


def test_unknown_colours_fall_back_and_bad_objects_are_skipped():
    scene = scene_from(
        {
            "objects": [
                {"type": "circle", "x": 1, "y": 1, "color": "chartreuse-ish"},
                {"type": "teleporter", "x": 1},
                {"type": "circle", "x": "os.system('rm')", "y": 1},
                {"type": "line", "x1": 0},
                "not an object",
            ]
        }
    )
    assert len(scene.objects) == 1
    assert scene.frame(0)[0].color == "blue"


def test_limits_and_clamps():
    data = {
        "duration": 500,
        "objects": [{"type": "point", "x": index, "y": 1} for index in range(100)],
        "captions": [{"at": index, "text": f"c{index}"} for index in range(20)],
        "title": "t" * 300,
    }
    scene = scene_from(data)
    assert scene.duration == 30
    assert len(scene.objects) == MAX_OBJECTS
    assert len(scene.captions) == MAX_CAPTIONS
    assert len(scene.title) <= 60
    assert scene_from({"duration": 0.1, "objects": [{"type": "point", "x": 1, "y": 1}]}).duration == 1


def test_bad_world_falls_back_to_default():
    scene = scene_from({"world": {"x": [5, 5], "y": "nope"}, "objects": [{"type": "point", "x": 1, "y": 1}]})
    assert scene.world == (0, 10, 0, 10)


def test_formula_errors_hide_the_object_for_that_frame():
    scene = scene_from({"objects": [{"type": "point", "x": "1/t", "y": 1}]})
    assert scene.frame(0.0) == []
    assert len(scene.frame(1.0)) == 1


@pytest.mark.parametrize(
    "text",
    ["", "not json", "[1, 2]", '{"objects": []}', '{"objects": "x"}', "null", '{"objects": [{"type": "point"}]}'],
)
def test_garbage_gives_no_scene(text):
    assert parse_scene(text) is None


def test_code_fences_around_json_are_tolerated():
    text = "```json\n" + json.dumps({"objects": [{"type": "point", "x": 1, "y": 1}]}) + "\n```"
    assert parse_scene(text) is not None


def test_oversized_scene_text_is_rejected():
    assert parse_scene("{" + " " * 30000 + "}") is None
