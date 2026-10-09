import pytest

from app.config import ConfigError, load_settings


def test_defaults():
    s = load_settings({})
    assert (s.soda_page_size, s.soda_concurrency, s.soda_max_tries) == (1000, 4, 5)
    assert s.soda_app_token is None
    assert not s.voice_enabled


def test_missing_voice_key_names_variable_without_values():
    env = {"VOICE_ENABLED": "true", "OPENAI_API_KEY": "sk-secret-value"}
    with pytest.raises(ConfigError) as exc:
        load_settings(env)
    msg = str(exc.value)
    assert "DEEPGRAM_API_KEY" in msg
    assert "sk-secret-value" not in msg


def test_voice_keys_not_required_when_disabled():
    assert load_settings({"VOICE_ENABLED": "false"}).openai_api_key is None


def test_invalid_int_names_variable():
    with pytest.raises(ConfigError, match="SODA_PAGE_SIZE"):
        load_settings({"SODA_PAGE_SIZE": "abc"})


def test_repr_hides_secrets():
    s = load_settings({"OPENAI_API_KEY": "sk-secret-value", "SODA_APP_TOKEN": "tok-secret"})
    # openai/deepgram ocultas por repr=False; el token se oculta en el cliente
    assert "sk-secret-value" not in repr(s)


def test_startup_exits_with_clear_message(tmp_path):
    import os
    import subprocess
    import sys

    env = {k: v for k, v in os.environ.items() if k not in ("DEEPGRAM_API_KEY",)}
    env.update({"VOICE_ENABLED": "true", "OPENAI_API_KEY": "sk-secret-value"})
    r = subprocess.run(
        [sys.executable, "-c", "from app.config import load_settings_or_exit; load_settings_or_exit()"],
        env=env, capture_output=True, text=True,
    )
    assert r.returncode == 1
    assert "DEEPGRAM_API_KEY" in r.stderr
    assert "sk-secret-value" not in r.stderr + r.stdout
    assert "Traceback" not in r.stderr
