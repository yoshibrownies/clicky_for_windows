# Lesson card restyle: one soft-green card, top status pill, cursor follows the pen, follow-up chips

Date: 2026-11-06 · Status: Yoshi asked for this with two reference screenshots (during and after an answer about drag):
"softer green colour, the top bar while speaking/active, cursor following thought, longer more intelligent answers and the
after options for follow up questions." Calls marked *(call)* are Claude's.

## What the references show
- One card at the side of the screen: a muted green-grey **title bar** ("drag forces"), pale sage paper, a big
  handwritten **heading** ("What slows you down?"), an inline **diagram/animation** (an ellipse with labelled
  Drag/Motion arrows, animated bars showing v→F and 2v→4F), a **formula** line ("F_D = ½ρC_DAv²"), and a short
  **legend** ("ρ: density  C_D: shape …").
- A green triangle cursor sitting where the drawing is happening.
- After the answer: green **follow-up chips** ("Explain terminal speed", "Try a calculation").
- At the top of the screen, a dark **"Speaking"** pill with a small waveform/logo while Clicky is active.

## Goals
1. A **LessonCard** replaces the separate notepad and whiteboard, in a softer green style: title bar, heading,
   notes, formulas, a diagram and an animation, all written into one card in reading order as Clicky speaks.
2. A **top status pill** (Listening / Thinking / Speaking with a waveform) at the top centre of the cursor's screen
   while not idle.
3. **Cursor follows the pen**: while the card writes or draws, the buddy glides to the spot being written; when the
   reply ends it returns to the mouse.
4. **Follow-up chips** (up to 3) under the card after the answer. Clicking one asks that question immediately as
   typed text: fresh screenshot, no microphone.
5. **Longer, more intelligent answers**: the prompt asks for real explanations (several sentences with structure, an
   intuition, an example), a card for anything non-trivial, and follow-ups. Output budget raised.

## Non-goals
Free typing of questions, chip editing, card scrolling or interaction other than the chips, saving cards.

## Anti-goals
- Anything other than the chips catching clicks or focus. The chips window never steals keyboard focus.
- Copying another product's exact look: the style is inspired by the references (sage paper, green accents,
  handwritten type), not pixel-copied *(call)*.
- Idle CPU (timers stop when nothing moves). Breaking any existing behaviour: underlines and circles, Esc clear,
  interrupting, the voice.

## Approaches considered
1. **New LessonCard that reuses the notepad text/diagram code and the whiteboard scene renderer** *(chosen, call)*:
   one window and one layout model, and the existing tested pieces carry over.
2. Restyle the two existing windows and dock them together. Cheaper, but the references clearly show a single card
   with mixed content in reading order; two windows can't interleave heading, animation and formula.
3. An HTML card in a web view. Easy styling, but a ~200 MB dependency, and click-through/animation sync get harder.

## Design

### New tags *(call)*
- `[TITLE:drag forces]`: the card's title bar (≤ 40 chars). `[HEADING:What slows you down?]`: big handwritten line
  (≤ 60 chars). `[FORMULA:F = ½ρCv²]`: one larger maths line (≤ 60 chars). Notes keep `[NOTE:…]` (legend lines like
  "ρ: density, C: shape" are notes). `[FOLLOWUP:Explain terminal speed]`: up to 3, ≤ 40 chars, shown as chips after
  the speech ends. Diagram and `[ANIMATE]` stay; both now draw inside the card.
- Limits: 1 title, 1 heading, 3 formulas, 3 follow-ups (plus the existing ones).

### LessonCard *(call)*
- About 420 logical px wide; height grows with content (capped to 88% of the screen; oldest blocks scroll off the
  top). Docked at the right of the cursor's monitor.
- Style: sage paper `#EEF3EE`, title bar `#D5E0D6` with dark green-grey title text, ink `#1F2933`, accents green
  `#2F9E67`, red `#E0564F` and blue `#3B6FD8`. Rounded 16 px, soft shadow. Heading in the handwriting font at 26 px
  bold; notes 18 px; formula 24 px; legend notes in grey.
- Blocks in arrival order: heading, note, formula, diagram (190 px tall), animation (240 px tall, the scene rendered
  inline with the whiteboard painter, white plot area replaced by paper). Text types at about 45 chars/s;
  diagrams/animations reveal as before.
- `writing_point` signal: the global position of the pen (the end of the text being typed, the last node drawn,
  or the animation's most-moved object). Emitted at most 30×/s while writing.
- Lingers 20 s after the reply, then fades; Esc/clear fades quickly. Click-through and capture-excluded.

### Follow-up chips *(call)*
A separate small window under the card (not click-through), pill buttons in green with a speech icon, shown when the
reply ends. Clicking one hides the chips and calls `controller.ask_typed(text)`. They hide on the next push-to-talk,
on clear, and when the card fades. `WA_ShowWithoutActivating` + `WindowDoesNotAcceptFocus`, so clicking doesn't take
keyboard focus away from your app.

### Typed questions
`CompanionController.ask_typed(text)`: same pipeline minus transcription (abort the current interaction, capture
screens, processing state, Claude/GPT, TTS, visuals). The transcript shown and stored is the chip text.

### Top status pill *(call)*
A dark rounded pill (about 190×36) at the top centre of the cursor's screen: the Clicky triangle in green, then
"Listening" with live bars, "Thinking" with three pulsing dots, or "Speaking" with animated bars. It fades in on
leaving idle and out 0.6 s after idle. Click-through, capture-excluded, timer only while visible.

### Cursor follows the pen
`BuddyOverlay.guide_to(x, y)`: while guided, the buddy eases toward the point instead of the mouse (no bubble
change). `release_guide()` returns it via a return flight. The app connects `card.writing_point → overlay.guide_to`
while responding; on idle or a new press → `release_guide`. An explicit POINT flight takes priority over guiding.

### Longer answers
Prompt: "explain properly: 4 to 8 spoken sentences for a real question (more if asked), build intuition, give a
concrete example; for anything non-trivial build a card: title, heading as a question, notes/formula/diagram or
animation, and 2 to 3 follow-ups." `DEFAULT_MAX_TOKENS` goes from 4096 to 8192. Effort stays Balanced by default.

## Testing
Tag parsing (new kinds, limits, follow-ups fire at the end). Card: block layout, typing progress, writing_point
emission, scrolling cap, timers stop, preview renders inspected. Chips: click emits the text and hides; no focus
flags. ask_typed runs the pipeline without transcription. Pill: state changes, fades, timer stops. Overlay guide
mode. Prompt examples parse. E2E: a fake model reply with every new tag reaches the card and chips sinks. Live
check with GPT-6.1 Terra plus a rendered preview.
