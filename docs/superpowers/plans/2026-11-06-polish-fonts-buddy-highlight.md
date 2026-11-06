# Plan: polish (fonts, buddy, no reply bubble, live highlights)

Spec: `docs/superpowers/specs/2026-11-06-polish-fonts-buddy-highlight-design.md` (binding). Tests:
`.venv/Scripts/python -m pytest -q -p no:cacheprovider`; lint: `ruff check .` and `ruff format`. TDD each task.
Edit scripts go in files written with the Write tool, never heredocs (quoting and `\b` have broken them before).

## Task 1: Fonts (clicky/fonts/, clicky/fonts.py)
Download `Inter[opsz,wght].ttf`, `GeistMono[wght].ttf` and both OFL.txt from github.com/google/fonts (ofl/inter,
ofl/geistmono) into `clicky/fonts/`. `fonts.py`: `load_fonts()` (idempotent, returns loaded family names),
`ui_font(pixel_size, weight=Normal)`, `mono_font(pixel_size, weight=Normal)` with Segoe UI / Consolas fallbacks.
Replace `handwriting_font`/`_handwriting_font`/`QFont("Segoe UI"…)` in lesson_card, followup_chips, scene_painter,
status_pill, overlay; formulas and axis ticks use mono. Remove the handwriting font helper. app calls `load_fonts()`
right after QApplication. Tests: both families load; card heading font is Inter, formula font is Geist Mono; ticks
mono. Preview render of the card inspected.

## Task 2: Buddy on top and softer (overlay.py, lesson_card.py, followup_chips.py, app.py)
`appeared` signal on LessonCard (first show of a card) and FollowUpChips (each show). App: raise the overlay on
card/chips `appeared` and after each mark. Buddy: no white pen, rounded-corner triangle path, soft shadow, glow kept.
Tests: signals fire; a rendered buddy has no near-white pixels.

## Task 3: No reply bubble (overlay.py, app.py)
Remove `show_reply` and its connection; transcript and notice bubbles remain. Tests updated/added.

## Task 4: Live highlight (visuals.py, controller.py, visual_director.py, scene_painter.py, lesson_card.py, app.py, prompts.py)
`HIGHLIGHT` tag (4 per reply, 40 chars) → `highlight` card-text event → `card.highlight(label)`. ScenePainter records
per-label item bounds each frame and draws a red ring around the highlighted label's live bounds (grow-in 0.4 s,
3 s total), and sets focus_point to it. App drops screen marks overlapping the visible card. Prompt documents HIGHLIGHT
and the card-invisible rule, with an example. Tests: parsing/limits; ring follows a moving object (bounds differ over
time); unknown label ignored; overlapping mark dropped; prompt examples parse. Live check with GPT-6.1 Terra.
