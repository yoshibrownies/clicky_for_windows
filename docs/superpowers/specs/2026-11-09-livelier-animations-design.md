# Livelier, cleaner animations at no extra cost

Date: 2026-11-09 · Status: Yoshi asked to "determine the best way and execute" (how handed over) · Size: small project

## Intent
Better animation quality: animate more things, at higher quality, while keeping answers fast and cheap.

## Evidence (real scenes, gpt-6.1-terra, 4 questions, 8 scenes, 43 objects)
- Only 21% of objects move; only 14% appear after the start. Frames at 25%/50%/100% look the same except the caption.
- Text collides ("output: 2 turnsinput: 1 turn"); labels sit on shapes.
- Plain circles where the `gear` figure would fit.

## Approaches considered
1. **Drawing-engine polish + small prompt nudges (chosen).** Engine changes cost nothing per answer and apply to every
   scene; a few general prompt lines push the model toward motion. No extra requests, no bigger model.
2. Bigger model or higher effort: likely better scenes, but slower and costlier (rejected by the brief).
3. A second "critique and redraw" request per scene: better scenes, but doubles latency and cost (rejected).

## Design
Engine (`scene.py`, `scene_painter.py`):
- **Entrances:** each object eases in over ENTRANCE_SECONDS (0.45 s) from its start: shapes fade and grow from 70%,
  lines/arrows draw along their length, text fades. (Today: a 0.25 s fade, and none at t=0.)
- **Auto build-up:** when a scene gives no object a start time (and has 3+ objects), objects appear in listed order,
  STAGGER_SECONDS (0.18 s) apart, all within the first 1.2 s. Scenes that set start times keep them.
- **Eased keyframes:** keyframe motion uses smoothstep easing instead of constant speed.
- **Readable text:** labels and text objects are placed after shapes and nudged vertically (±16/32 px) to avoid
  overlapping text already placed.
Prompt (`prompts.py`, a few general lines): show each step's key idea by motion (things travel, turn, grow, flow,
change); reveal objects in the order you mention them (start times); prefer a stock figure when one fits (rotate a
gear to turn it); keep labels short and apart.

## Checks
Unit tests for each engine change; live before/after with the same questions: % moving, % appearing later, average
reply length (must not grow meaningfully), rendered gallery.

## Non-goals
New object types; a second model call; changing the model.
