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


# --- voz (realtime-voice grupo 1) ---------------------------------------------------
def test_voice_defaults():
    s = load_settings({})
    assert (s.realtime_voice, s.input_transcription_model, s.deepgram_model) == ("marin", "gpt-live-transcribe", "nova-3")
    assert (s.limits.max_sessions, s.limits.sessions_per_minute, s.limits.max_seconds, s.limits.warn_seconds) == \
        (3, 10, 900, 780)


def test_voice_overrides_from_env():
    s = load_settings({"REALTIME_VOICE": "cedar", "OPENAI_INPUT_TRANSCRIPTION_MODEL": "x", "DEEPGRAM_MODEL": "nova-x",
                       "WS_MAX_SESSIONS": "5", "SESSION_MAX_SECONDS": "600", "SESSION_WARN_SECONDS": "500"})
    assert (s.realtime_voice, s.input_transcription_model, s.deepgram_model) == ("cedar", "x", "nova-x")
    assert (s.limits.max_sessions, s.limits.max_seconds, s.limits.warn_seconds) == (5, 600, 500)


def test_vad_semantic_and_server_turn_detection():
    sem = load_settings({"VAD_TYPE": "semantic_vad", "VAD_EAGERNESS": "high"}).vad
    assert sem.turn_detection() == {"type": "semantic_vad", "eagerness": "high",
                                    "create_response": True, "interrupt_response": True}
    assert sem.configured_silence_ms is None            # con semantic_vad no se publica vad_silence_ms
    srv = load_settings({"VAD_TYPE": "server_vad"}).vad
    assert srv.turn_detection() == {"type": "server_vad", "threshold": 0.5, "prefix_padding_ms": 300,
                                    "silence_duration_ms": 500, "create_response": True, "interrupt_response": True}
    assert srv.configured_silence_ms == 500


def test_vad_values_are_configurable():
    v = load_settings({"VAD_TYPE": "server_vad", "VAD_THRESHOLD": "0.7", "VAD_PREFIX_PADDING_MS": "200",
                       "VAD_SILENCE_MS": "800"}).vad.turn_detection()
    assert (v["threshold"], v["prefix_padding_ms"], v["silence_duration_ms"]) == (0.7, 200, 800)


@pytest.mark.parametrize("env,var", [
    ({"VAD_TYPE": "otro"}, "VAD_TYPE"), ({"VAD_THRESHOLD": "2"}, "VAD_THRESHOLD"),
    ({"VAD_EAGERNESS": "x"}, "VAD_EAGERNESS"), ({"VAD_SILENCE_MS": "-1"}, "VAD_SILENCE_MS"),
    ({"SESSION_MAX_SECONDS": "100", "SESSION_WARN_SECONDS": "200"}, "SESSION_WARN_SECONDS"),
])
def test_invalid_voice_settings_name_the_variable(env, var):
    with pytest.raises(ConfigError, match=var):
        load_settings(env)


def test_health_reports_voice_status():
    import time
    from fastapi.testclient import TestClient
    from app.main import create_app
    for flag, expected in (("false", "disabled"), ("true", "enabled")):
        env = {"VOICE_ENABLED": flag, "OPENAI_API_KEY": "k", "DEEPGRAM_API_KEY": "k"}
        with TestClient(create_app(load_settings(env))) as c:
            assert c.get("/health").json()["voice"] == expected


def test_default_data_path_is_repo_snapshot():
    from app.config import REPO_DATA
    assert load_settings({}).data_path == REPO_DATA
    assert (load_settings({}).data_path / "snapshot.parquet").is_file()


def test_relative_data_path_resolves_from_backend(tmp_path, monkeypatch):
    from app.config import REPO_DATA
    monkeypatch.chdir(tmp_path)                       # p. ej. arrancando desde otra carpeta
    assert load_settings({"DATA_PATH": "../data"}).data_path.resolve() == REPO_DATA.resolve()


def test_env_file_utf8_and_utf16(tmp_path):
    from app.config import read_env_file
    body = '# comentario\nVOICE_ENABLED=true\nOPENAI_API_KEY="sk-x"\n\nDATA_PATH=../data\n'
    f8 = tmp_path / "a.env"
    f8.write_text("﻿" + body, encoding="utf-8")
    f16 = tmp_path / "b.env"
    f16.write_text(body, encoding="utf-16")             # lo que produce `echo ... > .env` en PowerShell
    for f in (f8, f16):
        assert read_env_file(f) == {"VOICE_ENABLED": "true", "OPENAI_API_KEY": "sk-x", "DATA_PATH": "../data"}
    assert read_env_file(tmp_path / "no.env") == {}


def test_process_env_overrides_env_file(tmp_path, monkeypatch):
    import app.config as C
    f = tmp_path / ".env"
    f.write_text("VOICE_ENABLED=false\nCORS_ORIGINS=http://a\n", encoding="utf-8")
    monkeypatch.setattr(C, "ENV_FILE", f)
    monkeypatch.setenv("CORS_ORIGINS", "http://b")
    monkeypatch.delenv("VOICE_ENABLED", raising=False)
    s = C.load_settings_or_exit()
    assert s.cors_origins == ("http://b",) and s.voice_enabled is False


def test_stale_relative_data_path_falls_back_to_repo(tmp_path, monkeypatch):
    from app.config import REPO_DATA
    monkeypatch.chdir(tmp_path)
    assert load_settings({"DATA_PATH": "data"}).data_path == REPO_DATA


def test_realtime_speed():
    assert load_settings({}).realtime_speed == 0.9
    assert load_settings({"REALTIME_SPEED": "1.1"}).realtime_speed == 1.1
    with pytest.raises(ConfigError):
        load_settings({"REALTIME_SPEED": "3"})
