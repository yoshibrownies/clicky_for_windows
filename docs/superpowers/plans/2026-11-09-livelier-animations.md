# Livelier animations — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every scene builds up and moves more, text never collides, at no extra cost per answer.

**Architecture:** `scene.py` gains entrance progress per DrawItem, auto-stagger in `parse_scene`, eased keyframes; `scene_painter.py` uses entrance progress and places text/labels in a second pass with nudging; `prompts.py` gets a few general motion lines.

**Tech Stack:** Python 3.13, PySide6, pytest.

**Spec:** `docs/superpowers/specs/2026-11-09-livelier-animations-design.md`

## Global Constraints
- ENTRANCE_SECONDS = 0.45, STAGGER_SECONDS = 0.18, stagger window 1.2 s, nudge offsets 0, -16, +16, -32, +32 px.
- Never raise on model output; no extra model requests; prompt growth ≤ ~700 chars.

## Review Focus
- A scene where every object has start 0 but is meant to show "before" all at once (stagger is short, ≤1.2 s).
- HIGHLIGHT targeting an object still entering (bounds exist once visible).
- Keyframes with a single frame or zero-length spans.
- Text nudged outside the panel (keep within the plot area).
- Still-image cache: final frame must be fully entered (t = duration).

---

### Task 1: entrances, auto-stagger, eased keyframes (`scene.py`)
**Produces:** `DrawItem.entrance: float` (0..1, eased); constants above.
- [ ] Tests (tests/test_scene.py): `test_objects_ease_in_from_their_start` (entrance 0 at start, 1 after 0.45 s,
  alpha follows); `test_unstaged_scenes_build_up_in_order` (3 objects all start 0 → starts 0, 0.18, 0.36);
  `test_staged_scenes_keep_their_timing`; `test_stagger_fits_in_the_first_seconds` (12 objects → last ≤ 1.2);
  `test_keyframes_ease_between_values` (midpoint = average, quarter point < linear quarter).
- [ ] Implement; full suite; commit `feat(scene): objects ease in, unstaged scenes build up, keyframes ease`.

### Task 2: painter uses entrances and keeps text apart (`scene_painter.py`)
- [ ] Tests (tests/test_scene_painter.py): `test_entering_shapes_are_drawn_smaller` (circle radius scaled while
  entering); `test_arrows_draw_along_their_length_while_entering`; `test_overlapping_texts_are_nudged_apart`
  (two text objects at the same spot → painted rects don't intersect).
- [ ] Implement (second pass for text and labels); full suite; commit `feat(painter): entrances and non-overlapping text`.

### Task 3: prompt motion lines + live check (`prompts.py`)
- [ ] Test (tests/test_prompts.py): `test_prompt_asks_for_motion_and_build_up` (phrases present; prompt growth
  within budget vs the previous length).
- [ ] Implement; full suite; live gallery + metrics before/after; commit `feat(prompt): show the key idea by motion`.
