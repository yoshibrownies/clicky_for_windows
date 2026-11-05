import pytest

from clicky.config import ConfigError, load_settings


def test_reads_values_and_strips_trailing_slash():
    settings = load_settings(
        {
            "CLICKY_WORKER_URL": "https://clicky-proxy.example.workers.dev/",
            "CLICKY_HOTKEY": "right_ctrl",
            "CLICKY_MODEL": "claude-sonnet-5-5",
            "CLICKY_EFFORT": "medium",
        }
    )
    assert settings.worker_base_url == "https://clicky-proxy.example.workers.dev"
    assert settings.hotkey == "right_ctrl"
    assert settings.model == "claude-sonnet-5-5"
    assert settings.effort == "medium"
    assert settings.chat_url == "https://clicky-proxy.example.workers.dev/chat"
    assert settings.tts_url == "https://clicky-proxy.example.workers.dev/tts"
    assert settings.transcribe_token_url == "https://clicky-proxy.example.workers.dev/transcribe-token"


def test_defaults():
    settings = load_settings({"CLICKY_WORKER_URL": "http://localhost:8787"})
    assert settings.hotkey == "ctrl+alt"
    assert settings.model == "claude-opus-5-5"
    assert settings.effort == "low"


def test_blank_values_fall_back_to_defaults():
    settings = load_settings({"CLICKY_WORKER_URL": "http://localhost:8787", "CLICKY_HOTKEY": "  "})
    assert settings.hotkey == "ctrl+alt"


@pytest.mark.parametrize("bad_url", [None, "", "   ", "clicky-proxy.workers.dev", "ftp://x.dev"])
def test_missing_or_invalid_worker_url_raises(bad_url):
    environment = {} if bad_url is None else {"CLICKY_WORKER_URL": bad_url}
    with pytest.raises(ConfigError):
        load_settings(environment)


def test_placeholder_url_is_rejected():
    with pytest.raises(ConfigError, match="placeholder"):
        load_settings({"CLICKY_WORKER_URL": "https://clicky-proxy.your-subdomain.workers.dev"})


def test_invalid_effort_raises():
    with pytest.raises(ConfigError):
        load_settings({"CLICKY_WORKER_URL": "http://localhost:8787", "CLICKY_EFFORT": "turbo"})
