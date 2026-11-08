# Kokoro local voice

Date: 2026-11-08 · Status: draft, awaiting Yoshi's approval · Size: small project

## Intent
Yoshi's ElevenLabs free credits (10,000/month) are used up until about 5 Dec, so Clicky speaks with the robotic
Windows voice. He wants a good-sounding voice that is free with no monthly cap. Account-farming free tiers was ruled
out (breaks ElevenLabs' terms, risks his real account).

## Goals
- Clicky speaks every answer with Kokoro-82M, a neural voice that runs locally on the CPU: free, unlimited, offline.
- Everything that hangs off the voice keeps working unchanged: note/mark/animation timing from playback progress,
  Esc and talking over it, the heard-part cut-off in history.
- ElevenLabs stays available behind a setting, for when the credits are back.
- If Kokoro can't speak (model missing, synthesis error), the Windows voice says it, as today.

## Non-goals
- Sentence-by-sentence streaming (approach 2 below). Only if the pause before long answers feels slow when tried live.
- A voice picker in the tray. The voice is set in `.env`.
- Bundling the model in the repo, GPU acceleration, other languages.

## Anti-goals
- Clicky freezing while Kokoro thinks: synthesis must never run on the GUI thread or block the asyncio loop.
- Downloading anything without a checksum, or at app start without Yoshi knowing.

## Approaches (Yoshi chose 1, "Your defaults", 2026-11-08)
1. **Whole answer to a WAV, played by the existing `SpeechPlayer` (chosen).** Smallest change: Kokoro becomes another
   source of audio bytes, so progress, stop and interrupt logic are reused as-is. Cost: a pause before playback that
   grows with answer length.
2. Sentence-by-sentence synthesis with a play queue: speech starts sooner, but needs a queue and progress stitched
   across pieces, roughly double the work.
3. Cloud free tiers (Azure F0, Cloudflare Workers AI): need accounts or Worker changes and are capped; rejected.

## Decisions
- **Voice order (Yoshi chose the default):** `CLICKY_VOICE=kokoro` (default) or `elevenlabs`. Kokoro mode: Kokoro,
  then Windows voice. ElevenLabs mode: unchanged behaviour (ElevenLabs, quota skip, then Windows voice).
- **Voice:** `CLICKY_KOKORO_VOICE=af_heart` by default (any Kokoro voice name). Speed 1.0.
- **Package:** `kokoro-onnx` 0.6.x (MIT; model Apache-2.0). It pulls in `onnxruntime`, `numpy`, `phonemizer` and
  `espeakng-loader`; the last two are **GPL-3.0**. Fine for personal use; the repo only lists them as dependencies.
  Noted in the README.
- **Model:** `kokoro-v1.0.int8.onnx` (114 MB) + `voices-v1.0.bin` (28 MB) from the kokoro-onnx GitHub release
  `model-files-v1.1`, into `%LOCALAPPDATA%\Clicky\models\`. Fetched by a one-off `scripts/download_kokoro.py` that
  checks the SHA-256 published for each file (int8 `ae315a79…ee9c`, voices `bca610b8…bf7d`). Never downloaded at run
  time. int8 rather than full precision (325 MB): a third of the size; the project notes its timings differ slightly,
  which doesn't matter here.
- **Threading:** synthesis runs in a worker thread (`asyncio.to_thread`) called from the AsyncRunner loop, like the
  ElevenLabs fetch. The model loads once, in the background at startup, so the first answer isn't slower.
- **Audio format:** float samples → 16-bit mono WAV (stdlib `wave`, 24 kHz). `SpeechPlayer.play` takes any audio bytes
  and names the temp file `.wav` or `.mp3` from the header.
- **Early speech:** the existing "start the voice when the first `<scene` appears" path works for Kokoro too.
- **Failure:** missing model or Kokoro error → `TTSError` with a plain message (e.g. "run scripts/download_kokoro.py")
  → the existing Windows-voice fallback. Kokoro is retried on the next answer.

## Left to the builder
Exact module/class names, how the fake Kokoro is injected in tests, wording of log messages.

## Verification
Unit tests (WAV encoding, settings, engine selection, fallback, checksum check) with a fake Kokoro, so the suite
doesn't need the model. Then a live check on Yoshi's laptop: time to first sound for a short and a long answer.
