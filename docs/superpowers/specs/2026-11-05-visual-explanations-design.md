# Visual explanations: animated underlines, live notepad, diagrams, smarter answers

Date: 2026-11-05 · Status: Yoshi asked for this ("do all those things, especially animated underlining, simple
explanations, live notepad writing and diagrams") and handed over the design calls. Everything below marked
*(call)* was decided by Claude; Yoshi reviews it in the final report.

## Intent
Clicky felt "dumb" and only pointed. Yoshi wants it to *teach*: explain simply, and while it talks, mark up the
screen and write on a notepad, so the answer is something you watch as well as hear. It's both for daily use and for
showing off, so the animation quality matters.

## Goals
1. **Animated underlines and circles** on the real screen, drawn in time with the speech.
2. **A live notepad**: a paper-style panel where Clicky hand-writes key points while it talks.
3. **Simple diagrams** in the notepad (boxes and arrows) that draw themselves.
4. **Simpler, smarter explanations**: a teaching-style prompt, `medium` effort by default, and a tray "Thinking" menu
   plus GPT-6.1 Sol as a smarter model choice.

## Non-goals
Word-perfect sync (needs ElevenLabs timestamps and a Worker change, so it's a possible follow-up), interactive or
editable notes, saving notes to disk, freehand drawing beyond underline/circle/boxes/arrows.

## Anti-goals
- Clutter or flicker that makes the screen harder to read.
- Marks showing up in Clicky's own screenshots (the model would see its own scribbles).
- Breaking click-through: nothing may ever steal a click or focus.
- Idle CPU drain (no always-on 60 fps timers).
- Malformed model output crashing or freezing the UI.

## Approaches considered
1. **Inline tags in the spoken reply, timed by audio progress** *(chosen, call)*. The model already writes
   `[POINT:…]`, and the same trick extends to `[UNDERLINE:…]`, `[CIRCLE:…]`, `[NOTE:…]` and `[DIAGRAM:…]` placed
   *where in the sentence* they should appear. Each tag's character offset ÷ the spoken length gives a 0..1 fraction,
   fired when audio playback reaches it. Works with both Claude and OpenAI, needs no Worker change, and is testable as
   pure logic.
2. Structured JSON or tool calls for visuals. More robust parsing, but a different flow per provider (OpenAI tool
   calls need the Responses API for Terra) and harder to time against speech. Rejected for now.
3. ElevenLabs word timestamps for exact sync. Changes the Worker's `/tts` route and response format. Deferred as a
   follow-up; approach 1 gets close enough for phrases.

## Design

### Tag grammar *(call)*
Coordinates are screenshot pixels, as for POINT; `:screenN` is optional (default: the cursor screen).
- `[UNDERLINE:x1,y1,x2,y2]`: underline under the on-screen text spanning that box (drawn along the bottom edge).
- `[CIRCLE:x1,y1,x2,y2]`: hand-drawn ellipse around that box.
- `[POINT:x,y:label]`: unchanged (the buddy flies there); now allowed anywhere, not only at the end.
- `[NOTE:short text]`: one line written on the notepad (≤ 80 chars kept).
- `[DIAGRAM:A -> B -> C; B -> D]`: flow diagram, nodes are labels (≤ 24 chars), at most 8 nodes / 10 edges.
- `[POINT:none]` still allowed.
Tags never reach the voice or the bubble. Unknown or malformed tags are dropped silently. Limits: ≤ 6 marks,
≤ 8 notes, 1 diagram per reply.

### Timing
`VisualTimeline` (pure): events sorted by fraction; `due(progress)` returns events whose fraction ≤ progress that
haven't fired. Progress comes from `SpeechPlayer.progress` (position ÷ duration). Without audio (TTS failed), a
QTimer advances progress at about 14 characters/second of spoken text. A small lead (0.03) makes marks appear just
before the words.

### Screen layer *(call)*
`AnnotationLayer`: one frameless, translucent, input-transparent, topmost, capture-excluded window per monitor,
created on demand and hidden when empty. Underlines are drawn left to right over 450 ms with a slight hand-drawn
wobble in highlighter yellow (semi-transparent, 4 px, round caps). Circles are traced over 600 ms in coral red,
2.5 px, with a slightly overshooting ellipse. Marks stay until the reply ends plus 4 s, then fade over 600 ms.
A new interaction clears everything. The timer runs only while something is animating or fading.

### Notepad *(call)*
`NotepadWindow`: a paper-style panel (cream, faint ruled lines, red margin line, soft shadow, rounded corners), about
340×420 logical px, docked on the right side of the cursor's monitor below the top edge. Click-through and
capture-excluded like the rest. The title strip says "clicky's notes". Notes are written character by character in
Ink Free (handwriting font, falling back to Segoe Print) at about 45 chars/s, each line prefixed with "•".
Diagrams draw below the notes: nodes as rounded boxes appearing one by one, then arrows drawn as growing lines with
arrowheads; layered left-to-right layout (longest-path layering, ordered within a layer by first appearance); wraps
to top-to-bottom if it's too wide. It appears with the first NOTE/DIAGRAM, lingers 20 s after the reply ends, then
fades. A tray toggle "Show notepad" turns the feature off.

### Smarter and simpler *(call)*
- The prompt is rewritten as a teacher: plain words, one idea at a time, an analogy when it helps. Keep speech short
  but put structure on the notepad (2–5 NOTE lines for anything with steps or parts, a DIAGRAM for processes and
  relationships), and underline the exact on-screen thing being discussed. With examples.
- Default effort `medium`. The tray gets "Thinking: Fast / Balanced / Deep" (low / medium / high), changeable live.
- Models: add `gpt-6.1-sol` ("GPT-6.1 Sol (OpenAI, smartest)").
- `max_tokens` stays 4096 (enough for the tags).

### Data flow
Controller (asyncio side) parses the finished reply → `VisualReply(spoken_text, events)` → screen-space events
(mapped through `map_image_point_to_screen` per corner) travel in `CompanionReply.visual_events`. GUI side:
`visuals_ready(events)` signal → `VisualDirector` (GUI object) owns the timeline, listens to player progress, and
dispatches due events to the `AnnotationLayer` (underline/circle), `NotepadWindow` (note/diagram) and `BuddyOverlay`
(point). `state_changed` to idle starts the linger and fade; `listening` clears.

## Testing
Pure: tag parsing (all kinds, inline offsets, malformed, limits, screen numbers), diagram parsing and layout,
timeline. Controller: events mapped and attached; no visuals → unchanged behaviour. GUI (offscreen): layer and
notepad construct, animate and paint every state; timer stops when idle. End to end: a fake Worker reply with tags
produces events in order. Live: a synthetic screenshot with text checks underline placement (no user screen).
