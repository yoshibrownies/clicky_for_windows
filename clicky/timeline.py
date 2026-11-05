"""Fires visual events as the spoken reply progresses (pure logic, no Qt)."""

from __future__ import annotations

from collections.abc import Iterable

from clicky.visuals import VisualEvent

SPOKEN_CHARACTERS_PER_SECOND = 14.0
MINIMUM_ESTIMATED_SECONDS = 2.0


def estimated_duration_seconds(spoken_text: str) -> float:
    """Rough speaking time, used when there is no audio to follow (TTS failed)."""
    return max(MINIMUM_ESTIMATED_SECONDS, len(spoken_text) / SPOKEN_CHARACTERS_PER_SECOND)


class VisualTimeline:
    """Holds a reply's events sorted by fraction; `due(progress)` hands each one out exactly once."""

    def __init__(self, events: Iterable[VisualEvent], lead: float = 0.03) -> None:
        # Stable sort keeps the model's order for events at the same spot.
        self._events = sorted(events, key=lambda event: event.fraction)
        self._lead = lead
        self._next_index = 0

    @property
    def is_finished(self) -> bool:
        return self._next_index >= len(self._events)

    def due(self, progress: float) -> list:
        """Events whose moment has arrived. `lead` makes marks appear just before the words."""
        fired: list[VisualEvent] = []
        while not self.is_finished and self._events[self._next_index].fraction <= progress + self._lead:
            fired.append(self._events[self._next_index])
            self._next_index += 1
        return fired

    def flush(self) -> list:
        """Everything not yet fired (speech ended early or was cut short)."""
        remaining = self._events[self._next_index :]
        self._next_index = len(self._events)
        return remaining

    def reset(self) -> None:
        self._next_index = 0
