# Exact figures, still finished animations, complete diagram labels — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Figures sit exactly at their anchor, finished animations are drawn once as still pictures, diagram labels are never cut off.

**Architecture:** Icons are normalised once when built (`icons.py`). Diagram layout (`diagram.py`, pure) learns to wrap and fit labels given a text-measuring function and reports the height it needs; the lesson card sizes the diagram block from it. The card caches each finished animation block as a QPixmap.

**Tech Stack:** Python 3.13, PySide6, pytest (offscreen Qt).

**Spec:** `docs/superpowers/specs/2026-11-07-figures-still-animations-wrapped-labels-design.md`

## Global Constraints
- Labels: up to 3 lines per box; font shrinks only after that, minimum 11 px (normal 13 px); "…" only as a last resort.
- Diagram block height: from 190 px up to 340 px.
- Icon `size` = the figure's longer side; (x, y) = its exact bottom centre; rotation about that point.
- Still image at the screen's pixel ratio; live painting only while a highlight ring is on that block.
- Stay general: no topic-specific code. Keep `tests/test_end_to_end.py` passing.

## Review Focus
- A diagram whose single label is one very long word (no spaces) — it must break inside the word, not overflow.
- A diagram with 8 boxes in one layer — boxes still readable, block grows to the cap, nothing overflows.
- Highlight arriving on an already-finished (cached) animation — ring must appear and follow the object.
- A very wide icon (eye) at a given size — width equals size, not larger.
- Card faded/cleared and reused — no stale picture from a previous reply.

---

### Task 1: Icons sit exactly

**Files:** Modify `clicky/icons.py` (`_build_icon`), `clicky/prompts.py` (icon line). Test: `tests/test_icons.py`.

**Interfaces:** Produces `icon_subpaths(name) -> Subpaths | None` with normalised points (unchanged signature).

- [ ] Step 1: failing test `test_every_icon_sits_on_its_anchor_and_fills_its_size` (parametrised over ICON_NAMES): min y == 0 (abs 1e-9); max(height, width) == 1 (abs 1e-9); (min x + max x)/2 == 0 (abs 1e-9). Plus `test_the_prompt_describes_icon_size_as_the_longer_side`: "longer side" and "exactly at x, y" in the lowered prompt.
- [ ] Step 2: run → FAIL.
- [ ] Step 3: in `_build_icon`, after collecting subpaths, compute the bounding box over all points and map each point to `((x - centre_x) / longest, (y - min_y) / longest)`. Prompt: replace "size = its height in y-axis units, standing with its bottom centre at x, y" with "size = its longer side in y-axis units; it stands with its bottom centre exactly at x, y".
- [ ] Step 4: run icons/scene/painter/prompts tests → PASS (adjust the old unit-box test to the new bounds).
- [ ] Step 5: commit `fix(icons): figures sit exactly on their anchor; size is the longer side`.

### Task 2: Complete diagram labels

**Files:** Modify `clicky/diagram.py` (`layout_diagram`, `DiagramLayout`), `clicky/lesson_card.py` (`set_diagram`, `_diagram_area`, `_paint_diagram`, pen position). Test: `tests/test_diagram.py`, `tests/test_lesson_card.py`.

**Interfaces:**
- Produces `layout_diagram(diagram, width, height, measure: Callable[[str], float] | None = None) -> DiagramLayout`.
  `measure(text)` = width in px at the normal 13 px font. `DiagramLayout` gains `lines: dict[int, tuple[str, ...]]`,
  `font_scale: float` (1.0 … 11/13), `needed_height: float`. Without `measure`, behaviour is as today (one line each).
- Constants in diagram.py: `MAX_LABEL_LINES = 3`, `LABEL_LINE_HEIGHT = 17.0`, `LABEL_PADDING = 10.0`,
  `MIN_FONT_SCALE = 11 / 13`. In lesson_card.py: `MAX_DIAGRAM_BLOCK_HEIGHT = 340`.

