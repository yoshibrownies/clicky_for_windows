# Movable lesson card, card dodges marks, Win+Alt hotkey — design

Date: 2026-11-06. Small change. Yoshi approved approach (a) for marks ("do solution A").

## Intent
1. Yoshi can't interact with the lesson card. Make it movable.
2. Clicky underlined something on screen that ended up hidden behind the card.
3. Change the push-to-talk hotkey from Ctrl+Alt to Win+Alt.

## Findings
- The card is fully click-through (`WindowTransparentForInput`, `WA_TransparentForMouseEvents`).
- Clicky can't see its card (excluded from capture), so it marks text under it. The safety net drops a mark only if
  the card is already up; a mark drawn before the card appears ends up under it.
- The hotkey parser already supports `win`. `.env.example` sets `CLICKY_HOTKEY=ctrl+alt`, so a `.env` copied from it
  overrides the default; `.env` is read-denied to Claude, so Yoshi changes that line himself.

## Approaches (#2)
- (a) **chosen**: the card slides out of the way (to the other side of the screen) when a mark lands under it, and a
  new card docks away from marks already on screen. Overrides a position Yoshi dragged it to: seeing the mark wins.
- (b) draw the mark on top of the card: rejected, the marked thing stays hidden.
- (c) drop the mark (current safety net): rejected, the explanation loses its pointer.

## Design
- **Card input**: the card takes mouse input but never keyboard focus (`WindowDoesNotAcceptFocus`,
  `WA_ShowWithoutActivating`, like the chips). Drag by the title bar (open-hand / closed-hand cursor). A small `×` at
  the right of the title bar clears the card (normal clear fade). Mouse wheel scrolls the content; new writing
  snaps back to following the newest line. Clicks elsewhere on the card do nothing.
- **Remembered position**: where Yoshi drops the card is used for later cards this session (kept on a visible screen);
  a restart docks top-right again.
- **Chips follow** the card when it moves.
- **Dodging marks**: every screen underline/circle is reported to the card with its rectangle (kept ~12 s, the marks'
  lifetime). If the visible card overlaps it, the card glides (~250 ms) to the dock spot on the opposite side of the
  same screen (or, if that also overlaps, whichever overlaps less). A new card avoids live marks when it docks. Marks are
  no longer dropped; the buddy is still raised above everything.
- **Hotkey**: default `win+alt`; `.env.example`, README and tests updated. Tray shows "Win + Alt".

## Non-goals
Resizing the card, pinning it permanently, saving position across restarts.
