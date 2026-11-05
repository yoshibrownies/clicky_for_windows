# Clicky for Windows: implementation plan

Spec: `docs/design.md`. Test command for every task: `.venv/Scripts/python -m pytest -q` (plus `ruff check .`).
Global constraints: Python 3.13, type hints on public functions, no secrets in the repo, the Worker stays unchanged,
and descriptive names (upstream convention). Commits are conventional and land on `feat/initial-app`.

## Task 1: Scaffold
Add pyproject (ruff, pytest asyncio_mode=auto), requirements files, .gitignore (.venv, .env, logs), .env.example,
LICENSE (MIT, crediting upstream), AGENTS.md + CLAUDE.md (`@AGENTS.md`), and the `clicky` package with `config.py`.
Tests: `load_settings` reads env, strips a trailing `/` from the URL, defaults hotkey `ctrl+alt`, model `claude-opus-5-5`, effort `low`;
a missing or non-http(s) worker URL raises `ConfigError`.

## Task 2: Pointing tag parser (`pointing.py`)
Port the Swift regex. `parse_point_tag(text) -> PointingResult(spoken_text, coordinate, label, screen_number)`.
Tests: none / plain coordinates / coordinates with label / with screen2 / whitespace / no tag / a tag mid-text (not at the end → ignored).

## Task 3: Screens geometry (`screens.py`, pure part)
`fit_within(w, h, max_long_edge)`, `order_screens_cursor_first`, `build_screen_label(index, count, is_cursor, w, h)`,
`map_image_point_to_screen(point, image_size, screen_geometry) -> (global_x, global_y)` with clamping.
Tests: downscale math, no upscale, labels match the Mac wording, mapping at 150% DPI and on a second monitor with a negative origin.

## Task 4: Conversation and Claude request/SSE (`conversation.py`, `claude_client.py`)
`ConversationHistory(max_exchanges=10)`; `build_chat_request_body(...)`; `SSEParser.feed(bytes) -> events`;
`extract_text_deltas`; `stream_chat(...)` async generator (httpx), raising `ClaudeStreamError` on HTTP errors or an `error` event,
yielding a final `stop_reason`. Tests: history trimming, body shape (images before labels, text last, effort, no thinking or temperature),
SSE split across chunk boundaries, CRLF, ping, error event, thinking blocks ignored; stream_chat against httpx.MockTransport.

## Task 5: AssemblyAI (`transcription.py`)
`build_websocket_url(token, keyterms)`, `TurnTranscriptTracker` (ported Swift logic), `fetch_temporary_token`,
`AssemblyAIStreamingSession` (websockets): `open()` waits for Begin, `send_audio(bytes)`, `finish(timeout)` → transcript, `cancel()`.
Tests: URL query, tracker ordering, formatted beats unformatted, partial appended; session against a local websockets test server
(Begin → Turn → ForceEndpoint → end_of_turn → Terminate).

## Task 6: TTS fetch and audio capture (`tts.py`, `audio_capture.py`)
`build_tts_request_body`, `fetch_speech_audio(client, url, text) -> bytes` (raises on non-2xx or empty audio);
`MicrophoneStreamer` (sounddevice RawInputStream → thread-safe callback) plus a pure `compute_audio_level(pcm16_bytes) -> 0..1`.
Tests: body, MockTransport success and failure, level of silence, full scale and odd byte counts.

## Task 7: Hotkey (`hotkey.py`)
`parse_hotkey("ctrl+alt")` → required key groups; `PushToTalkStateMachine.update(pressed_vks, now) -> event|None`;
`HotkeyPoller(QThread)` using GetAsyncKeyState. Tests: activation delay, release, cancel on an extra key, no retrigger until
released, mouse ignored, left/right variants, AltGr sequence, invalid hotkey string.

## Task 8: Async runner and controller (`async_runner.py`, `controller.py`)
`AsyncRunner` (loop in a daemon thread, `submit(coro) -> Future`, `stop()`).
`CompanionController(QObject)`: the state machine wiring hotkey → mic+AssemblyAI → capture → Claude → TTS → point,
through injected collaborators so it can be tested with fakes. Tests (pytest-qt-free, plain QCoreApplication): happy path order,
empty transcript → idle, Claude error → idle + error message, cancel mid-listen, pressing again while responding stops playback and
restarts listening.

## Task 9: Overlay, tray, playback, app entry (`overlay.py`, `tray.py`, `playback.py`, `app.py`, `__main__.py`)
Per-screen click-through overlay excluded from capture; buddy cursor follows the mouse; waveform/spinner/bubble; bezier `fly_to`.
Tray: model picker, "always show buddy", quit. `QMediaPlayer` playback with a finished signal. `python -m clicky` entry; DPI awareness.
Tests: bezier math (pure), offscreen smoke test constructing the overlay/tray with the `offscreen` QPA platform.

## Task 10: README and real-run smoke
README (setup: Worker, .env, run; how it works; troubleshooting; credits). Launch on this PC against a local fake Worker
to check the whole loop end to end except the real APIs.
