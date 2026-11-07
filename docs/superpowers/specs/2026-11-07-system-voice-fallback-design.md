# Windows voice fallback when ElevenLabs can't speak

Date: 2026-11-07 · Status: approved by Yoshi in chat ("Approve and build") · Size: small

## Intent
Yoshi ran out of ElevenLabs free credits (10,000/month, resets with the billing cycle). Clicky then only shows the
answer as text. He wants Clicky to keep talking with Windows' free built-in voice instead.

## Design (approved)
- Whenever fetching the ElevenLabs voice fails (quota exceeded, network, Worker error), Clicky speaks the answer with
  Windows' own voice via Qt's `QTextToSpeech` (PySide6 already bundles it: engines `winrt`, `sapi`; `mock` for tests).
  No new dependency, no cost.
- After a `quota_exceeded` error, Clicky stops asking ElevenLabs until it's restarted (saves a doomed request per
  answer). Other errors retry ElevenLabs on the next answer.
- Timing works as with ElevenLabs: the Windows voice reports each word, giving playback progress for notes, marks and
  animations, for the cut-off point when interrupted, and for Esc / talking over it.
- Voice: the Windows default (changeable in Windows settings). The only sign of the fallback is the voice itself.
- If the Windows voice fails too, the answer is shown as text, as today.

## Approaches considered
1. **Qt `QTextToSpeech` (chosen):** bundled, word-by-word progress, a mock engine for silent tests.
2. `pyttsx3`: a new dependency, no word progress on Windows.
3. PowerShell `System.Speech`: slow to start, no progress, a subprocess per answer.

## Non-goals
Choosing a voice inside Clicky; caching audio; changing the Worker.
