# Kokoro Local Voice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicky speaks every answer with Kokoro-82M running locally (free, unlimited), keeping ElevenLabs behind a setting and the Windows voice as the fallback.

**Architecture:** A new `clicky/kokoro_voice.py` turns text into 16-bit WAV bytes in a worker thread. `WorkerServices.fetch_speech` returns those bytes instead of ElevenLabs MP3s when `CLICKY_VOICE=kokoro`, so the controller, `SpeechPlayer`, progress timing and the Windows-voice fallback are reused unchanged. The model is fetched once by a checksum-verified script.

**Tech Stack:** Python 3.13, PySide6 (QtMultimedia), `kokoro-onnx` 0.6.x (onnxruntime, numpy), stdlib `wave`/`hashlib`, httpx, pytest.

**Spec:** `docs/superpowers/specs/2026-11-08-kokoro-local-voice-design.md`

## Global Constraints
- Branch: rename the worktree branch to `feat/kokoro-voice` before the first commit (`git branch -m feat/kokoro-voice`). Conventional commits ending with the Co-Authored-By line.
- Commands: the venv lives in the main checkout: `C:/Users/yoshi/Downloads/clicky-windows/.venv/Scripts/python -m pytest -q` and `.../.venv/Scripts/ruff check .` run from the worktree.
- Dependency: `kokoro-onnx>=0.6.1,<0.7` in `requirements.txt`. Import it lazily (inside the loader) so tests and app start never need it or the model.
- Settings: `CLICKY_VOICE` ∈ {`kokoro`, `elevenlabs`}, default `kokoro`. `CLICKY_KOKORO_VOICE`, default `af_heart`. Speed 1.0, lang `en-us`.
- Model files, in `%LOCALAPPDATA%\Clicky\models\`, from `https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1/`:
  - `kokoro-v1.0.int8.onnx` sha256 `ae315a79b623f244700e4afb9246c46a26066782e049ba174bf3ba433970ee9c` (114,119,327 bytes)
  - `voices-v1.0.bin` sha256 `bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d` (28,214,398 bytes)
- Synthesis never runs on the GUI thread or directly on the asyncio loop (`asyncio.to_thread`).
- Nothing is downloaded at run time. `tests/test_end_to_end.py` must keep passing (it pins `CLICKY_VOICE=elevenlabs`).

## Review Focus
1. Model files missing (script never run): the answer must still be spoken by the Windows voice, with a log line naming `scripts/download_kokoro.py`. → Task 2 test `test_missing_model_raises_tts_error_naming_the_script`.
2. Esc / talking over Kokoro while it is still synthesising: the interaction must stop at once (the thread finishes in the background and its WAV is dropped by the existing generation check). → Task 3 test `test_cancelling_kokoro_fetch_returns_promptly`.
3. Text with only symbols/whitespace or very long answers (>510 phonemes): no crash; blank text raises `TTSError` ("Nothing to speak."), long text is chunked by kokoro-onnx itself. → Task 2 test `test_blank_text_raises_tts_error`.
4. A corrupt or partly downloaded model file: the script must reject it and delete it, not leave it for Clicky to load. → Task 4 test `test_download_deletes_file_with_wrong_checksum`.
5. Kokoro throws inside synthesis (bad voice name in `.env`): becomes `TTSError` → Windows voice. → Task 2 test `test_synthesis_error_becomes_tts_error`.

---

### Task 1: Voice settings

**Files:**
- Modify: `clicky/config.py` (Settings dataclass, `load_settings`)
- Modify: `.env.example` (document both settings)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces: `Settings.voice_engine: str` (`"kokoro"` | `"elevenlabs"`), `Settings.kokoro_voice: str`; constants `VOICE_ENGINES = ("kokoro", "elevenlabs")`, `DEFAULT_VOICE_ENGINE = "kokoro"`, `DEFAULT_KOKORO_VOICE = "af_heart"`. Both new fields have defaults so existing `Settings(...)` calls keep working.

- [ ] **Step 1: Write failing tests**

```python
def test_voice_defaults_to_kokoro_af_heart():
    settings = load_settings({"CLICKY_WORKER_URL": "http://localhost:8787"})
    assert settings.voice_engine == "kokoro"
    assert settings.kokoro_voice == "af_heart"


