# Clicky for Windows: agent notes

Python 3.13 + PySide6 port of farzaa/clicky. Read `docs/design.md` before changing behaviour.

## Commands
- Tests: `.venv\Scripts\python -m pytest -q` (Qt runs offscreen via `tests/conftest.py`)
- Lint/format: `.venv\Scripts\ruff check .` and `.venv\Scripts\ruff format .`
- Run: `.venv\Scripts\python -m clicky` (needs `CLICKY_WORKER_URL`)

## Rules
- `worker/src/` is the upstream Worker code and stays byte-for-byte unchanged (only the `ELEVENLABS_VOICE_ID`
  setting in `worker/wrangler.toml` differs: a default voice free ElevenLabs plans can use). The app must work with it as-is
  (it serves only `/chat`, `/tts`, `/transcribe-token` and forwards no client headers).
- No API keys in the app, repo, tests or logs.
- Threading: Qt objects on the GUI thread only; network on `AsyncRunner`'s loop; cross-thread results go through
  Qt signals. Screen capture (`QScreen.grabWindow`) is GUI-thread only.
- Keep `tests/test_end_to_end.py` passing. It is the contract with the Worker and AssemblyAI protocol.
- Names: descriptive over short (upstream convention). Type hints on public functions.
- Branches `feat/…` / `fix/…`; conventional commits; never commit to `main` directly.
