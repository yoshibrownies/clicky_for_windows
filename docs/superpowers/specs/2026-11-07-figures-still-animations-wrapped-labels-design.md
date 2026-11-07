# Figures that sit exactly, still finished animations, complete diagram labels

Date: 2026-11-07 · Status: draft for Yoshi's approval · Size: a small change (three focused fixes)

## Intent (Yoshi's three asks)
1. Figures sit exactly where they're meant to.
2. A finished animation stops being redrawn every frame and becomes a still image.
3. Text in the boxes of the boxes-and-arrows diagram must never be cut off (seen: labels elided with "…" when boxes
   get narrow), because a cut label makes the explanation incoherent.

Learning comes first; everything stays general (no topic-specific code).

## 1. Figures sit exactly
Today the built-in figures are drawn in a unit box they don't fill (the eye uses only the middle third, so it floats
above its anchor; die, heart, clock and gear float slightly).
- When an icon is built, measure its real drawing and normalise it: the drawing's bottom edge sits at y = 0, it's
  centred on x = 0, and its longer side is 1. So `size` = the figure's longer side, and (x, y) is exactly its
  bottom centre. Rotation turns about that same point. Applies to every icon automatically, now and in future.
- The prompt's icon line says: "size = its longer side; it stands with its bottom centre exactly at x, y".
- Tests: every icon's points span exactly y 0..1 (or x −0.5..0.5 for wide ones) with its bottom at 0.

## 2. Finished animations become still images
Today every animation block on the card is re-evaluated and repainted ~60 times a second while anything on the card
moves, even long after it ended.
- When a block's animation has finished (time ≥ its duration, fully faded in), the card paints it once into an
  offscreen picture (at the screen's pixel ratio, so it stays sharp) and from then on draws that picture.
- Live painting resumes only while a highlight ring is on that block; afterwards it re-caches.
- The cache is dropped when the card is cleared or resized.
- Tests: a finished block is drawn from the cache (the scene isn't re-evaluated on later frames); a highlighted
  finished block paints live; the cached picture matches a live paint.

## 3. Complete diagram labels (approach A, chosen by Yoshi)
- Labels wrap onto up to 3 lines inside their box, breaking between words (a single word longer than the box breaks
  inside the word). Only if 3 lines still don't fit does the font shrink, down to a readable minimum (11 px).
  No "…" while any of that works.
- Boxes grow taller to hold their lines; every box in a diagram gets the same height (neat rows).
- The layout measures the labels first and picks the direction (left to right, or top to bottom) where they fit
  with the least shrinking and wrapping.
- The diagram block on the card grows taller when it needs to (from 190 px up to a cap, about 340 px), so wrapped
  boxes are never squashed.
- Last resort, only past every step above (absurdly long labels in many boxes): "…" as today, so nothing overflows.
- Tests: a long label in a crowded diagram comes back whole across lines; boxes are tall enough for their lines;
  the block grows; short labels stay one line at the normal size.

## Approaches considered (for 3)
- **A. Wrap, then fit (chosen):** always complete and readable; costs some vertical space on the card.
- B. Shrink only: compact, but long labels in crowded diagrams become unreadably small.
- C. Ask for shorter labels: no layout work, but depends on the model and still cuts text.
For 1 and 2 there was one sensible way each (normalise the artwork; cache finished blocks).

## Non-goals
Rectangles and text inside animations (Yoshi saw the problem in diagram boxes); the other deferred review minors.

## Left to the builder
Exact padding, line height, the minimum font size within "readable", and the block height cap.
