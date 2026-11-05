from clicky.prompts import COMPANION_SYSTEM_PROMPT


def test_prompt_teaches_every_visual_tag_with_examples():
    for tag in ("[UNDERLINE:", "[CIRCLE:", "[NOTE:", "[DIAGRAM:", "[POINT:"):
        assert COMPANION_SYSTEM_PROMPT.count(tag) >= 2, f"{tag} needs a rule and an example"


def test_prompt_asks_for_simple_explanations():
    lowered = COMPANION_SYSTEM_PROMPT.lower()
    assert "plain" in lowered and "analogy" in lowered
    assert "notepad" in lowered
