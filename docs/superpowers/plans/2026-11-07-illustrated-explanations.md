# Illustrated explanations plan

Spec: `docs/superpowers/specs/2026-11-07-illustrated-explanations-design.md`
Branch `feat/illustrated-explanations`. Test: `.venv\Scripts\python -m pytest -q` (main checkout's venv).
Global: pure parsing in scene.py (no Qt), never raise on model output, no eval; GUI thread for painting.

## Task 1: path data parser (new `clicky/paths.py`)
`parse_path_data(d: str) -> list[list[tuple[float, float]]] | None`: tokenizer (command letters MLHVCQZ/mlhvcqz,
numbers incl. exponent), absolute/relative, implicit repeats, flattens C/Q into 12 points each, Z closes. Limits:
MAX_PATH_LENGTH 2000 chars, MAX_PATH_COMMANDS 200; unknown letters, missing numbers or non-finite → None.
`polyline_length`, `partial_subpaths(subpaths, fraction)` (first fraction of total length, last segment cut).
Tests: absolute/relative lines, H/V, cubic endpoints, Z closes, implicit lineto after M, invalid → None, limits,
partial at 0 / 0.5 / 1.
Commit `feat(paths): whitelisted path-data parser and partial drawing`.

## Task 2: icon library (new `clicky/icons.py`)
`ICONS: dict[str, str]` of path data in a unit box (x −0.5..0.5, y 0..1, bottom-centre anchor):
person, head, brain, neuron, synapse, lightbulb, clock, gear, eye, die, domino, heart. `icon_subpaths(name)` cached.
Tests: every icon parses, fits the unit box (±0.05), has ≥1 subpath; unknown → None.
Commit `feat(icons): built-in figures for illustrations`.

## Task 3: scene objects path, icon; rotate, opacity, draw, fill
scene.py: REQUIRED/OPTIONAL numbers for `path` (x, y; scale 1, rotate 0, draw 1) and `icon` (x, y; size 1, rotate 0,
draw 1); `rotate` optional on rect; `opacity` optional (1) on all kinds; `fill` (palette or "none") stepped text on
rect/circle/path/icon; `pivot` on rect. SceneObject gets `subpaths`, `fill`, `pivot`. `_draw_object` emits world-space
`segments` for path/icon: transform (scale → rotate → translate), then `partial_subpaths(draw)`; alpha × opacity.
DrawItem gets `fill`, `closed` flags per segment. Tests: parse/frame for each; invalid d/name skipped; rotate 90 maps
points; draw 0.5 halves length; opacity scales alpha.
Commit `feat(scene): paths, icons, rotation, opacity, sketch-in drawing`.

## Task 4: painting
scene_painter.py: path/icon → polylines (closed subpaths filled with `fill` at 0.35·alpha·draw-progress), pen 2.6;
rect rotation via painter transform about pivot; circle/rect fill override; bounds for highlights and focus point
(path/icon bounds = bounding box of drawn points; head of a partially drawn outline is the focus point).
Tests: painting a scene with every new kind into a QImage doesn't raise and sets bounds/highlight; painted pixels
appear where the icon is.
Commit `feat(painter): draw paths, icons and rotated shapes`.

## Task 5: several animations per reply + prompt
visuals.py MAX_ANIMATIONS = 4; prompt: object list gains path/icon (names)/rotate/opacity/draw/fill; limits line says
4 animations; a "follow your train of thought" bullet; a determinism example with two scenes using icons, path, draw
and rotate (must parse and fire, via existing test). Update test expecting extra animations dropped. Tests:
prompt mentions every icon name; limit text matches MAX_ANIMATIONS.
Commit `feat: up to four animations per answer that follow the explanation; prompt teaches drawing`.

## Task 6: docs
AGENTS.md line; README feature bullet.
Commit `docs: illustrated explanations`.
