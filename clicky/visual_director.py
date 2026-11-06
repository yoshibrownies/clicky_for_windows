"""Plays a reply's visual events in time with its speech (GUI thread).

The controller hands over a VisualPlan; playback progress (or a timer, when there is no audio) advances a
VisualTimeline, and each due event goes to the sink that draws it: the annotation layer, the lesson card or the buddy.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from PySide6.QtCore import QObject, QTimer

from clicky.timeline import VisualTimeline, estimated_duration_seconds

logger = logging.getLogger(__name__)

FALLBACK_TICK_MS = 40


class VisualDirector(QObject):
    def __init__(
        self,
        *,
        annotate: Callable[[object], None],
        note: Callable[[str], None],
        diagram: Callable[[str], None],
        point: Callable[[object], None],
        clear: Callable[[], None],
        finish: Callable[[], None],
        animate: Callable[[str], None] | None = None,
        card_text: Callable[[str, str], None] | None = None,
        followups: Callable[[list[str]], None] | None = None,
        estimate_duration: Callable[[str], float] = estimated_duration_seconds,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._sinks = {"underline": annotate, "circle": annotate, "point": point}
        self._animate = animate or (lambda scene_text: None)
        self._card_text = card_text or (lambda kind, text: None)
        self._followups = followups or (lambda options: None)
        self._pending_followups: list[str] = []
        self._note = note
        self._diagram = diagram
        self._clear = clear
        self._finish = finish
        self._estimate_duration = estimate_duration
        self._timeline: VisualTimeline | None = None
        self._fallback_started_at = 0.0
        self._fallback_duration = 0.0
        self._fallback_timer = QTimer(self)
        self._fallback_timer.setInterval(FALLBACK_TICK_MS)
        self._fallback_timer.timeout.connect(self._on_fallback_tick)

    @property
    def is_active(self) -> bool:
        return self._timeline is not None

    def start(self, plan) -> None:
        """Begin a new reply's visuals. `plan` is a controller.VisualPlan."""
        self._stop_timer()
        self._clear()
        # Follow-up questions aren't timed: they're offered once the answer is over.
        self._pending_followups = [event.text for event in plan.events if event.kind == "followup"]
        timed_events = [event for event in plan.events if event.kind != "followup"]
        self._timeline = VisualTimeline(timed_events) if (timed_events or self._pending_followups) else None
        if self._timeline is None:
            return
        self.on_progress(0.0)
        if not plan.has_audio:
            self._fallback_duration = max(0.05, self._estimate_duration(plan.spoken_text))
            self._fallback_started_at = time.monotonic()
            self._fallback_timer.start()

    def on_progress(self, progress: float) -> None:
        if self._timeline is None:
            return
        for event in self._timeline.due(progress):
            self._dispatch(event)

    def cancel(self) -> None:
        """The reply was interrupted: forget its pending events without drawing them."""
        self._stop_timer()
        self._timeline = None
        self._pending_followups = []

    def on_playback_finished(self) -> None:
        self._complete()

    def on_state(self, state: str) -> None:
        if state == "listening":
            self._stop_timer()
            self._timeline = None
            self._pending_followups = []
            self._clear()
        elif state == "idle" and self._timeline is not None and not self._fallback_timer.isActive():
            self._complete()

    def _complete(self) -> None:
        self._stop_timer()
        if self._timeline is None:
            return
        for event in self._timeline.flush():
            self._dispatch(event)
        self._timeline = None
        followups, self._pending_followups = self._pending_followups, []
        if followups:
            try:
                self._followups(followups)
            except Exception:
                logger.exception("Showing follow-ups failed")
        self._finish()

    def _on_fallback_tick(self) -> None:
        progress = (time.monotonic() - self._fallback_started_at) / self._fallback_duration
        self.on_progress(min(progress, 1.0))
        if progress >= 1.0:
            self._complete()

    def _stop_timer(self) -> None:
        if self._fallback_timer.isActive():
            self._fallback_timer.stop()

    def _dispatch(self, event) -> None:
        try:
            if event.kind == "note":
                self._note(event.text)
            elif event.kind == "diagram":
                self._diagram(event.text)
            elif event.kind in ("title", "heading", "formula", "highlight"):
                self._card_text(event.kind, event.text)
            elif event.kind == "animate":
                self._animate(event.text)
            elif event.kind in self._sinks:
                self._sinks[event.kind](event)
        except Exception:
            # One bad mark must never stop the rest of the explanation.
            logger.exception("Drawing a %s failed", event.kind)
