import time

from PySide6.QtWidgets import QApplication

from clicky.controller import ScreenVisualEvent, VisualPlan
from clicky.visual_director import VisualDirector


class Sinks:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def make_director(self, **overrides) -> VisualDirector:
        options = dict(
            annotate=lambda event: self.calls.append(("annotate", event.kind, event.box)),
            note=lambda text: self.calls.append(("note", text)),
            diagram=lambda spec: self.calls.append(("diagram", spec)),
            point=lambda event: self.calls.append(("point", event.point, event.label)),
            clear=lambda: self.calls.append(("clear",)),
            finish=lambda: self.calls.append(("finish",)),
        )
        options.update(overrides)
        return VisualDirector(**options)


def plan(has_audio: bool = True) -> VisualPlan:
    return VisualPlan(
        spoken_text="this line repeats the code under it",
        events=(
            ScreenVisualEvent(kind="underline", fraction=0.0, box=(1, 2, 30, 4)),
            ScreenVisualEvent(kind="note", fraction=0.5, text="loop = repeat"),
            ScreenVisualEvent(kind="point", fraction=0.6, point=(5, 6), label="here"),
            ScreenVisualEvent(kind="diagram", fraction=1.0, text="a -> b"),
        ),
        has_audio=has_audio,
    )


def pump_until(condition, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not condition():
        QApplication.processEvents()
        time.sleep(0.01)


def test_events_follow_playback_progress_and_finish_flushes(qt_app):
    sinks = Sinks()
    director = sinks.make_director()
    director.start(plan())
    assert sinks.calls == [("clear",), ("annotate", "underline", (1, 2, 30, 4))]
    director.on_progress(0.3)
    assert len(sinks.calls) == 2
    director.on_progress(0.62)
    assert sinks.calls[2:] == [("note", "loop = repeat"), ("point", (5, 6), "here")]
    director.on_playback_finished()
    assert sinks.calls[4:] == [("diagram", "a -> b"), ("finish",)]
    director.on_progress(1.0)  # nothing more after finishing
    assert len(sinks.calls) == 6


def test_idle_state_also_flushes_and_finishes(qt_app):
    sinks = Sinks()
    director = sinks.make_director()
    director.start(plan())
    director.on_state("idle")
    assert [call[0] for call in sinks.calls] == ["clear", "annotate", "note", "point", "diagram", "finish"]


def test_without_audio_a_timer_drives_the_timeline(qt_app):
    sinks = Sinks()
    director = sinks.make_director(estimate_duration=lambda text: 0.25)
    director.start(plan(has_audio=False))
    pump_until(lambda: ("finish",) in sinks.calls)
    assert [call[0] for call in sinks.calls] == ["clear", "annotate", "note", "point", "diagram", "finish"]


def test_listening_clears_and_ignores_stale_progress(qt_app):
    sinks = Sinks()
    director = sinks.make_director()
    director.start(plan())
    director.on_state("listening")
    assert sinks.calls[-1] == ("clear",)
    director.on_progress(1.0)
    director.on_playback_finished()
    assert sinks.calls[-1] == ("clear",)


def test_a_broken_sink_does_not_stop_the_rest(qt_app):
    sinks = Sinks()

    def broken_note(text: str) -> None:
        raise RuntimeError("paint failed")

    director = sinks.make_director(note=broken_note)
    director.start(plan())
    director.on_progress(1.0)
    assert ("diagram", "a -> b") in sinks.calls


def test_player_progress_math(qt_app):
    from clicky.playback import progress_fraction

    assert progress_fraction(500, 2000) == 0.25
    assert progress_fraction(5000, 2000) == 1.0
    assert progress_fraction(100, 0) is None
