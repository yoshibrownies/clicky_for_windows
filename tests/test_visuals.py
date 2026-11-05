import pytest

from clicky.visuals import MAX_MARKS, MAX_NOTES, parse_visual_reply


def test_plain_text_has_no_events():
    reply = parse_visual_reply("just an answer.")
    assert reply.spoken_text == "just an answer."
    assert reply.events == ()


def test_every_kind_is_parsed_with_its_payload():
    reply = parse_visual_reply(
        "see this word [UNDERLINE:100,200,300,220] and that button [CIRCLE:400,50,480,90:screen2] "
        "[NOTE: Step 1: open the menu] then [DIAGRAM:Input -> Process -> Output] "
        "over here [POINT:600,700:save button:screen2]"
    )
    kinds = [event.kind for event in reply.events]
    assert kinds == ["underline", "circle", "note", "diagram", "point"]
    underline, circle, note, diagram, point = reply.events
    assert underline.box == (100, 200, 300, 220) and underline.screen_number is None
    assert circle.box == (400, 50, 480, 90) and circle.screen_number == 2
    assert note.text == "Step 1: open the menu"
    assert diagram.text == "Input -> Process -> Output"
    assert point.point == (600, 700) and point.label == "save button" and point.screen_number == 2


def test_tags_are_removed_from_speech_and_spacing_cleaned():
    reply = parse_visual_reply("click [UNDERLINE:1,2,30,4] save , then [NOTE:save it] done [POINT:none]")
    assert reply.spoken_text == "click save, then done"


def test_fractions_follow_position_in_speech():
    reply = parse_visual_reply("[NOTE:a]first half of the sentence [NOTE:b]second half of it[NOTE:c]")
    fractions = [event.fraction for event in reply.events]
    assert fractions[0] == 0.0
    assert 0.4 < fractions[1] < 0.75
    assert fractions[2] == pytest.approx(1.0)
    assert fractions == sorted(fractions)


def test_tag_only_reply_gives_empty_speech_and_zero_fraction():
    reply = parse_visual_reply("[NOTE:just a note]")
    assert reply.spoken_text == ""
    assert reply.events[0].fraction == 0.0


def test_boxes_are_normalised_so_corners_are_ordered():
    reply = parse_visual_reply("x [UNDERLINE:300,220,100,200]")
    assert reply.events[0].box == (100, 200, 300, 220)


@pytest.mark.parametrize(
    "bad_tag",
    [
        "[UNDERLINE:1,2,3]",
        "[UNDERLINE:a,b,c,d]",
        "[CIRCLE:5,5,5,5]",
        "[NOTE:   ]",
        "[DIAGRAM:just words no arrows]",
        "[POINT:12]",
        "[SPARKLE:1,2]",
        "[UNDERLINE:1,2,3,4:screenX]",
    ],
)
def test_malformed_and_unknown_tags_are_dropped_from_speech_and_events(bad_tag):
    reply = parse_visual_reply(f"hello {bad_tag} world")
    assert reply.events == ()
    assert reply.spoken_text == "hello world"


def test_lowercase_brackets_in_speech_are_left_alone():
    assert parse_visual_reply("an [array] of things").spoken_text == "an [array] of things"


def test_limits_are_applied():
    marks = " ".join(f"w{index} [UNDERLINE:{index},0,{index + 10},5]" for index in range(10))
    notes = " ".join(f"[NOTE:note {index}]" for index in range(12))
    diagrams = "[DIAGRAM:A -> B] [DIAGRAM:C -> D]"
    reply = parse_visual_reply(f"{marks} {notes} {diagrams}")
    assert sum(event.kind == "underline" for event in reply.events) == MAX_MARKS
    assert sum(event.kind == "note" for event in reply.events) == MAX_NOTES
    assert [event.text for event in reply.events if event.kind == "diagram"] == ["A -> B"]


def test_long_notes_are_truncated():
    reply = parse_visual_reply("[NOTE:" + "x" * 200 + "]")
    assert len(reply.events[0].text) <= 80


def test_square_brackets_inside_notes_and_diagrams_are_kept_in_the_tag():
    reply = parse_visual_reply(
        "the first item [NOTE:list[0] is the first item] is at index zero [DIAGRAM:a[0] -> a[1]]"
    )
    assert reply.spoken_text == "the first item is at index zero"
    assert [event.text for event in reply.events] == ["list[0] is the first item", "a[0] -> a[1]"]


def test_an_unclosed_known_tag_is_never_spoken():
    reply = parse_visual_reply("see the loop [NOTE:arr[i] holds each value")
    assert reply.spoken_text == "see the loop"
    assert reply.events == ()


def test_visible_text_hides_bracketed_and_half_streamed_tags():
    from clicky.visuals import visible_text

    assert visible_text("see [NOTE:arr[i") == "see"
    assert visible_text("see [NOTE:arr[i] is fine] then") == "see then"
    assert visible_text("an [array] of things") == "an [array] of things"


SCENE_JSON = '{"duration": 4, "objects": [{"type": "circle", "x": "t", "y": 1}]}'


def test_animate_marker_picks_up_its_scene_block_and_the_block_is_never_spoken():
    reply = parse_visual_reply(
        f'watch the ball roll [ANIMATE:roll] faster and faster. <scene name="roll">{SCENE_JSON}</scene>'
    )
    assert reply.spoken_text == "watch the ball roll faster and faster."
    animate = [event for event in reply.events if event.kind == "animate"]
    assert len(animate) == 1
    assert animate[0].text == SCENE_JSON
    assert 0.3 < animate[0].fraction < 0.6


def test_scene_block_can_come_before_the_marker_and_json_brackets_are_fine():
    scene = '{"objects": [{"type": "rect", "x": 0, "y": 0, "w": 1, "h": [[0, 1], [1, 3]]}]}'
    reply = parse_visual_reply(f'<scene name="bars">{scene}</scene> the bars grow [ANIMATE:bars] here.')
    assert reply.spoken_text == "the bars grow here."
    assert reply.events[0].kind == "animate" and reply.events[0].text == scene


def test_marker_without_a_block_and_extra_animations_are_dropped():
    reply = parse_visual_reply(
        f'one [ANIMATE:a] two [ANIMATE:missing] three [ANIMATE:b] <scene name="a">{SCENE_JSON}</scene>'
        f'<scene name="b">{SCENE_JSON}</scene>'
    )
    assert [event.kind for event in reply.events] == ["animate"]
    assert reply.spoken_text == "one two three"


def test_unfinished_scene_block_is_never_spoken():
    reply = parse_visual_reply('look [ANIMATE:a] here. <scene name="a">{"objects": [{"type": ')
    assert reply.spoken_text == "look here."
    assert reply.events == ()


def test_visible_text_hides_scene_blocks_while_streaming():
    from clicky.visuals import visible_text

    assert visible_text('ok [ANIMATE:a] then <scene name="a">{"objects": [') == "ok then"
    assert visible_text("ok then <sce") == "ok then"
    assert visible_text(f'ok <scene name="a">{SCENE_JSON}</scene> done') == "ok done"
