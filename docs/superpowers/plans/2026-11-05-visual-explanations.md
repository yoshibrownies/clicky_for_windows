# Plan: visual explanations

Spec: `docs/superpowers/specs/2026-11-05-visual-explanations-design.md` (binding).
Test command: `.venv/Scripts/python -m pytest -q -p no:cacheprovider`; lint: `.venv/Scripts/ruff check .` and
`ruff format`. TDD: write the test, watch it fail, implement, watch it pass. Branch `feat/initial-app`, conventional
commits.

Global constraints: no Worker changes; everything new is click-through and capture-excluded; timers run only while
animating; malformed model output never raises into the UI; Qt objects only on the GUI thread.

## Task 1: Visual tag parser (`clicky/visuals.py`)
`VisualEvent(kind, fraction, ...)` with kinds `point|underline|circle|note|diagram` (image-space coords +
screen_number, or text). `parse_visual_reply(text) -> VisualReply(spoken_text, events)`: strip every recognised tag
anywhere, fraction = offset of the tag in the spoken text ÷ spoken length (0 for empty), clamp to [0,1], apply
limits (6 marks, 8 notes, 1 diagram, note ≤ 80 chars), drop malformed tags, collapse the double spaces left behind.
Tests: each kind, inline order and fractions, `[POINT:none]`, screen numbers, malformed/unknown tags dropped (no
exception), limits, a trailing tag gives fraction ≈ 1, a tag-only reply gives empty spoken text.

## Task 2: Diagram model and layout (`clicky/diagram.py`)
`parse_diagram(spec) -> Diagram(nodes, edges)` from `A -> B -> C; B -> D` (labels trimmed, ≤ 24 chars, ≤ 8 nodes,
≤ 10 edges, self-loops/duplicates dropped). `layout_diagram(diagram, width, height) -> {node: QRectF-like tuple}` with
longest-path layering left to right; switch to top-to-bottom when there are more layers than fit. Pure, no Qt.
Tests: chain, branch, cycle-safe (no infinite loop), limits, layout inside bounds with no overlapping boxes.

## Task 3: Timeline (`clicky/timeline.py`)
`VisualTimeline(events, lead=0.03)`: `due(progress) -> list[events]` fires each event once, in fraction order;
`reset()`; `is_finished`. `estimated_duration_seconds(spoken_text)` ≈ len/14, min 2 s. Tests.

## Task 4: Smarter and simpler (prompt, config, tray)
Rewrite `prompts.py` per spec (teacher style, tag grammar with examples, limits). `DEFAULT_EFFORT = "medium"`;
`EFFORT_LEVELS = {"low": "Fast", "medium": "Balanced", "high": "Deep"}`; add `gpt-6.1-sol`. Tray: "Thinking" submenu
(emits `effort_selected`) and a "Show notepad" toggle (emits `notepad_toggled`). Controller gets `set_effort`. Update
the prompt-related tests and the config default tests. Tests: prompt mentions every tag; tray emits; config defaults.

## Task 5: Controller emits visual events
After the stream: `parse_visual_reply`; spoken text from it; map underline/circle/point boxes to global logical
coords with the right capture (`screen_number` fallback to cursor screen); `CompanionReply.visual_events` (tuple of
`ScreenVisualEvent`). Keep `point_requested` behaviour for a POINT at fraction ≥ 0.9 (legacy end tag), otherwise let
the director time it. New signal `visuals_ready(object)` emitted from `_on_reply_ready` before playback. Tests:
events mapped and ordered; refusal → no visuals; history stores the raw reply.

## Task 6: Player progress + VisualDirector (`clicky/visual_director.py`)
`SpeechPlayer.progress = Signal(float)` from positionChanged/duration. `VisualDirector(QObject)`: `start(events,
spoken_text, has_audio)`, `on_progress(p)`, fallback QTimer when there's no audio, `on_state(state)` (idle → linger
and fade, listening → clear), dispatches to injected sinks (`annotate`, `note`, `diagram`, `point`). Tests with fake
sinks: order and timing, fallback timer, clear on listening.

## Task 7: AnnotationLayer (`clicky/annotations.py`)
Per-screen overlay windows (created per QScreen on demand), underline (wobbly, left to right, 450 ms) and circle
(traced ellipse, 600 ms); fade; hide when empty; capture exclusion; timer only while animating. Pure helpers for the
wobble path and ellipse points are unit-tested. Offscreen smoke: add marks, pump, grab is non-empty, timer stops
after the fade.

## Task 8: NotepadWindow (`clicky/notepad.py`)
Paper panel, typewriter-handwriting notes (Ink Free → Segoe Print fallback), diagram drawing (boxes then arrows)
using `layout_diagram`; docked on the cursor screen; linger 20 s then fade; disabled when the toggle is off.
Offscreen smoke: notes typed progressively, diagram draws, the timer stops when finished.

## Task 9: Wire it up, end to end, live check
app.py wiring (director ↔ player ↔ overlay ↔ layer ↔ notepad ↔ tray). E2E test: the fake Worker returns a reply with
NOTE/UNDERLINE/DIAGRAM tags, and the director receives the mapped events. Live: a synthetic screenshot with known
text and a GPT-6.1 Terra request checks an UNDERLINE lands on the right words. Real launch smoke. README/AGENTS update.