def test_voice_engine_and_kokoro_voice_are_read_case_insensitively():
    settings = load_settings(
        {"CLICKY_WORKER_URL": "http://localhost:8787", "CLICKY_VOICE": "ElevenLabs", "CLICKY_KOKORO_VOICE": "bf_emma"}
    )
    assert settings.voice_engine == "elevenlabs"
    assert settings.kokoro_voice == "bf_emma"


def test_unknown_voice_engine_is_a_config_error():
    with pytest.raises(ConfigError, match="CLICKY_VOICE"):
        load_settings({"CLICKY_WORKER_URL": "http://localhost:8787", "CLICKY_VOICE": "siri"})
```

- [ ] **Step 2: Run** `pytest tests/test_config.py -q` → the 3 new tests FAIL.
- [ ] **Step 3: Implement** the fields and validation in `config.py` (lower-case the engine; keep the voice name as given). Add to `.env.example`: `CLICKY_VOICE=kokoro` with a comment (kokoro = free local voice, needs `python scripts/download_kokoro.py` once; elevenlabs = Worker `/tts`, uses credits) and `CLICKY_KOKORO_VOICE=af_heart`.
- [ ] **Step 4: Pin the e2e test to ElevenLabs:** in `tests/test_end_to_end.py`, add `"CLICKY_VOICE": "elevenlabs"` to every environment dict passed to `load_settings`. Run `pytest -q` → all pass.
- [ ] **Step 5: Commit** `feat(config): CLICKY_VOICE (kokoro default) and CLICKY_KOKORO_VOICE settings`

### Task 2: Kokoro synthesis module

**Files:**
- Create: `clicky/kokoro_voice.py`
- Test: `tests/test_kokoro_voice.py`

**Interfaces:**
- Consumes: `clicky.tts.TTSError`.
- Produces:
  - `MODEL_FILE_NAME = "kokoro-v1.0.int8.onnx"`, `VOICES_FILE_NAME = "voices-v1.0.bin"`
  - `default_model_dir() -> Path` — `%LOCALAPPDATA%/Clicky/models` (same base folder as the log file; reuse that helper if one exists in `app.py`/`paths`).
  - `encode_wav(samples: Sequence[float] | numpy.ndarray, sample_rate: int) -> bytes` — mono 16-bit PCM WAV; clip to [-1, 1], scale by 32767.
  - `class KokoroSpeech(model_dir: Path, voice: str, kokoro_factory: Callable[[str, str], Any] | None = None)` — `kokoro_factory(model_path, voices_path)` returns an object with `.create(text, voice=, speed=, lang=) -> (samples, sample_rate)`; default factory imports `kokoro_onnx.Kokoro` lazily.
    - `load() -> None` — idempotent, thread-safe (a `threading.Lock`); raises `TTSError` if either file is missing: `f"Kokoro voice model not found in {model_dir}. Run: python scripts/download_kokoro.py"`.
    - `synthesize(text: str) -> bytes` — blocking; calls `load()`, returns `encode_wav(...)`; blank text → `TTSError("Nothing to speak.")`; any exception from the factory or `create` → `TTSError(f"Kokoro voice failed: {error}")`.

- [ ] **Step 1: Write failing tests** (fake factory records calls and returns `([0.0, 0.5, -1.0, 2.0], 24000)`; model files are empty files in `tmp_path`):

```python
def test_encode_wav_writes_mono_16_bit_clipped_samples():
    wav = encode_wav([0.0, 0.5, -1.0, 2.0], 24000)
    with wave.open(io.BytesIO(wav)) as reader:
        assert (reader.getnchannels(), reader.getsampwidth(), reader.getframerate()) == (1, 2, 24000)
        assert struct.unpack("<4h", reader.readframes(4)) == (0, 16383, -32767, 32767)


def test_synthesize_returns_wav_and_passes_voice_speed_lang(tmp_path):
    ...
    # assert bytes start with b"RIFF"; fake.create called once with voice="af_heart", speed=1.0, lang="en-us"


