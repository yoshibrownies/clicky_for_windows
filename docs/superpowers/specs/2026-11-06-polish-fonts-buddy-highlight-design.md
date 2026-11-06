# Polish: fonts, buddy cursor, no reply bubble, live highlights — design

Date: 2026-11-06. Small change; approved by Yoshi via the brainstorming exchange ("Please do all the following").

## Intent
Yoshi uses Clicky daily and shows it off. Five things looked wrong or cheap after the lesson-card restyle:
1. Fonts: use **Inter** for headlines and body UI text, **Geist Mono** for technical text, code and monospaced UI.
2. The buddy cursor was drawn *behind* the lesson card and animations.
3. The buddy had an ugly white outline and sharp corners.
4. The whole spoken reply was shown in a bubble next to the cursor while Clicky talked.
5. An animated object moved (orbited east → north) and Clicky's red circle "referencing it" stayed at a guessed
   spot, half on the card and half on the desktop, during the same answer.

## Root causes (from reading the code)
- 2: buddy, card, chips and marks are all always-on-top tool windows; Windows stacks the most recently shown on top,
  and the card is shown after the buddy.
- 3: `_paint_buddy` strokes the triangle with a 1.6 px white pen.
- 4: `controller.reply_text_changed` is wired to `overlay.show_reply`.
- 5: the card is excluded from screen capture on purpose, so the model can't see it. It wrote a screen
  `[CIRCLE:…]` guessed from its own scene JSON. A screen mark is static and knows nothing about the animation.

## Approaches considered
- Fonts: (a) bundle the two OFL font files in `clicky/fonts/` and load them at startup (chosen: works on any PC,
  no install step); (b) ask Yoshi to install them system-wide (fragile, breaks for anyone else running it).
- #5: (a) new `[HIGHLIGHT:label]` tag that rings the scene object with that label, tracking its live position
  inside the card (chosen: correct by construction); (b) screenshot the card so the model can see it (it still
  can't predict where a moving object will be when the circle appears); (c) only drop screen marks over the card
  (hides the symptom; Clicky still can't point at moving things). (c) is kept as a safety net alongside (a).

## Design
- **Fonts**: `clicky/fonts/Inter[opsz,wght].ttf`, `GeistMono[wght].ttf` + their OFL licences, from the
  google/fonts GitHub repo. `clicky/fonts.py` loads them once (`load_fonts()`), and `ui_font(px, weight)` /
  `mono_font(px, weight)` return them, falling back to Segoe UI / Consolas if loading fails. Inter replaces the
  handwriting font and Segoe UI everywhere (card title, heading, notes, diagram labels, chips, status pill,
  speech bubble, buddy label, scene labels and captions). Geist Mono: formulas, axis tick numbers, code-like text.
  Typing-out animation stays. The handwriting font helper is removed (wrap/typing helpers stay).
- **Buddy on top**: the card and the chips emit `appeared` when they become visible. The app raises the buddy
  (`overlay.raise_()`) after the card appears, the chips appear or a mark is drawn.
- **Buddy look**: no outline. A rounded-corner triangle (corners softened with a small radius), a soft drop shadow
  and the existing blue glow.
- **No reply bubble**: the reply text is no longer shown by the cursor. Your own words (transcript while you speak)
  and short notices (errors, "didn't catch that") still show.
- **Live highlight**: `[HIGHLIGHT:label]` (up to 4 per reply, label ≤ 40 chars) is timed like other tags. When it
  fires, the card rings the object in the current animation whose label matches (case-insensitive), drawing a red
  ring that grows in over 0.4 s and **follows the object every frame** for 3 s. Circles, points, rects, text and plot
  heads all have bounds. No match → ignored. The pen (buddy) goes to the highlighted object while it is ringed.
- **Safety net**: screen underlines/circles whose box overlaps the visible card are dropped.
- **Prompt**: document HIGHLIGHT; say the card is invisible to the model, so never use UNDERLINE/CIRCLE/POINT on it;
  label any object it will refer to.

## Non-goals
No new animation types, no change to scene language, no change to spoken length.

## Left to the builder
Exact ring colour/width, shadow size, font sizes (keep the current sizes unless they look wrong in Inter).
