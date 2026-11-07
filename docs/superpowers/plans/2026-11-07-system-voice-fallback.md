# Windows voice fallback — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Speak answers with Windows' built-in voice when ElevenLabs fails, and stop asking ElevenLabs after a quota error.

**Architecture:** A `SystemVoice` (Qt `QTextToSpeech`) with the same signals as `SpeechPlayer`, and a `VoiceOutput` that owns both and re-emits their signals, so the controller and director keep one player. The controller asks it to `speak_text` when there's no audio but a TTS error.

**Tech Stack:** Python 3.13, PySide6 6.12 (`QtTextToSpeech`), pytest offscreen.

**Spec:** `docs/superpowers/specs/2026-11-07-system-voice-fallback-design.md`

## Global Constraints
- No new dependencies. Tests use the `mock` engine (silent). GUI thread only for Qt objects.
- Keep `tests/test_end_to_end.py` passing. History/interrupt behaviour unchanged.

## Review Focus
- Interrupting (hotkey / Esc) while the Windows voice speaks: it stops at once, `finished` fires exactly once, history keeps only what was heard.
- Windows voice in an error state or no engine available: the answer still appears as text.
- A quota error during the early (pre-scene) speech fetch must also set the "skip ElevenLabs" flag.
- Very long answers: progress reaches 1.0 at the end (last word), never above.
- A new reply arriving while the Windows voice is still talking.

---

### Task 1: SystemVoice and VoiceOutput (`clicky/system_voice.py`, tests `tests/test_system_voice.py`)

**Interfaces — Produces:**
- `SystemVoice(QObject, engine: str = "winrt")`: `speak(text: str) -> None`, `stop() -> None`, `is_playing: bool`,
  `available: bool`; signals `started()`, `progress(float)`, `finished()`, `failed(str)`. Progress =
  (word start + length) / len(text), clamped 0..1. `finished` once per speak (ended, stopped or failed).
- `VoiceOutput(QObject, player: SpeechPlayer, voice: SystemVoice)`: `play(mp3: bytes)`, `speak_text(text: str)`,
  `stop()` (stops whichever is playing; the other's stop is a no-op), `is_playing`; re-emits `started`, `progress`,
  `finished` from both; `failed(str)` from the voice.

- [ ] Tests (mock engine): `test_system_voice_speaks_and_reports_progress_to_the_end` — speak("one two three"):
  started once, progress increasing, last == 1.0, finished once; `test_stopping_the_system_voice_finishes_once`;
  `test_voice_output_routes_text_to_the_system_voice_and_stops_it`; `test_stop_without_speaking_is_safe`.
- [ ] Run → FAIL; implement; run → PASS; commit `feat(voice): Windows voice with word progress, behind one output`.

### Task 2: Controller fallback (`clicky/controller.py`, tests `tests/test_controller.py`)

**Consumes:** `player.speak_text(text)` when the player has it (`getattr`); otherwise today's text notice.

- [ ] Tests: `test_a_failed_voice_falls_back_to_speaking_the_text` (FakePlayer with `speak_text`; tts_error=TTSError(
  "... quota_exceeded ...")): spoken_texts == [answer], state RESPONDING, no notice; after
  `handle_playback_finished` the answer is in history. `test_after_a_quota_error_elevenlabs_is_not_asked_again`:
  second interaction → services.spoken has one entry, fallback used again.
  `test_other_voice_errors_still_retry_elevenlabs`: two interactions with a network-style error → two fetches.
  Existing `test_tts_failure_still_points_and_goes_idle` (player without speak_text) still passes.
- [ ] Implement: `_skip_elevenlabs` flag set when a TTS error message contains "quota_exceeded" (main and early
  fetch); when set, `_respond` skips both fetches with `speech_error = "elevenlabs quota used up"`. In `_on_reply_ready`,
  no audio + speech_error + `speak_text` available → same path as audio (remember-on-heard, RESPONDING) via
  `speak_text`. Add `handle_voice_failed(message)` → if RESPONDING: show the answer as a notice and go IDLE.
- [ ] Commit `feat: speak with the Windows voice when ElevenLabs fails; stop asking after a quota error`.

### Task 3: Wire into the app (`clicky/app.py`)
- [ ] `player = VoiceOutput(SpeechPlayer(), SystemVoice())`; connect `player.failed` to `controller.handle_voice_failed`.
  Existing `player.started/progress/finished` connections unchanged. Full suite + ruff; AGENTS.md one line.
- [ ] Commit `feat(app): use the Windows voice fallback`.
