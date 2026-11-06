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
        assert len(scenes) == 1, example[:60]
        scene = parse_scene(scenes[0].text)
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
