# Interrupt awareness: Clicky knows where you cut it off

Date: 2026-11-07 · Status: approved by Yoshi in chat ("Sounds good. Now do it please.")

## Intent
Yoshi cuts Clicky off mid-explanation to go deeper into something it just said ("wait, what's long-term
potentiation?"). Today Clicky saves its whole answer to history before speaking, so it believes Yoshi heard all of
it, and the next answer can't tell what "that" refers to. Clicky should know exactly how far it got, and history
should hold only what Yoshi actually heard.

## Goals (Yoshi's words, played back and approved)
- When cut off, Clicky knows where it was.
- Visuals and animations for later parts of the old explanation are discarded, not saved.
- History stores no unheard text or unplayed animation.

## Behaviour (proposed in chat, approved)
1. A reply is remembered only once it has been heard: in full when speech finishes; up to the cut-off point plus the
   marker `… (the user cut me off here)` when interrupted. Tags before the cut (notes, animations already shown) stay,
   so Clicky knows what was on screen; tags after it, and follow-up tags, are dropped. Scene JSON is never stored (as
   today).
2. Esc (`stop_speaking`) and push-to-talk interruptions behave the same.
3. Interrupted before any speech was heard (still thinking, or audio not yet started): nothing is remembered.
4. The prompt tells the model what the marker means: answer the new question directly and go deeper; don't restart
   or finish the old explanation unless asked.
5. The new answer builds a fresh card, as today. Pending visuals of the old reply are already dropped on interrupt
   (`interrupted` → `VisualDirector.cancel`).
6. TTS failure (answer shown as text): remembered in full immediately, as today.

## Approach
Cut-off position = playback progress (audio position / duration) mapped proportionally onto the spoken text, rounded
forward to the end of the word being spoken. This is the same mapping the visual timeline already uses to fire marks,
so what's remembered as shown matches what was drawn. *(Builder's call; alternatives considered: ElevenLabs
character timestamps via a new Worker route — exact, but a Worker change and redeploy; speaking sentence by sentence
— exact sentence, but more requests and gaps between sentences. Proportional is within a few words, which is enough
to resolve "that".)*

## Non-goals
Richer graphics (next project); resuming the old explanation; keeping the old card on screen.

## Anti-goals
Saving words Yoshi never heard; Esc or interruption losing the history of fully heard answers.
