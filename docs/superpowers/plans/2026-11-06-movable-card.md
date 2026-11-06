# Plan: movable card, dodge marks, Win+Alt

Spec: `docs/superpowers/specs/2026-11-06-movable-card-design.md` (binding). Tests:
`.venv/Scripts/python -m pytest -q -p no:cacheprovider`; lint `ruff check .` / `ruff format`. TDD. Edit scripts via
the Write tool, never heredocs. Tests that show widgets must close them in `finally` (a leaked widget with a live
timer crashed the run twice).

## Task 1: Interactive card (lesson_card.py, app.py)
Drop the click-through flags (keep no-focus). Title-bar drag (moves the window, remembers `_user_position`), `×` button
(`clear()`), wheel scroll (`_user_scroll`, reset when a new block is appended, clamped). `moved` signal; app re-shows
the chips under the card when it moves. `_dock()` uses the remembered position, clamped onto a screen. Tests with
QTest: no-focus flags and input accepted; drag moves by the delta and is remembered for the next card; `×` empties;
wheel changes scroll_offset and new content resets it.

## Task 2: Dodge marks (lesson_card.py, app.py)
`card.avoid(QRect)` records a mark rect for ~12 s; if visible and overlapping, glide (QPropertyAnimation on pos) to the
opposite dock spot of the same screen (or the less-overlapping one). `_dock()` avoids live rects. App: `add_mark` calls
`card.avoid(rect)` instead of dropping. Tests: visible card moves off an overlapping mark; a new card docks away from a
live mark; expired marks are ignored; non-overlapping marks don't move it.

## Task 3: Win+Alt (config.py, .env.example, README.md, tests)
DEFAULT_HOTKEY "win+alt"; parse works; tray pretty "Win + Alt"; docs. Tests updated first.
