# Moving graphics (Clicky's animation language) and a clear-screen control

Date: 2026-11-06 · Status: Yoshi chose approach A ("the small animation language that Clicky writes and your renderer
plays") and asked for a way to clear everything on screen. Calls marked *(call)* are Claude's; Yoshi reviews them
in the final report.

## Intent
Explanations should *move*: a ball speeding up while its velocity arrow grows and a graph plots itself; a list being
sorted step by step; a neuron firing; a supply curve shifting. The topics are wide, so Clicky invents a fresh
animation per question instead of picking from a fixed set. And Yoshi wants to wipe the screen on demand.

## Goals
1. A **scene language** the model writes per answer, played by Clicky's own renderer on a **whiteboard** panel,
   timed to start at the right moment in the speech.
2. General enough for physics, maths, algorithms, biology, economics: shapes, arrows, text, axes and plotted
   functions, moving by **formulas of time** or **keyframes** (step by step).
3. **Safe**: nothing the model writes is executed as code. Formulas go through a whitelisted maths evaluator.
4. **Clear everything**: Esc (while Clicky's visuals are showing) and a tray "Clear screen" item remove marks,
   notes, diagrams, the whiteboard and the bubble immediately.

## Non-goals
3D, physics engines, user interaction with the animation (pause/scrub), sound, saving animations.

## Anti-goals
- Running model-generated code. Any freeze, hang or crash from a bad scene.
- An always-on 60 fps timer. A cluttered panel that covers what's being explained.
- Breaking click-through. Clear must never need a click.

## Approaches considered
A. **Scene language + own renderer** (chosen by Yoshi): flexible, safe, consistent look; the model sometimes lays things
   out clumsily, mitigated by building blocks (axes, plots, arrows, keyframes) and good prompt examples.
B. Fixed templates with parameters: polished but can't cover "much wider" topics.
C. Model-written code in a sandboxed browser panel: most flexible, but executes generated code, +~200 MB, slower, buggier.

## Design

### How a reply carries a scene *(call)*
JSON needs square brackets, which can't live inside the inline `[...]` tags. So:
- An inline marker `[ANIMATE:name]` sits where the animation should start in the speech (timed like NOTE).
- The scene itself is a block anywhere in the reply: `<scene name="name">{ ...JSON... }</scene>`. The parser removes
  these blocks from speech and from the streaming bubble (including a half-streamed block).
- 1 animation per reply. An unknown name or invalid JSON → no animation, never an error.

### Scene JSON *(call)*
```json
{
  "title": "a dropped ball speeds up",
  "duration": 6,
  "world": {"x": [0, 10], "y": [0, 50]},
  "axes": {"x": "time (s)", "y": "distance fallen (m)"},
  "objects": [
    {"type": "circle", "x": 2, "y": "50 - 4.9*t^2", "r": 10, "color": "blue", "label": "ball", "trail": true, "end": 3.2},
    {"type": "arrow", "x": 2, "y": "50 - 4.9*t^2", "dx": 0, "dy": "-0.5*9.8*t", "color": "red", "label": "v"},
    {"type": "plot", "fn": "4.9*x^2", "from": 0, "to": "min(t, 3.2)", "color": "green"},
    {"type": "text", "x": 6, "y": 44, "text": "d = ½·g·t²", "size": 16},
    {"type": "rect", "x": 1, "y": 0, "w": 2, "h": [[0, 1], [2, 5]], "color": "orange"},
    {"type": "line", "x1": 0, "y1": 25, "x2": 10, "y2": 25, "color": "gray", "dashed": true}
  ],
  "captions": [{"at": 0, "text": "let go…"}, {"at": 1.5, "text": "faster every second"}]
}
```
- `world` sets the coordinate system (y points up); objects use world units except `r` and `size` (pixels).
- **Numeric properties** are a number, a formula string in `t` (seconds since the scene started; `x` is also available
  inside `plot.fn`), or **keyframes** `[[time, value], ...]`, linearly interpolated (held before the first and after
  the last). **Text and colour** may be keyframes too (stepped, not blended): `[[0, "compare 5 and 2"], [1, "swap"]]`.
- Each object may have `start` / `end` (seconds) and fades in or out over 0.25 s.
- Types: `circle`, `rect`, `line`, `arrow`, `text`, `plot` (y = fn(x) drawn from `from` to `to`, both animatable),
  `point` (small dot with label). `trail: true` on circle/point leaves a faint path.
- Colours: a named palette (blue, red, green, orange, purple, teal, gray, black, yellow) for a consistent look.
- Limits: at most 40 objects and 8 captions; duration from 1 to 30 s (clamped); formula length up to 160 characters.
  Invalid objects are skipped and the rest still play.

### Formula evaluator *(call)*
A recursive-descent parser over a token whitelist: numbers, `t`, `x`, `pi`, `e`, `+ - * / ^`, parentheses,
unary minus, and the functions `sin cos tan asin acos atan sqrt abs exp log min max floor ceil round clamp(v,lo,hi)
lerp(a,b,u) step(edge,v) mod(a,b)`. It compiles once to an AST and is evaluated per frame. Guards: length, nesting
depth (≤ 32), exponent results capped, and any maths error or non-finite value gives "hide this object this
frame". No `eval`, no attribute access, no names outside the whitelist.

### Whiteboard panel *(call)*
A paper-white panel (faint grid, rounded corners, soft shadow), about 520×390 logical px, docked to the left of the
notepad's column on the cursor's monitor (or the right edge when there's no room). Click-through,
capture-excluded, topmost. The title shows at the top and captions at the bottom, fading in and out. Axes have
ticks and labels. Objects are drawn in the palette with round line ends; labels sit beside their objects. 60 fps
while the scene plays, then it holds the last frame (timer stopped), lingers 20 s after the reply ends, then fades.
Replaying the same scene isn't needed.

### Clear *(call)*
- `KeyTapWatcher` (hotkey.py): polls `VK_ESCAPE` every 50 ms on its own thread and reports a press edge. It's armed
  only while something of Clicky's is visible, so Esc in other apps does nothing otherwise. Esc still reaches the
  other app, because polling can't swallow keys; acceptable *(call)*.
- Tray "Clear screen" item.
- `clear_all()`: director.cancel, annotation layer clear, notepad clear, whiteboard clear, buddy bubble dismissed,
  and the buddy returns to the cursor. Speech keeps playing *(call: clearing visuals shouldn't silence an answer the
  user is listening to; talking over Clicky already stops speech)*. *Changed 2026-11-07 at Yoshi's request: Esc now also stops speech; the tray item still doesn't.*

### Prompt
A new tool line plus two full examples (kinematics with formulas, sorting with keyframes). When to animate: motion,
change over time, step-by-step processes. Keep it 3–12 s, label things, fill the world range sensibly, and one
animation per reply. The examples are tested: they must parse and validate.

## Testing
Evaluator (maths, precedence, whitelist rejection, errors to None, depth/length guards). Scene parsing and
validation (every type, keyframes numeric and stepped, limits, malformed parts skipped, frame evaluation at several
t). Reply extraction (block removal, marker timing, half-streamed block hidden). Whiteboard offscreen smoke (plays,
stops its timer, holds the last frame, fades; renders a non-empty image) plus a real-font preview render to inspect.
Clear: watcher edge detection (pure), tray emits, `clear_all` reaches every sink. End to end: a fake Worker reply
with a scene reaches the whiteboard sink. Live: GPT-6.1 Terra answers a kinematics question with a valid scene,
rendered to PNG frames and inspected.