def test_model_loads_once_across_calls(tmp_path): ...  # factory called once after load() + 2 synthesize()
def test_missing_model_raises_tts_error_naming_the_script(
    tmp_path,
): ...  # match="download_kokoro.py"; factory never called
def test_blank_text_raises_tts_error(tmp_path): ...  # "   " → TTSError("Nothing to speak.")
def test_synthesis_error_becomes_tts_error(
    tmp_path,
): ...  # fake .create raises ValueError("bad voice") → TTSError match "bad voice"
```

- [ ] **Step 2: Run** `pytest tests/test_kokoro_voice.py -q` → FAIL (module missing).
- [ ] **Step 3: Implement** `clicky/kokoro_voice.py` per the interface (stdlib `wave` + `array('h')` or numpy for encoding; module docstring says why it exists and that it's thread-blocking by design).
- [ ] **Step 4: Run** the file's tests → PASS; `ruff check .` clean.
- [ ] **Step 5: Commit** `feat(voice): local Kokoro synthesis to WAV`

### Task 3: Wire Kokoro into services, player and app

**Files:**
- Modify: `clicky/services.py` (`WorkerServices.__init__`, `fetch_speech`, new `warm_up_voice`)
- Modify: `clicky/playback.py` (`SpeechPlayer.play`)
- Modify: `clicky/app.py:196-198` (build `KokoroSpeech`, pass it in, warm up)
- Test: `tests/test_services_voice.py` (new), `tests/test_tts_and_audio.py`

**Interfaces:**
- Consumes: `KokoroSpeech`, `default_model_dir()` (Task 2); `Settings.voice_engine`, `Settings.kokoro_voice` (Task 1).
- Produces:
  - `WorkerServices(settings, assemblyai_websocket_base_url=..., kokoro_speech: KokoroSpeech | None = None)`.
  - `async fetch_speech(text) -> bytes` — if `settings.voice_engine == "kokoro"`: `await asyncio.to_thread(kokoro_speech.synthesize, text)` (raise `TTSError("Kokoro voice isn't set up")` if `kokoro_speech` is None); else the ElevenLabs path unchanged.
  - `async warm_up_voice() -> None` — kokoro mode only: `await asyncio.to_thread(kokoro_speech.load)`, logging (not raising) a `TTSError` as a warning.
  - `SpeechPlayer.play(audio: bytes)` — temp-file suffix `.wav` when `audio[:4] == b"RIFF"`, else `.mp3`. Rename the parameter in `VoiceOutput.play` too.
  - Pure helper `audio_file_suffix(audio: bytes) -> str` in `playback.py` (tested without Qt).

- [ ] **Step 1: Write failing tests**

```python
async def test_kokoro_engine_synthesises_in_a_worker_thread():
    # fake KokoroSpeech whose synthesize records threading.get_ident() and returns b"RIFF...."
    # settings via load_settings({..., "CLICKY_VOICE": "kokoro"}); assert result == b"RIFF....", thread id != main loop thread id

async def test_elevenlabs_engine_never_touches_kokoro():
    # httpx MockTransport for /tts returning b"mp3"; fake kokoro whose synthesize raises AssertionError; result == b"mp3"

async def test_cancelling_kokoro_fetch_returns_promptly():
    # fake synthesize blocks on a threading.Event; task = create_task(fetch_speech("hi")); cancel it;
    # assert CancelledError within 0.5 s; then set the event so the thread ends

async def test_kokoro_engine_without_kokoro_speech_raises_tts_error(): ...
async def test_warm_up_logs_instead_of_raising_when_model_missing(caplog): ...  # caplog has "download_kokoro.py"

def test_audio_file_suffix_detects_wav_and_defaults_to_mp3():
    assert audio_file_suffix(b"RIFF\x00\x00\x00\x00WAVE") == ".wav"
    assert audio_file_suffix(b"\xff\xfb\x90") == ".mp3"
