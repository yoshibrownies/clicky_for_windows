# Interrupt awareness plan

Spec: `docs/superpowers/specs/2026-11-07-interrupt-awareness-design.md`
Branch: `feat/interrupt-awareness`. Test command: `.venv\Scripts\python -m pytest -q` (venv lives in the main checkout).

Global constraints: Qt objects on the GUI thread; history is thread-safe; keep `tests/test_end_to_end.py` passing;
type hints on public functions; descriptive names.

## Task 1: `heard_part` in visuals.py

Pure function `heard_part(reply_text: str, fraction: float) -> str` (scene blocks already removed by the caller).
- Walk `find_tags` like `parse_visual_reply`; spoken length counts text outside tags; total = rstripped spoken length.
- `cut = fraction * total`. Keep text segments up to `cut`; the segment containing the cut is kept to the end of the
  word being spoken (`\S*`). Closed tags at a spoken offset ≤ cut are kept verbatim, except FOLLOWUP (shown only at the
  end). Unclosed tags are dropped. Stop after the cut segment.
- fraction ≥ 1 → whole text stripped. No spoken words heard (fraction ≤ 0, or only tags) → "".
- Return stripped.

Tests (tests/test_visuals.py): full at 1.0; empty at 0; mid-word cut rounds forward to the word end; tags before the
cut kept and after dropped; FOLLOWUP dropped when cut; tag-only prefix → "".

Commit: `feat(visuals): heard_part cuts a reply at the point speech reached`.

## Task 2: controller remembers only what was heard

- `CompanionReply` gains `transcript: str = ""`, `remembered_text: str = ""`, `remember: bool = False`.
  `_respond` no longer calls `history.add`; it fills these (remember = stop_reason != "refusal").
- GUI thread: `_on_reply_ready` → no audio: `history.add` in full (if remember) as today; with audio: store
  `_speaking_reply = (transcript, remembered_text)` (if remember) and `_heard_fraction = 0.0`, then play.
- `handle_playback_progress(fraction: float)` keeps the max fraction.
- `handle_playback_finished` (RESPONDING) → remember in full.
- `_abort_current_interaction` → before `player.stop()`, take `_speaking_reply` (set None) and, if present, remember
  `heard_part(text, fraction)` + `" … (the user cut me off here)"` when non-empty. Taking it first stops the
  `finished` that `stop()` emits from saving it in full.
- app.py: `player.progress.connect(controller.handle_playback_progress)`.
- Update `test_history_keeps_the_words_not_the_scene_json` to finish playback before reading history.

Tests (tests/test_controller.py): finished → full reply remembered; interrupted at 0.5 by push-to-talk → only the
first part + marker, later NOTE absent; Esc at 0.5 → same; interrupted with no progress → nothing remembered; the next
request's history carries the marker.

Commit: `feat: remember only what was heard when Clicky is cut off`.

## Task 3: prompt and docs

- prompts.py, "how to explain": a bullet explaining the marker (answer the new question directly, go deeper, don't
  restart or finish the old explanation unless asked). Test in tests/test_prompts.py that the prompt mentions the
  exact marker string exported from controller (`CUT_OFF_MARKER`).
- AGENTS.md: one line on history holding only heard text.

Commit: `feat(prompt): explain the cut-off marker; docs`.
