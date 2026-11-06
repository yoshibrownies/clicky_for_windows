from clicky.handwriting import typed_characters, wrap_text


def test_wrap_text_breaks_on_words_to_fit():
    lines = wrap_text("a variable is like a labelled box", lambda text: len(text) * 10, 120)
    assert lines == ["a variable", "is like a", "labelled box"]
    assert all(len(line) * 10 <= 120 for line in lines)


def test_wrap_text_splits_a_word_longer_than_the_line():
    lines = wrap_text("supercalifragilistic", lambda text: len(text) * 10, 60)
    assert "".join(lines) == "supercalifragilistic"
    assert all(len(line) <= 6 for line in lines)


def test_typed_characters_follows_time():
    assert typed_characters(0.0, 45, 30) == 0
    assert typed_characters(0.5, 40, 30) == 20
    assert typed_characters(10.0, 40, 30) == 30
