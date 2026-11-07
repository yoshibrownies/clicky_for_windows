# Illustrated explanations: pictures that follow the train of thought

Date: 2026-11-07 · Status: approved by Yoshi in chat ("That is exactly what I want ... Priority however is always
aiding learning.")

## Intent
When Clicky explains something abstract (determinism: every choice is the end of a chain of prior causes) or physical
(the hippocampus, synapses), Yoshi wants drawn illustrations and animations that build up step by step as Clicky
talks, so the picture follows the explanation and helps him think. Animations stay: they aid thinking and make the
experience feel good. **Learning comes first**: a visual earns its place by making the idea clearer, not by decorating.

## Decided in chat
- Drawn illustrations in Clicky's own style that move, light up and build piece by piece (Yoshi: "exactly what I
  want"). Real images from the web: not now (maybe later, only for physical things like anatomy).
- Animations remain central; priority is aiding learning.

## Today (constraints found)
- Scene language (`scene.py`): circle, point, rect, line, arrow, text, plot; numbers can be formulas or keyframes;
  objects have `start`/`end` with fades. No curves, outlines, rotation or figures.
- One animation per reply (`MAX_ANIMATIONS = 1`). The lesson card already stacks blocks and scrolls to the newest, and
  `HIGHLIGHT` targets the newest animation, so several animations per reply fit the card as it is.
- Formulas only through `expressions.compile_formula`; every prompt example must parse (tested); prompt limits must
  match `visuals.py` MAX_*.

## Approaches (builder's call, since Yoshi talked outcomes and handed over the how)
1. **Extend the JSON scene language (chosen).** Add a `path` object (SVG-style path data, parsed by a small
   whitelisted parser), a built-in `icon` library of simple figures (person, head, brain, neuron, …) drawn from the
   same path machinery, and `rotate`, `opacity`, `draw` (how much of an outline is drawn, so figures sketch themselves)
   and `fill` on shapes. Allow up to 4 animations per reply so each step of the explanation gets its own picture.
   Keeps one safe, testable language the model already writes, timed to speech by the existing director.
2. Model writes raw SVG rendered by QtSvg. Rich, but Qt's SVG animation support is minimal, so it can't build up in
   step with speech, and it is a second language to validate.
3. Image generation API. Detailed pictures, but costly (US$10/month cap), slow, static, and can't follow the speech.

## Design
- `path`: `{"type": "path", "d": "M 0 0 C 1 2 3 2 4 0 Z", "x", "y", "scale", "rotate", "draw", "opacity", "fill",
  "color", "label"}`. `d` uses world units relative to (x, y), y up. Commands M L H V C Q Z, absolute and relative.
  Curves are flattened to points in pure Python; `draw` (0..1) draws that fraction of the outline's length, fill fades
  in with it. Limits on command count and length; invalid paths are skipped (never raise).
- `icon`: `{"type": "icon", "name": "person", "x", "y", "size", ...same optional keys}`. A small curated library of
  outlines in a unit box (bottom-centre anchored), drawn as paths. Unknown names are skipped.
- `rotate` (degrees, counter-clockwise, animatable) on rect, path and icon; rect pivots at its bottom-left unless
  `"pivot": "bottom-right"` or `"center"` (dominoes tipping over). `opacity` (0..1, animatable) on every object.
  `fill` on rect, circle, path, icon (a palette colour or "none").
- Up to 4 animations per reply (`MAX_ANIMATIONS = 4`); the card stacks them, newest at the bottom.
- Prompt: teach the new objects and icon names, and to follow the train of thought: a short scene for each step,
  each building on the last (same objects carried forward, the new idea added and highlighted). Keep scenes small
  so replies stay fast. One new tested example (determinism: a chain of causes leading to a person's "choice").

## Revision (2026-11-07, Yoshi: "Do not overfit this code. I want it to be general, able to adapt to any question.")
- The determinism worked example is removed from the prompt; topics in the brief were illustrations of the need, not
  content to build in.
- The icon library keeps only general-purpose figures (person, head, eye, lightbulb, clock, gear, die, heart);
  brain, neuron, synapse and domino are gone. Anything subject-specific is drawn by the model with `path`.
- The prompt teaches a method instead of a picture: for each step, invent the picture that makes it click (the thing
  itself, how it moves, how parts connect or cause each other, or how much); no stock picture for any topic.
- Tests guard this: the prompt's icon list matches the library, and the library stays small and topic-free.

## Non-goals
Real photos or textbook images; image generation; changes to the Worker; a separate drawing window.

## Anti-goals
Pretty but confusing visuals; replies that get noticeably slower; any `eval`; overlay windows losing click-through or
capture exclusion.

## Left to the builder
Icon artwork, exact limits, timings, rendering details.
