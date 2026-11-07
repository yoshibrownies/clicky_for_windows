# Clicky for Windows: agent notes

Python 3.13 + PySide6 port of farzaa/clicky. Read `docs/design.md` before changing behaviour.

## Commands
- Tests: `.venv\Scripts\python -m pytest -q` (Qt runs offscreen via `tests/conftest.py`)
- Lint/format: `.venv\Scripts\ruff check .` and `.venv\Scripts\ruff format .`
- Run: `.venv\Scripts\python -m clicky` (needs `CLICKY_WORKER_URL`)

## Rules
- `worker/` is the upstream Worker plus two deliberate changes: an added `/chat-openai` route (OpenAI Chat
  Completions, `OPENAI_API_KEY` secret) and a free-plan-friendly `ELEVENLABS_VOICE_ID` in `wrangler.toml`. Leave the
  upstream routes (`/chat`, `/tts`, `/transcribe-token`) unchanged. The Worker forwards no client headers.
- Models: `gpt-*` go to `/chat-openai` (`openai_client.py`), everything else to `/chat` (`claude_client.py`). Both
  yield the same TextDelta/StreamFinished events; OpenAI finish reasons are mapped to Claude's stop-reason names.
- No API keys in the app, repo, tests or logs.
- Threading: Qt objects on the GUI thread only; network on `AsyncRunner`'s loop; cross-thread results go through
  Qt signals. Screen capture (`QScreen.grabWindow`) is GUI-thread only.
- Keep `tests/test_end_to_end.py` passing. It is the contract with the Worker and AssemblyAI protocol.
- Names: descriptive over short (upstream convention). Type hints on public functions.
- Branches `feat/…` / `fix/…`; conventional commits; never commit to `main` directly.
- Visual explanations: the prompt (`prompts.py`) teaches inline tags; `visuals.py` limits (MAX_*) must match the
  prompt's stated limits. Every overlay window (buddy, annotation layer, status pill) must stay click-through; the lesson
  card and follow-up chips take the mouse but never keyboard focus. All are capture-excluded and run timers only while
  something animates. Design: `docs/superpowers/specs/2026-11-05-visual-explanations-design.md`.
- Animations: the model writes `[ANIMATE:name]` plus a `<scene name="name">{json}</scene>` block (`visuals.py`).
  Formulas go ONLY through `expressions.compile_formula` (whitelisted recursive-descent parser) — never `eval`/`exec`.
  Every scene example in `prompts.py` must parse (tested). Design: `docs/superpowers/specs/2026-11-06-animations-and-clear-design.md`.
- History holds only what you heard: a reply is added when speech ends, or cut at playback progress
  (`visuals.heard_part`) plus `prompts.CUT_OFF_MARKER` when interrupted.
  Design: `docs/superpowers/specs/2026-11-07-interrupt-awareness-design.md`.
- Clearing: Esc (`KeyTapWatcher`) and tray "Clear screen" call `build_clear_controls` in `app.py`. Esc also stops speech (and an answer still on its way) via
  `CompanionController.stop_speaking`; the tray item leaves speech playing. Esc never cancels listening.
- Lesson card (`lesson_card.py`) replaced the notepad and whiteboard. Follow-up chips (`followup_chips.py`) and the card
  (drag by title bar, x to close, wheel to scroll) are the only clickable windows; they must never take keyboard focus.
  The card glides away from screen marks (`LessonCard.avoid`). Design: `docs/superpowers/specs/2026-11-06-movable-card-design.md`. Typed questions go through `CompanionController.ask_typed`.
  Design: `docs/superpowers/specs/2026-11-06-lesson-card-design.md`.