- [ ] Step 1: failing tests in `tests/test_diagram.py` with a fake measure `lambda text: 7.0 * len(text)`:
  `test_long_labels_wrap_instead_of_being_cut` — 5 chained nodes each "short term memory store" in width 388:
  every node's joined lines == its label (no "…"), every line's measure ≤ box width − LABEL_PADDING, box height ≥
  len(lines) × LABEL_LINE_HEIGHT; `test_one_long_word_breaks_inside_the_word` — label "electroencephalography"
  in a 4-wide row: joined (no spaces) == the word; `test_short_labels_stay_one_line_at_full_size` — font_scale == 1
  and one line each; `test_needed_height_grows_with_wrapped_boxes` — needed_height of the long-label diagram >
  that of the short one; `test_eight_boxes_in_a_layer_fit` — one root → 8 children with 20-char labels: all labels
  complete, needed_height reported.
- [ ] Step 2: run → FAIL.
- [ ] Step 3: implement. For each orientation and each scale in (1.0, 0.92, MIN_FONT_SCALE): box width from `fit`
  (as today); wrap each label with `handwriting.wrap_text(label, lambda s: measure(s) * scale, box_width −
  LABEL_PADDING)`; candidate fits if every label has ≤ MAX_LABEL_LINES lines. Box height (same for all boxes) =
  max(BOX_HEIGHT, max_lines × LABEL_LINE_HEIGHT × scale + 12). needed_height = boxes stacked along y plus gaps.
  Choose: the first scale (largest) where some orientation fits; between orientations prefer fewer max lines, then
  the existing roominess score. If nothing fits at MIN_FONT_SCALE: use MIN_FONT_SCALE, keep the first 3 lines and
  elide the last with "…" (measure-based). Place boxes using the chosen box height in a drawing area whose height
  is max(height, needed_height) (centred as today).
- [ ] Step 4: card. `set_diagram` computes the layout once at the card's inner diagram width with
  `QFontMetricsF(self._label_font).horizontalAdvance` and sets the block height to
  clamp(needed_height + 16, DIAGRAM_BLOCK_HEIGHT, MAX_DIAGRAM_BLOCK_HEIGHT); store it on the block
  (`_Block.diagram_layout`). `_diagram_area(top, block)` uses block.height − 16. `_paint_diagram` and the pen
  position use the stored layout; labels draw line by line, centred, with the font at 13 × font_scale px.
  Test `test_a_diagram_with_long_labels_gets_a_taller_block` in tests/test_lesson_card.py: block height > 190 and ≤ 340.
- [ ] Step 5: run full suite → PASS.
- [ ] Step 6: commit `fix(diagram): labels wrap and fit instead of being cut off; diagram grows to hold them`.

### Task 3: Finished animations become still images

**Files:** Modify `clicky/lesson_card.py` (`_Block`, `_paint_animation`). Test: `tests/test_lesson_card.py`.

**Interfaces:** `_Block.still: QPixmap | None = None`; no public API change.

- [ ] Step 1: failing tests: `test_a_finished_animation_is_drawn_from_a_still_picture` — play a 0.2 s scene, paint
  the block via `card._paint_animation(painter, block, top, now)` into a QImage at now = starts_at + 1 twice, with
  `block.scene.frame` wrapped to count calls: calls after the first paint == 0 and `block.still` is not None;
  `test_a_highlight_on_a_finished_animation_paints_live` — after caching, `card.highlight(label)`, paint again:
  frame is called and the ring rect (`card._scene_painter.highlight_rect`) is not None;
  `test_still_picture_matches_live_painting` — pixel at the scene object's centre is the same colour in cached and
  live paints (tolerance 8 per channel).
- [ ] Step 2: run → FAIL.
- [ ] Step 3: implement: finished = elapsed ≥ duration and fully faded in and not highlighted. On first finished
  paint (or if the cached size ≠ the area size), render panel + scene at t = duration into a transparent QPixmap of
  area size × `self.devicePixelRatioF()` with that pixel ratio set; afterwards `drawPixmap(area.topLeft(), still)`.
  Highlighted → paint live and drop the still (re-cached once the ring ends).
- [ ] Step 4: run full suite → PASS; ruff clean.
- [ ] Step 5: commit `perf(card): finished animations are drawn once as still pictures`.
