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
    scene = scene_with({"type": "rect", "x": 7, "y": 0, "w": 1, "h": [[0, 1], [2, 5]]})
    assert item(scene.frame(0.5), "rect").values["h"] < 2  # eased: slower than constant speed at first
    assert item(scene.frame(1.0), "rect").values["h"] == pytest.approx(3)
    assert item(scene.frame(3.0), "rect").values["h"] == 5


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
    segments = scene.frame(1.0)[0].segments
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
    assert scene.frame(1.0)[0].color == "blue"


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


def test_huge_json_integers_never_raise():
    huge = "1" + "0" * 400
    for text in (
        '{"objects": [{"type": "point", "x": HUGE, "y": 1}, {"type": "point", "x": 1, "y": 1}]}'.replace("HUGE", huge),
        '{"duration": HUGE, "objects": [{"type": "point", "x": 1, "y": 1}]}'.replace("HUGE", huge),
        '{"world": {"x": [0, HUGE], "y": [0, 1]}, "objects": [{"type": "point", "x": 1, "y": 1}]}'.replace(
            "HUGE", huge
        ),
    ):
        scene = parse_scene(text)
        assert scene is not None and len(scene.objects) >= 1


def test_worst_case_scene_stays_inside_the_frame_budget():
    import time

    long_formula = (
        "sin(x*0.5+t)*3 + cos(x*0.25-t)*2 + sqrt(abs(x)+1)*0.5 + min(x, t)*0.1 + max(x, 2)*0.05 + lerp(1, 2, 0.5)"
    )
    trail_formula = "5 + sin(t*3)*2 + cos(t*1.5)*1.5 + sqrt(t+1) + abs(sin(t)) + min(t, 3) + lerp(0, 1, 0.5)"
    objects = [{"type": "plot", "fn": long_formula, "from": 0, "to": 10} for _ in range(20)]
    objects += [{"type": "circle", "x": trail_formula, "y": trail_formula, "trail": True} for _ in range(20)]
    scene = scene_from({"duration": 30, "world": {"x": [0, 10], "y": [0, 20]}, "objects": objects})
    timings = []
    for frame_index in range(7):
        started = time.perf_counter()
        scene.frame(10.0 + frame_index * 0.016)
        timings.append(time.perf_counter() - started)
    assert sorted(timings)[3] < 0.008, f"median frame took {sorted(timings)[3] * 1000:.1f} ms"


def test_plot_and_trail_caps():
    from clicky.scene import MAX_PLOTS, MAX_TRAILS

    objects = [{"type": "plot", "fn": "x", "from": 0, "to": 1} for _ in range(10)]
    objects += [{"type": "circle", "x": 1, "y": 1, "trail": True} for _ in range(10)]
    scene = scene_from({"objects": objects})
    assert sum(item.kind == "plot" for item in scene.objects) == MAX_PLOTS
    assert sum(item.trail for item in scene.objects) == MAX_TRAILS
    assert sum(item.kind == "circle" for item in scene.objects) == 10  # circles kept, only their trails capped


# ---------- drawn illustrations: paths, icons, rotation, opacity, fill ----------


def scene_with(*objects):
    import json as _json

    return parse_scene(_json.dumps({"duration": 4, "world": {"x": [0, 10], "y": [0, 10]}, "objects": list(objects)}))


def test_path_objects_carry_their_outline_and_transform_values():
    scene = scene_with(
        {"type": "path", "d": "M 0 0 L 2 0 L 2 2 Z", "x": 3, "y": 4, "scale": 2, "rotate": 90, "fill": "orange"}
    )
    (item,) = scene.frame(1.0)
    assert item.kind == "path"
    assert item.segments == [[(0.0, 0.0), (2.0, 0.0), (2.0, 2.0), (0.0, 0.0)]]
    assert (item.values["x"], item.values["y"], item.values["scale"], item.values["rotate"]) == (3, 4, 2, 90)
    assert item.fill == "orange"


def test_icons_use_the_built_in_library_and_unknown_ones_are_skipped():
    scene = scene_with(
        {"type": "icon", "name": "gear", "x": 5, "y": 1, "size": 4, "label": "gear"},
        {"type": "icon", "name": "dragon", "x": 5, "y": 1},
    )
    (item,) = scene.frame(0.5)
    assert item.kind == "icon" and item.label == "gear" and item.values["size"] == 4
    assert len(item.segments) >= 2
    assert item.color == "black"


