from clicky.prompts import COMPANION_SYSTEM_PROMPT


def test_prompt_teaches_every_visual_tag_with_examples():
    for tag in ("[UNDERLINE:", "[CIRCLE:", "[NOTE:", "[DIAGRAM:", "[POINT:"):
        assert COMPANION_SYSTEM_PROMPT.count(tag) >= 2, f"{tag} needs a rule and an example"


def test_prompt_asks_for_simple_explanations():
    lowered = COMPANION_SYSTEM_PROMPT.lower()
    assert "plain" in lowered and "analogy" in lowered
    assert "card" in lowered


def test_examples_write_notes_while_talking_not_only_at_the_end():
    import re

    from clicky.visuals import parse_visual_reply

    lowered = COMPANION_SYSTEM_PROMPT.lower()
    assert "right after the sentence" in lowered
    assert "never put square brackets inside a tag" in lowered
    examples = re.findall(r'^- user asks[^"]*"(.*)"\s*$', COMPANION_SYSTEM_PROMPT, flags=re.MULTILINE)
    noted = [parse_visual_reply(example) for example in examples if "[NOTE:" in example]
    assert noted, "examples should include notes"
    for reply in noted:
        assert min(event.fraction for event in reply.events if event.kind == "note") < 0.8


def test_every_example_animation_in_the_prompt_parses_and_fires():
    import re

    from clicky.scene import parse_scene
    from clicky.visuals import parse_visual_reply

    assert "[ANIMATE:" in COMPANION_SYSTEM_PROMPT and "<scene name=" in COMPANION_SYSTEM_PROMPT
    examples = re.findall(r'^- user asks[^"]*"(.*)"\s*$', COMPANION_SYSTEM_PROMPT, flags=re.MULTILINE)
    animated = [example for example in examples if "<scene" in example]
    assert len(animated) >= 2
    for example in animated:
        reply = parse_visual_reply(example)
        scenes = [event for event in reply.events if event.kind == "animate"]
        assert scenes, example[:60]
        for event in scenes:
            scene = parse_scene(event.text)
            assert scene is not None, example[:60]
            assert scene.frame(scene.duration / 2), "the example should draw something mid-way"
        assert "<scene" not in reply.spoken_text and "{" not in reply.spoken_text


def test_prompt_asks_for_the_animation_to_start_early():
    lowered = COMPANION_SYSTEM_PROMPT.lower()
    assert "start the animation early" in lowered


def test_prompt_teaches_the_lesson_card_and_longer_answers():
    for tag in ("[TITLE:", "[HEADING:", "[FORMULA:", "[FOLLOWUP:"):
        assert COMPANION_SYSTEM_PROMPT.count(tag) >= 2, f"{tag} needs a rule and an example"
    lowered = COMPANION_SYSTEM_PROMPT.lower()
    assert "4 to 8 sentences" in lowered


def test_prompt_examples_with_a_card_have_followups_at_the_end():
    import re

    from clicky.visuals import parse_visual_reply

    examples = re.findall(r'^- user asks[^"]*"(.*)"\s*$', COMPANION_SYSTEM_PROMPT, flags=re.MULTILINE)
    carded = [parse_visual_reply(example) for example in examples if "[HEADING:" in example]
    assert len(carded) >= 2
    for reply in carded:
        kinds = [event.kind for event in reply.events]
        assert "title" in kinds and "heading" in kinds and kinds.count("followup") >= 2


def test_prompt_teaches_live_highlights_and_that_the_card_is_invisible():
    from clicky.prompts import COMPANION_SYSTEM_PROMPT
    from clicky.visuals import extract_scene_blocks, parse_visual_reply

    assert "[HIGHLIGHT:label]" in COMPANION_SYSTEM_PROMPT
    assert "hidden from your screenshots" in COMPANION_SYSTEM_PROMPT
    orbit_example = next(line for line in COMPANION_SYSTEM_PROMPT.splitlines() if "moon doesn't fall" in line)
    reply = orbit_example.split(': "', 1)[1].rstrip('"')
    parsed = parse_visual_reply(reply)
    highlighted = [event.text for event in parsed.events if event.kind == "highlight"]
    assert highlighted == ["moon", "gravity"]
    scenes = extract_scene_blocks(reply)[1]
    assert "orbit" in scenes and all(f'"label": "{name}"' in scenes["orbit"] for name in highlighted)


def test_prompt_explains_the_cut_off_marker():
    from clicky.prompts import COMPANION_SYSTEM_PROMPT, CUT_OFF_MARKER

    assert CUT_OFF_MARKER in COMPANION_SYSTEM_PROMPT


def test_prompt_teaches_drawn_illustrations_generally():
    import re

    from clicky.icons import ICON_NAMES
    from clicky.visuals import MAX_ANIMATIONS

    lowered = COMPANION_SYSTEM_PROMPT.lower()
    listed = re.search(r"icons: ([a-z, ]+)\.", lowered).group(1).split(", ")
    assert set(listed) == set(ICON_NAMES)  # the prompt offers exactly the figures that exist
    for key in ("path {d:", "icon {name", "rotate", "opacity", "draw", "fill", "train of thought"):
        assert key in lowered, key
    assert f"{MAX_ANIMATIONS} animations" in lowered
    assert "you draw yourself with path" in lowered  # anything else gets sketched for the question at hand
    assert "design a fresh one every time" in lowered


def test_the_figure_library_stays_general_purpose():
    from clicky.icons import ICON_NAMES

    # Subject-specific figures belong in the model's own path drawings, not the library (no overfitting to a topic).
    assert len(ICON_NAMES) <= 10
    assert not {"brain", "neuron", "synapse", "domino"} & set(ICON_NAMES)


def test_prompt_warns_that_paths_are_y_up_and_keeps_scene_counts_lean():
    lowered = COMPANION_SYSTEM_PROMPT.lower()
    assert "y points up, unlike svg" in lowered  # otherwise remembered svg shapes draw upside down
    assert "no a, s or t" in lowered  # unsupported commands would silently drop the drawing
    assert "only as many as the ideas need" in lowered
    assert "2 to 4 in all" not in lowered
