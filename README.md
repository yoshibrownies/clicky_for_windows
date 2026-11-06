# Clicky for Windows

An AI buddy that lives next to your cursor. Hold **Win + Alt** and ask something. Clicky hears you,
looks at your screens, answers out loud, and a little blue triangle flies over to point at the thing
it's talking about.

A Windows port of [Clicky for macOS](https://github.com/farzaa/clicky) by Farza (MIT), rewritten in
Python + Qt. It uses the original Cloudflare Worker (plus an optional OpenAI route), so your API keys never live on your PC or in this repo.

```
hold Win+Alt ─▶ mic ─▶ AssemblyAI (live transcript)
release       ─▶ screenshot every monitor ─▶ Claude (streamed) ─▶ ElevenLabs voice
                                              └─▶ [POINT:x,y:label] ─▶ buddy flies there
```

## What you need
- Windows 10 (2004+) or 11, a microphone, speakers
- Python **3.13** (`py -3.13 --version`)
- Node.js 18+ (only to deploy the Worker)
- A free [Cloudflare](https://cloudflare.com) account
- API keys: [Anthropic](https://console.anthropic.com), [AssemblyAI](https://www.assemblyai.com), [ElevenLabs](https://elevenlabs.io)

## Setup

### 1. Deploy the Worker (holds your keys)
```bash
cd worker
npm install
npx wrangler login
npx wrangler secret put ANTHROPIC_API_KEY
npx wrangler secret put ASSEMBLYAI_API_KEY
npx wrangler secret put ELEVENLABS_API_KEY
npx wrangler secret put OPENAI_API_KEY   # optional: only to use GPT models instead of Claude
npx wrangler deploy
```
Each `secret put` asks you to paste the key. Wrangler sends it straight to Cloudflare. `deploy` prints a URL
like `https://clicky-proxy.<you>.workers.dev`; copy it. To use your own voice, change `ELEVENLABS_VOICE_ID` in
`worker/wrangler.toml` before deploying.

> **The Worker has no login.** Anyone who learns its URL can spend your API credit. Keep the URL private,
> and set a monthly spend limit in the Anthropic console (and on the other two services).

### 2. Install the app
```bash
py -3.13 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env
```
Open `.env` and set `CLICKY_WORKER_URL` to your Worker URL. That's the only required setting.

### 3. Run it
Double-click **`Clicky.bat`** (no console window), or for logs in a terminal:
```bash
.venv\Scripts\python -m clicky
```
A blue triangle appears in the system tray (it may be in the ^ overflow). Hold **Win + Alt**, talk,
release.

**Start with Windows:** press Win + R, type `shell:startup`, and put a shortcut to `Clicky.bat` in that folder.

## What it does while it talks
Clicky explains properly (several sentences, an intuition, an example) and shows you as it goes:
- **A lesson card** slides in at the side of your screen: a soft-green card with a title bar, a big handwritten
  question, then notes, formulas, a boxes-and-arrows diagram and a little animation, written in order while it speaks.
- **The green cursor follows the pen** while the card is being written, then goes back to your mouse.
- **Animations** play inside the card: a ball speeding up with its velocity arrow growing, a graph plotting itself,
  a list being sorted step by step. Clicky writes a fresh scene for each question in its own safe animation
  language (shapes, arrows, plots, formulas of time, keyframes); nothing it writes is ever run as code.
- **Animated underlines and circles** mark the exact words or buttons on your real screen, and the buddy can fly
  over to point.
- **Follow-up chips** ("Explain terminal speed", "Try a calculation") appear under the card when it finishes. Click
  one and Clicky answers it straight away, no talking needed. They're the only part of Clicky you can click.
- **A status pill** at the top of the screen shows Listening, Thinking or Speaking while it works.
- **Clear it all** any time with **Esc** or **Clear screen** in the tray menu.

Everything else is click-through and stays out of Clicky's own screenshots.

## Using it
| You do | Clicky does |
|---|---|
| Hold Win + Alt | Starts listening (green waveform). It waits 0.15 s so quick shortcuts don't trigger it |
| Press another key while holding | Cancels, so Win+Alt shortcuts (like Game Bar recording) still work |
| Release | Takes screenshots, thinks (purple spinner), then talks and points |
| Hold Win + Alt while it's talking | Interrupts it and listens again |
| Right-click tray icon | Switch model (Claude Opus/Sonnet 5.5, GPT-6.1 Terra/Sol, GPT-6 Luna), Thinking (Fast / Balanced / Deep), Show lesson card, hide the buddy when idle, forget the conversation, quit |

Settings in `.env`:
| Variable | Default | Notes |
|---|---|---|
| `CLICKY_WORKER_URL` | (required) | Your Worker URL |
| `CLICKY_HOTKEY` | `win+alt` | e.g. `right_ctrl`, `ctrl+win`, `f13`. Names: ctrl, alt, shift, win, left_/right_ variants, f13 to f24 |
| `CLICKY_MODEL` | `claude-opus-5-5` | `claude-sonnet-5-5` (half the price), or OpenAI `gpt-6.1-terra` / `gpt-6-luna` (needs the `OPENAI_API_KEY` secret). Any `gpt-*` model goes to OpenAI |
| `CLICKY_EFFORT` | `medium` | `low` replies fastest; `high` thinks longest (slower, pricier). Also the tray's Thinking menu |

**Cost:** each question sends one compressed screenshot per monitor (≤1600 px, about 2,000 tokens each), the
system prompt and your last 10 exchanges as text. A rough estimate from list prices (not measured) is
2 to 3 US cents per question on Opus 5.5 at low effort, about half that on Sonnet 5.5, plus AssemblyAI and
ElevenLabs usage. Check your dashboards after the first few days.

## How it works
| File | Job |
|---|---|
| `clicky/hotkey.py` | Polls `GetAsyncKeyState` (no hooks, no admin) through a hold/cancel state machine |
| `clicky/audio_capture.py` | 16 kHz mono PCM16 mic stream (sounddevice) |
| `clicky/transcription.py` | AssemblyAI v3 websocket: temporary token from the Worker, turn tracking, ForceEndpoint on release |
| `clicky/screens.py` | Grabs each monitor (cursor screen first), labels them, maps Claude's pixel coordinates back to the desktop at any DPI scale |
| `clicky/claude_client.py` | Streams `/chat` server-sent events (raw httpx, because the Worker serves `/chat`, not `/v1/messages`) |
| `clicky/pointing.py` | Parses `[POINT:x,y:label:screenN]` |
| `clicky/controller.py` | The state machine: idle → listening → processing → responding |
| `clicky/overlay.py` | The buddy: click-through, always on top, **excluded from screen capture** so Claude never sees it |
| `clicky/visuals.py`, `timeline.py`, `visual_director.py` | Parse the model's inline `[UNDERLINE]`/`[CIRCLE]`/`[NOTE]`/`[DIAGRAM]`/`[POINT]` tags and fire each at its moment in the speech |
| `clicky/annotations.py` | Hand-drawn animated underlines and circles, one transparent layer per monitor |
| `clicky/lesson_card.py`, `handwriting.py`, `diagram.py` | The soft-green lesson card: handwriting, notes, formulas, diagrams, inline animations |
| `clicky/scene.py`, `expressions.py`, `scene_painter.py` | The animation language: JSON scenes with safe formulas and keyframes |
| `clicky/followup_chips.py`, `status_pill.py` | Clickable follow-up questions; the Listening/Thinking/Speaking pill |
| `clicky/tray.py`, `playback.py`, `app.py` | Tray menu, MP3 playback, wiring |
| `worker/` | Upstream Cloudflare Worker, unchanged |

Network calls run on a background asyncio loop; the Qt GUI thread only draws. See `docs/design.md` for the
design decisions and the approaches considered.

## Development
```bash
.venv\Scripts\python -m pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest -q
.venv\Scripts\ruff check . && .venv\Scripts\ruff format --check .
```
The tests cover everything except the real APIs, including a full interaction through the real httpx and
websockets code against a fake Worker and a fake AssemblyAI (`tests/test_end_to_end.py`).

## Troubleshooting
- **Logs:** `%LOCALAPPDATA%\Clicky\clicky.log`
- **"Couldn't reach the Clicky Worker":** check `CLICKY_WORKER_URL`, and that `npx wrangler deploy` succeeded.
- **401 / invalid key errors:** re-run the matching `npx wrangler secret put …` and redeploy.
- **Mic doesn't work:** Windows Settings → Privacy & security → Microphone → allow desktop apps.
- **The hotkey clashes with something:** set `CLICKY_HOTKEY` (e.g. `right_ctrl`) and restart Clicky.
- **The buddy points slightly off:** Claude estimates the coordinates itself; Opus 5.5 is usually more accurate than Sonnet.

## Credits
Original Clicky and the Worker: [farzaa/clicky](https://github.com/farzaa/clicky) (MIT). The official, polished
apps are at [heyclicky.com](https://www.heyclicky.com/). This is an independent community port.
