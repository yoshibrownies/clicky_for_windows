# Clicky for Windows: design

Date: 2026-11-05 · Author: Claude (for Yoshi) · Status: approved by Yoshi in chat ("build it for me")

## Intent
A Windows port of [farzaa/clicky](https://github.com/farzaa/clicky) (MIT). Yoshi uses it every day
and shows it off as a portfolio project. You hold a hotkey and talk. Clicky hears you,
looks at your screens, answers out loud, and a small blue cursor flies over to point at
the thing it's talking about.

## Goals
- The same loop as the Mac app: push-to-talk → AssemblyAI streaming transcript → transcript plus
  screenshots of every monitor to Claude (streamed) → spoken reply through ElevenLabs → the cursor points
  at `[POINT:x,y:label:screenN]`.
- Reuse the upstream Cloudflare Worker **unchanged** (`/chat`, `/tts`, `/transcribe-token`).
  The app never holds API keys.
- Windows-specific correctness: per-monitor DPI scaling, multiple monitors, the overlay is click-through
  and left out of its own screenshots, and the hotkey doesn't break normal typing.
- Polish worth showing off: anti-aliased cursor, smooth bezier flight, waveform while listening,
  a spinner while thinking, a speech bubble with the reply, and a tray menu.

## Non-goals
- Onboarding demo, analytics (PostHog), auto-update (Sparkle), OpenAI/Apple speech fallbacks.
- Installer or packaged .exe (possible follow-up).
- Changes to the Worker.

## Anti-goals (a failure even if it "works")
- API keys anywhere in the app, repo or logs.
- The hotkey stealing or breaking normal typing or shortcuts.
- The cursor pointing at the wrong place on a scaled or second monitor.
- A frozen UI while waiting on the network.

## Constraints
- Windows 11, Python 3.13 (PySide6 wheels; 3.15 is too new), venv + pip, ruff, pytest.
- Yoshi chose: **PySide6**, **Ctrl+Alt** default hotkey (configurable), repo at
  `Downloads/clicky-windows`.
- Paid APIs are capped at US$10/month overall, so the app keeps requests lean (screenshots ≤1600 px on the long edge, JPEG 80).

## Approaches considered
1. **Python + PySide6 (chosen by Yoshi).** One language and a mature, anti-aliased, click-through
   overlay. QtMultimedia plays the ElevenLabs MP3s with no extra decoder. Cost: a large install.
2. Python + tkinter. No big dependency, but jagged transparency edges, weak animation, and it needs
   an extra MP3 library. Doesn't fit "show off".
3. C# / WPF. The best native fit, but outside Yoshi's stack and harder for him to maintain.

## Architecture
```
GUI thread (Qt)                         asyncio thread (AsyncRunner)
───────────────                         ────────────────────────────
HotkeyPoller (own thread, GetAsyncKeyState) ──signals──▶ Controller
Controller (QObject state machine) ──submit coroutines──▶ AssemblyAI session, Claude stream, TTS fetch
OverlayWindow ×N (one per QScreen)  ◀──Qt signals (queued)── results / deltas / errors
TrayIcon, TTS playback (QMediaPlayer)
Screen capture (QScreen.grabWindow; GUI thread only)
```
States: `idle → listening → processing → responding → idle`. Any error goes back to `idle`,
shows a short message in the bubble, and is logged.

## Key decisions
- **Raw httpx, not the Anthropic SDK.** The SDK always posts to `{base}/v1/messages`, but the
  unchanged Worker only serves `/chat`. Same request body as the Mac app.
- **Model:** default `claude-opus-5-5`, with `claude-sonnet-5-5` in the tray menu. `output_config.effort = "low"`
  because it's a voice chat and latency matters; `thinking` is left out (Opus 5.5 can't disable it).
  `max_tokens` 4096. No server-side `fallbacks` because the Worker drops client headers, so the
  beta header can't get through; a `refusal` stop is spoken as a short apology.
- **Screens:** captured with `QScreen.grabWindow(0)`, so each image belongs to a known QScreen.
  The cursor's screen comes first and is labelled "primary focus", and labels include the image size (as in the Mac app).
  A Claude point `(x, y)` in image pixels maps to the screen's logical coordinates as
  `x / img_w * geom.width()`, which is DPI-independent. Modern models map coordinates 1:1 to image pixels.
- **Overlay:** one frameless, translucent, `WindowTransparentForInput`, always-on-top tool window per
  screen, with `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` so Clicky never appears in the
  screenshots it sends.
- **Hotkey:** polling `GetAsyncKeyState` at 100 Hz (no hooks, no admin, no unmaintained `keyboard`
  library). Pure state machine: activates after the combo has been held 150 ms with no other key down; any other key
  while held **cancels** (so Ctrl+Alt+Del, Ctrl+Alt+T and AltGr+letter typing don't start a recording);
  it can't re-trigger until the combo is fully released. Mouse buttons are ignored.
- **AssemblyAI v3:** temporary token from `/transcribe-token`, then
  `wss://streaming.assemblyai.com/v3/ws?sample_rate=16000&encoding=pcm_s16le&format_turns=true&speech_model=u3-rt-pro&token=…`.
  Binary PCM16 frames go up. Turn tracking is ported from Swift: completed turns are stored by `turn_order` (a formatted turn
  beats an unformatted one), and an active partial is appended. On release: `ForceEndpoint`, wait up to 2.5 s for an
  end-of-turn, then `Terminate`. Audio comes from `sounddevice.RawInputStream` (16 kHz, mono, int16).
- **TTS:** POST `/tts` `{text, model_id: eleven_flash_v2_5, voice_settings}` → MP3 bytes → QMediaPlayer
  from a temp file. The cursor flies to the target as speech starts.
- **History:** the last 10 exchanges, as text only (transcript, spoken reply), like the Mac app; images only on the
  current turn.
- **Config:** `.env` (python-dotenv): `CLICKY_WORKER_URL` (required), `CLICKY_HOTKEY`, `CLICKY_MODEL`,
  `CLICKY_EFFORT`. A missing URL is a clear startup error.

## Left to the builder
Visual sizes and colours, animation timings, log format.