def test_invalid_path_data_skips_the_object():
    assert scene_with({"type": "path", "d": "L 1 1", "x": 0, "y": 0}) is None


def test_draw_sketches_the_outline_in_over_time():
    scene = scene_with({"type": "path", "d": "M 0 0 L 4 0", "x": 0, "y": 0, "draw": "min(1, t/2)"})
    assert scene.frame(0.0) == [] or scene.frame(0.0)[0].segments == []
    assert scene.frame(1.0)[0].segments == [[(0.0, 0.0), (2.0, 0.0)]]
    assert scene.frame(3.0)[0].segments == [[(0.0, 0.0), (4.0, 0.0)]]


def test_opacity_scales_alpha_and_rotate_and_pivot_reach_rects():
    scene = scene_with(
        {
            "type": "rect",
            "x": 1,
            "y": 0,
            "w": 1,
            "h": 4,
            "rotate": [[0, 0], [1, -80]],
            "pivot": "bottom-right",
            "opacity": 0.5,
            "fill": "none",
        },
        {"type": "circle", "x": 1, "y": 1, "opacity": "t/4"},
    )
    rect, circle = scene.frame(1.0)
    assert rect.alpha == 0.5 and rect.values["rotate"] == -80 and rect.pivot == "bottom-right"
    assert rect.fill == "none"
    assert circle.alpha == 0.25


def test_bad_fill_and_pivot_fall_back_to_defaults():
    (rect,) = scene_with({"type": "rect", "x": 1, "y": 0, "w": 1, "h": 1, "fill": "sparkly", "pivot": "top"}).frame(1.0)
    assert rect.fill == "" and rect.pivot == "bottom-left"


@pytest.mark.parametrize("bad_value", [["gear"], {"a": 1}, 3, None])
def test_non_string_icon_names_and_types_never_raise(bad_value):
    good = {"type": "circle", "x": 1, "y": 1}
    scene = scene_with({"type": "icon", "name": bad_value, "x": 1, "y": 1}, {"type": bad_value, "x": 1, "y": 1}, good)
    assert scene is not None and [item.kind for item in scene.frame(1.0)] == ["circle"]


# ---------- livelier scenes: entrances, build-up, eased keyframes ----------


def test_objects_ease_in_from_their_start():
    from clicky.scene import ENTRANCE_SECONDS

    scene = scene_with({"type": "circle", "x": 1, "y": 1, "start": 1.0}, {"type": "circle", "x": 2, "y": 2})
    assert [item.kind for item in scene.frame(0.5)] == ["circle"]  # the first hasn't started yet
    entering = scene.frame(1.0 + ENTRANCE_SECONDS / 2)[0]  # listed first, so drawn first
    assert 0.0 < entering.entrance < 1.0 and 0.0 < entering.alpha < 1.0
    assert scene.frame(1.0 + ENTRANCE_SECONDS + 0.01)[0].entrance == 1.0


def test_unstaged_scenes_build_up_in_order():
    from clicky.scene import STAGGER_SECONDS

    scene = scene_with(
        {"type": "circle", "x": 1, "y": 1}, {"type": "circle", "x": 2, "y": 2}, {"type": "circle", "x": 3, "y": 3}
    )
    assert [scene_object.start for scene_object in scene.objects] == pytest.approx(
        [0.0, STAGGER_SECONDS, 2 * STAGGER_SECONDS]
    )


def test_staged_scenes_keep_their_timing():
    scene = scene_with(
        {"type": "circle", "x": 1, "y": 1},
        {"type": "circle", "x": 2, "y": 2, "start": 2},
        {"type": "circle", "x": 3, "y": 3},
    )
    assert [scene_object.start for scene_object in scene.objects] == [0.0, 2.0, 0.0]


def test_stagger_fits_in_the_first_seconds():
    scene = scene_with(*({"type": "point", "x": index % 10, "y": 1} for index in range(12)))
    assert scene.objects[-1].start <= 1.2 + 1e-9


def test_keyframes_ease_between_values():
    (item_quarter,) = scene_with({"type": "point", "x": [[0, 0], [4, 8]], "y": 1, "start": 0.0}).frame(1.0)
    (item_middle,) = scene_with({"type": "point", "x": [[0, 0], [4, 8]], "y": 1}).frame(2.0)
    assert item_middle.values["x"] == pytest.approx(4.0)  # halfway in time, halfway in value
    assert item_quarter.values["x"] < 2.0  # eased: slower than constant speed at the start
