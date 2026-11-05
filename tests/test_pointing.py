from clicky.pointing import parse_point_tag


def test_point_none():
    result = parse_point_tag("html is the skeleton of a web page. [POINT:none]")
    assert result.spoken_text == "html is the skeleton of a web page."
    assert result.coordinate is None
    assert result.label == "none"
    assert result.screen_number is None


def test_point_with_label():
    result = parse_point_tag("open the color inspector. [POINT:1100,42:color inspector]")
    assert result.spoken_text == "open the color inspector."
    assert result.coordinate == (1100, 42)
    assert result.label == "color inspector"
    assert result.screen_number is None


def test_point_with_screen_number():
    result = parse_point_tag("see the terminal? [POINT:400,300:terminal:screen2]")
    assert result.coordinate == (400, 300)
    assert result.label == "terminal"
    assert result.screen_number == 2


def test_point_without_label():
    result = parse_point_tag("right there [POINT:10, 20]")
    assert result.coordinate == (10, 20)
    assert result.label is None


def test_trailing_whitespace_after_tag():
    result = parse_point_tag("here [POINT:5,6:save button]  \n")
    assert result.coordinate == (5, 6)
    assert result.spoken_text == "here"


def test_no_tag_returns_text_unchanged():
    result = parse_point_tag("just an answer")
    assert result.spoken_text == "just an answer"
    assert result.coordinate is None
    assert result.label is None


def test_tag_not_at_end_is_ignored():
    text = "[POINT:1,2:x] then more words"
    result = parse_point_tag(text)
    assert result.spoken_text == text
    assert result.coordinate is None
