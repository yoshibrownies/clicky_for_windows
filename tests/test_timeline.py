from clicky.timeline import VisualTimeline, estimated_duration_seconds
from clicky.visuals import VisualEvent


def note(text: str, fraction: float) -> VisualEvent:
    return VisualEvent(kind="note", fraction=fraction, text=text)


def test_events_fire_once_in_order_with_lead():
    timeline = VisualTimeline([note("c", 0.9), note("a", 0.0), note("b", 0.5)], lead=0.03)
    assert [event.text for event in timeline.due(0.0)] == ["a"]
    assert timeline.due(0.2) == []
    assert [event.text for event in timeline.due(0.48)] == ["b"]  # 0.48 + 0.03 lead reaches 0.5
    assert timeline.due(0.6) == []
    assert not timeline.is_finished
    assert [event.text for event in timeline.due(1.0)] == ["c"]
    assert timeline.is_finished
    assert timeline.due(1.0) == []


def test_jumping_ahead_fires_everything_skipped_in_order():
    timeline = VisualTimeline([note("a", 0.1), note("b", 0.2), note("c", 0.3)])
    assert [event.text for event in timeline.due(0.95)] == ["a", "b", "c"]


def test_finish_flushes_the_rest_and_reset_restarts():
    timeline = VisualTimeline([note("a", 0.1), note("b", 0.99)])
    timeline.due(0.2)
    assert [event.text for event in timeline.flush()] == ["b"]
    timeline.reset()
    assert [event.text for event in timeline.due(0.2)] == ["a"]


def test_empty_timeline_is_finished():
    assert VisualTimeline([]).is_finished


def test_estimated_duration():
    assert estimated_duration_seconds("") == 2.0
    assert 6.5 < estimated_duration_seconds("x" * 100) < 7.5
