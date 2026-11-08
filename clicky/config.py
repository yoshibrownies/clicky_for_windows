"""Runtime settings, read from environment variables (and a local dotenv file at startup)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlparse

DEFAULT_HOTKEY = "win+alt"
DEFAULT_MODEL = "gpt-6.1-terra"
DEFAULT_EFFORT = "medium"
# Tray "Thinking" menu labels. Same names work for Claude (output_config.effort) and OpenAI (reasoning_effort).
EFFORT_LEVELS = {"low": "Fast", "medium": "Balanced", "high": "Deep"}
ALLOWED_EFFORT_LEVELS = tuple(EFFORT_LEVELS)
# "kokoro": free local neural voice (kokoro_voice.py). "elevenlabs": the Worker's /tts route, uses monthly credits.
VOICE_ENGINES = ("kokoro", "elevenlabs")
DEFAULT_VOICE_ENGINE = "kokoro"
DEFAULT_KOKORO_VOICE = "af_heart"
# Tray "Model" menu. Claude models are hidden while the Worker's Anthropic key is rejected (401). The /chat route
# and claude_client.py still work: to bring them back, fix the key (wrangler secret put ANTHROPIC_API_KEY) and add
# "claude-opus-5-5": "Claude Opus 5.5" and "claude-sonnet-5-5": "Claude Sonnet 5.5" here.
AVAILABLE_MODELS = {
    "gpt-6.1-terra": "GPT-6.1 Terra (OpenAI)",
    "gpt-6.1-sol": "GPT-6.1 Sol (OpenAI, smartest)",
    "gpt-6-luna": "GPT-6 Luna (OpenAI, cheapest)",
}


def is_openai_model(model: str) -> bool:
    """OpenAI models go through the Worker's /chat-openai route; everything else through /chat (Claude)."""
    return model.startswith("gpt-")


PLACEHOLDER_WORKER_HOST_FRAGMENT = "your-subdomain"


class ConfigError(ValueError):
    """Raised when settings are missing or invalid. The message is shown to the user."""


@dataclass(frozen=True)
class Settings:
    worker_base_url: str
    hotkey: str
    model: str
    effort: str
    voice_engine: str = DEFAULT_VOICE_ENGINE
    kokoro_voice: str = DEFAULT_KOKORO_VOICE

    @property
    def chat_url(self) -> str:
        return f"{self.worker_base_url}/chat"

    @property
    def tts_url(self) -> str:
        return f"{self.worker_base_url}/tts"

    @property
    def transcribe_token_url(self) -> str:
        return f"{self.worker_base_url}/transcribe-token"

    @property
    def chat_openai_url(self) -> str:
        return f"{self.worker_base_url}/chat-openai"


def _read_value(environment: Mapping[str, str], name: str, default: str) -> str:
    value = (environment.get(name) or "").strip()
    return value or default


def load_settings(environment: Mapping[str, str]) -> Settings:
    """Build Settings from an environment mapping such as os.environ."""
    worker_url = (environment.get("CLICKY_WORKER_URL") or "").strip().rstrip("/")
    if not worker_url:
        raise ConfigError("CLICKY_WORKER_URL is not set. Copy .env.example to .env and put your Worker URL in it.")
    parsed_worker_url = urlparse(worker_url)
    if parsed_worker_url.scheme not in ("http", "https") or not parsed_worker_url.netloc:
        raise ConfigError(f"CLICKY_WORKER_URL must start with https:// (or http:// for local dev): {worker_url!r}")
    if PLACEHOLDER_WORKER_HOST_FRAGMENT in parsed_worker_url.netloc:
        raise ConfigError(
            "CLICKY_WORKER_URL is still the placeholder from .env.example. "
            "Deploy the Worker (README step 1) and paste the URL it prints."
        )

    effort = _read_value(environment, "CLICKY_EFFORT", DEFAULT_EFFORT).lower()
    if effort not in ALLOWED_EFFORT_LEVELS:
        raise ConfigError(f"CLICKY_EFFORT must be one of {', '.join(ALLOWED_EFFORT_LEVELS)}, got {effort!r}")

    voice_engine = _read_value(environment, "CLICKY_VOICE", DEFAULT_VOICE_ENGINE).lower()
    if voice_engine not in VOICE_ENGINES:
        raise ConfigError(f"CLICKY_VOICE must be one of {', '.join(VOICE_ENGINES)}, got {voice_engine!r}")

    return Settings(
        worker_base_url=worker_url,
        hotkey=_read_value(environment, "CLICKY_HOTKEY", DEFAULT_HOTKEY).lower(),
        model=_read_value(environment, "CLICKY_MODEL", DEFAULT_MODEL),
        effort=effort,
        voice_engine=voice_engine,
        kokoro_voice=_read_value(environment, "CLICKY_KOKORO_VOICE", DEFAULT_KOKORO_VOICE),
    )
