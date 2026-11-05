# Clicky for Windows: agent notes

Python 3.13 + PySide6 port of farzaa/clicky. Read `docs/design.md` before changing behaviour.

## Commands
- Tests: `.venv\Scripts\python -m pytest -q` (Qt runs offscreen via `tests/conftest.py`)
- Lint/format: `.venv\Scripts\ruff check .` and `.venv\Scripts\ruff format .`
- Run: `.venv\Scripts\python -m clicky` (needs `CLICKY_WORKER_URL`)

## Rules
- `worker/` is the upstream Worker plus two deliberate changes: an added `/chat-openai` route (OpenAI Chat
  Completions, `OPENAI_API_KEY` secret) and a free-plan-friendly `ELEVENLABS_VOICE_ID` in `wrangler.toml`. Leave the
  upstream routes (`/chat`, `/tts`, `/transcribe-token`) unchanged. The Worker forwards no client headers.
- Models: `gpt-*` go to `/chat-openai` (`openai_client.py`), everything else to `/chat` (`claude_client.py`). Both
  yield the same TextDelta/StreamFinished events; OpenAI finish reasons are mapped to Claude's stop-reason names.
- No API keys in the app, repo, tests or logs.
- Threading: Qt objects on the GUI thread only; network on `AsyncRunner`'s loop; cross-thread results go through
  Qt signals. Screen capture (`QScreen.grabWindow`) is GUI-thread only.
- Keep `tests/test_end_to_end.py` passing. It is the contract with the Worker and AssemblyAI protocol.
- Names: descriptive over short (upstream convention). Type hints on public functions.
- Branches `feat/…` / `fix/…`; conventional commits; never commit to `main` directly.
