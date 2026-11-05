# Plan: animations (scene language + whiteboard) and clear

Spec: `docs/superpowers/specs/2026-11-06-animations-and-clear-design.md` (binding).
Test command: `.venv/Scripts/python -m pytest -q -p no:cacheprovider`; lint: `ruff check .` and `ruff format`.
TDD for every task. Branch `feat/initial-app`, conventional commits.
Global constraints: no `eval`/`exec` of model text; malformed scenes never raise into Qt; timers only while animating;
every window click-through and capture-excluded; no Worker changes.

## Task 1: Safe formula evaluator (`clicky/expressions.py`)
`compile_formula(text) -> Formula | None` (None when invalid); `Formula.evaluate(t, x=0.0) -> float | None` (None on
maths error or non-finite). Grammar and functions per spec; length ≤ 160, depth ≤ 32; `^` right-associative,
results capped at ±1e9. Tests: arithmetic and precedence, unary minus, `^` associativity, each function, `t`/`x`,
whitelist rejection (`__import__`, `os`, attribute dots, unknown names, letters like `tt`), malformed input,
division by zero to None, deep nesting rejected, long input rejected.

## Task 2: Scene model (`clicky/scene.py`)
`parse_scene(json_text) -> Scene | None`; `Scene.frame(t) -> list[DrawItem]` (pure, world coordinates) with
`DrawItem(kind, alpha, numbers dict, text, color, label, trail_points)`, plus captions and title. Number properties:
number | formula | keyframes; text and colour: string | stepped keyframes. Start/end with 0.25 s fades. Trails sample
the position over time (≤ 60 points). Limits per spec; invalid objects skipped, invalid scene → None. Tests: spec
example parses; ball position at t=1 matches the formula; keyframe interpolation and holds; stepped text; fades;
plot sampled points between from/to; limits; garbage JSON, wrong types and NaN-producing formulas don't raise.

## Task 3: Scenes in replies (`clicky/visuals.py`, controller)
`<scene name="…">…</scene>` blocks removed from speech and the bubble (a half-streamed `<scene` hides the rest);
`[ANIMATE:name]` becomes a `VisualEvent(kind="animate", text=<scene json>)` only if a block with that name exists;
1 per reply. The controller passes animate events through as `ScreenVisualEvent(kind="animate", text=…)`. Tests.

## Task 4: Whiteboard panel (`clicky/whiteboard.py`)
`WhiteboardWindow`: `play(scene)`, `finish()`, `clear()`, `set_enabled()`. World-to-pixel mapping helper (pure,
tested), axes with ticks, every draw kind, captions and title, trail. Timer at 16 ms while playing, stops after
`duration` holding the last frame; linger then fade like the notepad. Docks left of the notepad column. Offscreen
smoke tests plus a real-font preview render inspected visually.

## Task 5: Director and app wiring
`VisualDirector` gets an `animate` sink (`whiteboard.play(parse_scene(text))`, skipped if None), clear/finish include
the whiteboard. App wiring: whiteboard created and docked, tray "Show notepad" also governs the whiteboard (call:
one "visual aids" toggle). E2E test: a fake Worker reply containing a scene reaches the animate sink with a valid scene.

## Task 6: Clear (Esc + tray)
`KeyTapWatcher(virtual_key, on_tap, is_armed)` in hotkey.py with pure edge detection (`TapDetector.update(down) ->
bool`). Tray "Clear screen" (`clear_requested`). `clear_all()` in app: director.cancel + layer.clear +
notepad.clear + whiteboard.clear + overlay bubble dismissed + buddy returns. Armed while any visual is showing
(layer, notepad or whiteboard visible, or the bubble showing). Tests: detector edges, tray emits, overlay
`dismiss_bubble`, a `clear_all` integration test with fakes.

## Task 7: Prompt
Add ANIMATE and `<scene>` docs and two examples (kinematics formulas; bubble sort keyframes). Test: every scene in
the prompt parses and validates, and its marker fires.

## Task 8: Live check and docs
GPT-6.1 Terra, kinematics question on a blank synthetic screen: the reply's scene parses, frames render to PNGs and
get inspected. README and AGENTS updated. Relaunch Clicky.
