import time

from PySide6.QtWidgets import QApplication

from clicky.notepad import NotepadWindow, typed_characters, wrap_text


def pump(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)


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


def test_notes_are_written_progressively_then_the_timer_stops(qt_app):
    notepad = NotepadWindow(linger_seconds=0.2, fade_seconds=0.1, characters_per_second=200)
    try:
        notepad.add_note("for loop = repeat once per item")
        notepad.add_note("the indented code runs each time")
        assert notepad.isVisible()
        pump(0.05)
        assert 0 < notepad.typed_character_count() < len("for loop = repeat once per item") * 2
        pump(0.6)
        assert notepad.typed_character_count() == len("for loop = repeat once per item") + len(
            "the indented code runs each time"
        )
        assert not notepad.is_animating
        assert not notepad.grab().toImage().isNull()
    finally:
        notepad.close()


def test_diagram_draws_then_finish_fades_it_away(qt_app):
    notepad = NotepadWindow(linger_seconds=0.2, fade_seconds=0.1, characters_per_second=200)
    try:
        notepad.set_diagram("browser -> server -> database; server -> cache")
        assert notepad.isVisible()
        assert notepad.diagram_node_count() == 4
        pump(2.5)
        assert notepad.diagram_fully_drawn()
        notepad.finish()
        pump(0.8)
        assert not notepad.isVisible()
    finally:
        notepad.close()


def test_clear_empties_and_hides(qt_app):
    notepad = NotepadWindow()
    try:
        notepad.add_note("something")
        notepad.clear()
        pump(0.4)
        assert notepad.typed_character_count() == 0
        assert not notepad.isVisible()
    finally:
        notepad.close()


def test_disabled_notepad_ignores_everything(qt_app):
    notepad = NotepadWindow()
    try:
        notepad.set_enabled(False)
        notepad.add_note("hidden")
        notepad.set_diagram("a -> b")
        assert not notepad.isVisible()
    finally:
        notepad.close()


def test_bad_diagram_spec_is_ignored(qt_app):
    notepad = NotepadWindow()
    try:
        notepad.set_diagram("no arrows here")
        assert notepad.diagram_node_count() == 0
    finally:
        notepad.close()