```

  (Injecting a fake HTTP client: follow how `tests/test_end_to_end.py` or `test_tts_and_audio.py` already does it; if `WorkerServices` has no seam, set `services._client` to an `httpx.AsyncClient(transport=MockTransport(...))`.)
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the services and playback changes. In `app.py`: `kokoro_speech = KokoroSpeech(default_model_dir(), settings.kokoro_voice)`; `WorkerServices(settings, kokoro_speech=kokoro_speech)`; after the runner starts, `runner.submit(services.warm_up_voice())`. Update the comment above `VoiceOutput(...)`. No controller change: in kokoro mode `fetch_speech` never reports `quota_exceeded`, and a `TTSError` already routes to the Windows voice.
- [ ] **Step 4: Run** `pytest -q` (whole suite, incl. `test_end_to_end.py`, `test_controller.py`) → all pass; `ruff check .` and `ruff format --check .` clean.
- [ ] **Step 5: Commit** `feat(voice): speak with Kokoro by default, ElevenLabs behind CLICKY_VOICE`

### Task 4: Model download script, dependency and docs

**Files:**
- Create: `scripts/download_kokoro.py`
- Modify: `requirements.txt`, `README.md` (setup step + GPL note), `AGENTS.md` (Voice rule)
- Test: `tests/test_download_kokoro.py`

**Interfaces:**
- Consumes: `MODEL_FILE_NAME`, `VOICES_FILE_NAME`, `default_model_dir()` (Task 2).
- Produces (in the script, importable for tests via `importlib`/`sys.path`):
  - `MODEL_FILES: dict[str, str]` — file name → sha256 (Global Constraints values); `RELEASE_URL` base.
  - `sha256_of(path: Path) -> str` (streamed, 1 MiB chunks).
  - `download_file(client: httpx.Client, url: str, destination: Path, expected_sha256: str) -> None` — streams to `destination.with_suffix(".part")`, verifies, renames on match; on mismatch deletes the part file and raises `ValueError` naming the file.
  - `main() -> int` — skips files already present with the right hash; prints what it did; returns 0/1.

- [ ] **Step 1: Write failing tests** (httpx `MockTransport` serving fixed bytes)

```python
def test_download_keeps_file_with_matching_checksum(tmp_path): ...  # destination exists, no .part left
def test_download_deletes_file_with_wrong_checksum(
    tmp_path,
): ...  # raises ValueError; neither destination nor .part exists
def test_model_files_pin_the_published_checksums():
    assert MODEL_FILES == {
        "kokoro-v1.0.int8.onnx": "ae315a79b623f244700e4afb9246c46a26066782e049ba174bf3ba433970ee9c",
        "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
    }
```

- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the script (`follow_redirects=True`; GitHub release URLs redirect). Add `kokoro-onnx>=0.6.1,<0.7` to `requirements.txt`. README: a "Free local voice (Kokoro)" step (`pip install -r requirements.txt`, `python scripts/download_kokoro.py`, ~142 MB once; `CLICKY_VOICE=elevenlabs` to switch back) and a licence line (phonemizer and espeakng-loader are GPL-3.0). AGENTS.md Voice bullet: Kokoro default, ElevenLabs via `CLICKY_VOICE`, Windows voice fallback, spec path.
- [ ] **Step 4: Run** `pytest -q` and ruff → clean.
- [ ] **Step 5: Commit** `feat(voice): checksum-verified Kokoro model download script and docs`

### Task 5: Install, download and live check (needs Yoshi's OK at each side-effect step)

- [ ] **Step 1:** Ask Yoshi, then `C:/Users/yoshi/Downloads/clicky-windows/.venv/Scripts/python -m pip install "kokoro-onnx>=0.6.1,<0.7"` (main checkout's venv). Expected: installs onnxruntime, phonemizer, espeakng-loader, numpy.
- [ ] **Step 2:** Ask Yoshi (downloading ~142 MB), then `python scripts/download_kokoro.py`. Expected: both files verified in `%LOCALAPPDATA%\Clicky\models`.
- [ ] **Step 3:** Timing script in the scratchpad: synthesize a 1-sentence and a ~60-word answer with `af_heart`; record seconds to WAV and audio length. Save one WAV for Yoshi to listen to.
- [ ] **Step 4:** Full suite + ruff once more; report numbers. Yoshi runs Clicky (from this branch) and judges the pause and the voice. If the long-answer pause feels slow, that is the trigger for approach 2 (not in this plan).
