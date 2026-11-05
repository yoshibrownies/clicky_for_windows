# Plan: lesson card restyle

Spec: `docs/superpowers/specs/2026-11-06-lesson-card-design.md` (binding). Tests: `.venv/Scripts/python -m pytest -q
-p no:cacheprovider`; lint: `ruff check .` and `ruff format`. TDD each task. Don't put backslash escapes like `\b`
inside heredoc Python edit scripts: write regexes with the Edit/Write tools (a backspace slipped in twice).

## Task 1: New tags (visuals.py, controller.py)
TITLE, HEADING, FORMULA, FOLLOWUP kinds with limits (1/1/3/3) and length caps; follow-ups get fraction 1.0. The
controller passes them through as ScreenVisualEvents. The bubble hides them. Tests.

## Task 2: Scene painter refactor (whiteboard.py → scene_painter.py)
Move `WorldMapper`, `nice_ticks` and the scene painting into `ScenePainter.paint(painter, rect, scene, t, paper)`.
WhiteboardWindow keeps working on top of it (until Task 7 removes the window). Existing tests stay green; add a test
that the painter draws into an arbitrary rect.

## Task 3: LessonCard (lesson_card.py)
Blocks: heading, note, formula, diagram (reuse the notepad diagram painting, moved into a `diagram_painter` helper),
animation (ScenePainter). API: `set_title`, `add_heading`, `add_note`, `add_formula`, `set_diagram`,
`play_animation(scene)`, `finish`, `clear`, `set_enabled`, `writing_point` signal, `content_blocks()` for tests.
Typing, sequential reveal, auto-height with scroll cap, dock right, linger/fade, timers stop. Offscreen tests plus a
real-font preview render inspected.

## Task 4: Follow-up chips + typed questions
`FollowUpChips(QWidget)` with `show_options(list[str], below=QRect)`, `hide_options()`, `chosen = Signal(str)`, no
focus. `CompanionController.ask_typed(text)`. Tests: chip click emits and hides; ask_typed sends a request whose
transcript is the text, with no transcription session started.

## Task 5: Top status pill (status_pill.py)
`StatusPill.set_state(state)`, `set_audio_level(level)`; shows for listening/processing/responding, fades out after
idle; timer only while visible or fading. Tests.

## Task 6: Cursor follows the pen
`BuddyOverlay.guide_to(x, y)` / `release_guide()`; the card emits `writing_point` while revealing. Tests: guided mode
moves toward the point; a POINT flight wins; release returns.

## Task 7: Wiring, prompt, docs
The app uses LessonCard + chips + pill (notepad and whiteboard windows retired; their tests move or are deleted when
the card covers them). The director gets sinks for the new kinds plus follow-ups at finish. Prompt: longer answers,
card tags, examples (tested). Max tokens 8192. README/AGENTS. E2E test with every new tag. Live check plus preview.
