"""Configuración del backend leída de variables de entorno.

Los valores nunca se imprimen: los errores nombran la variable, no su contenido.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

DATASET_ID = "s2ru-bqt6"
BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_DATA = BACKEND_DIR.parent / "data"          # snapshot versionado en la raíz del repositorio
ENV_FILE = BACKEND_DIR / ".env"
SODA_URL = f"https://www.datos.gov.co/api/v3/views/{DATASET_ID}/query.json"


class ConfigError(RuntimeError):
    """Configuración inválida o incompleta. El mensaje nombra la variable, sin valores."""


def _int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"La variable de entorno {name} debe ser un entero positivo") from None
    if value < 1:
        raise ConfigError(f"La variable de entorno {name} debe ser un entero positivo")
    return value


def _nonneg(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    if not raw.isdigit():
        raise ConfigError(f"La variable de entorno {name} debe ser un entero mayor o igual a 0")
    return int(raw)


def _speed(raw: str) -> float:
    if not raw:
        return Settings.realtime_speed
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError("La variable de entorno REALTIME_SPEED debe ser un número") from None
    if not 0.25 <= value <= 1.5:
        raise ConfigError("La variable de entorno REALTIME_SPEED debe estar entre 0.25 y 1.5")
    return value


def _float(env: Mapping[str, str], name: str, default: float) -> float:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"La variable de entorno {name} debe ser un número") from None
    if not 0 <= value <= 1:
        raise ConfigError(f"La variable de entorno {name} debe estar entre 0 y 1")
    return value


def _bool(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


VAD_TYPES = ("semantic_vad", "server_vad")


@dataclass(frozen=True)
class VadConfig:
    """Detección de turno del servidor de OpenAI (valores por defecto: ver .env.example)."""
    type: str = "server_vad"          # decidido en el spike (grupo 0): ver scripts/spike_audio_results.json
    threshold: float = 0.5
    prefix_padding_ms: int = 300
    silence_duration_ms: int = 500
    eagerness: str = "auto"

    def turn_detection(self) -> dict:
        """Objeto `turn_detection` de la sesión Realtime. Siempre permite interrumpir al agente."""
        common = {"create_response": True, "interrupt_response": True}
        if self.type == "semantic_vad":
            return {"type": "semantic_vad", "eagerness": self.eagerness, **common}
        return {"type": "server_vad", "threshold": self.threshold, "prefix_padding_ms": self.prefix_padding_ms,
                "silence_duration_ms": self.silence_duration_ms, **common}

    @property
    def configured_silence_ms(self) -> int | None:
        """Silencio configurado: se publica como `vad_silence_ms`; con semantic_vad no existe."""
        return self.silence_duration_ms if self.type == "server_vad" else None


@dataclass(frozen=True)
class WsLimits:
    """Protección del WebSocket público."""
    max_sessions: int = 3
    sessions_per_minute: int = 10
    max_seconds: int = 900
    warn_seconds: int = 780


@dataclass(frozen=True)
class Settings:
    soda_app_token: str | None = field(repr=False)
    soda_page_size: int
    soda_concurrency: int
    soda_max_tries: int
    data_path: Path
    cors_origins: tuple[str, ...]
    voice_enabled: bool
    openai_api_key: str | None = field(repr=False, default=None)
    openai_realtime_model: str = "gpt-realtime-mini"
    deepgram_api_key: str | None = field(repr=False, default=None)
    realtime_voice: str = "marin"
    input_transcription_model: str = "gpt-live-transcribe"
    deepgram_model: str = "nova-3"
    openai_realtime_url: str = "wss://api.openai.com/v1/realtime"
    deepgram_url: str = "wss://api.deepgram.com/v1/listen"
    echo_window_ms: int = 0
    realtime_speed: float = 0.9          # velocidad de la voz del agente (OpenAI admite 0,25 a 1,5)
    vad: VadConfig = field(default_factory=lambda: VadConfig())
    limits: WsLimits = field(default_factory=lambda: WsLimits())

    @property
    def snapshot_path(self) -> Path:
        return self.data_path / "snapshot.parquet"

    @property
    def snapshot_meta_path(self) -> Path:
        return self.data_path / "snapshot.meta.json"


# Claves obligatorias por módulo habilitado.
_VOICE_REQUIRED = ("OPENAI_API_KEY", "DEEPGRAM_API_KEY")


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if env is None else env
    voice_enabled = _bool(env, "VOICE_ENABLED")
    if voice_enabled:
        missing = [n for n in _VOICE_REQUIRED if not env.get(n, "").strip()]
        if missing:
            raise ConfigError(
                "Falta la variable de entorno obligatoria: " + ", ".join(missing)
                + " (requerida con VOICE_ENABLED=true)"
            )
    vad_type = env.get("VAD_TYPE", "").strip() or VadConfig.type
    if vad_type not in VAD_TYPES:
        raise ConfigError("La variable de entorno VAD_TYPE debe ser semantic_vad o server_vad")
    eagerness = env.get("VAD_EAGERNESS", "").strip() or VadConfig.eagerness
    if eagerness not in ("auto", "low", "medium", "high"):
        raise ConfigError("La variable de entorno VAD_EAGERNESS debe ser auto, low, medium o high")
    vad = VadConfig(
        type=vad_type, threshold=_float(env, "VAD_THRESHOLD", VadConfig.threshold),
        prefix_padding_ms=_int(env, "VAD_PREFIX_PADDING_MS", VadConfig.prefix_padding_ms),
        silence_duration_ms=_int(env, "VAD_SILENCE_MS", VadConfig.silence_duration_ms), eagerness=eagerness)
    limits = WsLimits(
        max_sessions=_int(env, "WS_MAX_SESSIONS", WsLimits.max_sessions),
        sessions_per_minute=_int(env, "WS_SESSIONS_PER_MINUTE", WsLimits.sessions_per_minute),
        max_seconds=_int(env, "SESSION_MAX_SECONDS", WsLimits.max_seconds),
        warn_seconds=_int(env, "SESSION_WARN_SECONDS", WsLimits.warn_seconds))
    if limits.warn_seconds >= limits.max_seconds:
        raise ConfigError("SESSION_WARN_SECONDS debe ser menor que SESSION_MAX_SECONDS")
    origins = tuple(o.strip() for o in env.get("CORS_ORIGINS", "").split(",") if o.strip())
    return Settings(
        soda_app_token=env.get("SODA_APP_TOKEN", "").strip() or None,
        soda_page_size=_int(env, "SODA_PAGE_SIZE", 1000),
        soda_concurrency=_int(env, "SODA_CONCURRENCY", 4),
        soda_max_tries=_int(env, "SODA_MAX_TRIES", 5),
        data_path=_data_path(env.get("DATA_PATH", "").strip()),
        cors_origins=origins,
        voice_enabled=voice_enabled,
        openai_api_key=env.get("OPENAI_API_KEY", "").strip() or None,
        openai_realtime_model=env.get("OPENAI_REALTIME_MODEL", "").strip() or "gpt-realtime-mini",
        deepgram_api_key=env.get("DEEPGRAM_API_KEY", "").strip() or None,
        realtime_voice=env.get("REALTIME_VOICE", "").strip() or "marin",
        input_transcription_model=env.get("OPENAI_INPUT_TRANSCRIPTION_MODEL", "").strip() or "gpt-live-transcribe",
        deepgram_model=env.get("DEEPGRAM_MODEL", "").strip() or "nova-3",
        openai_realtime_url=env.get("OPENAI_REALTIME_URL", "").strip() or Settings.openai_realtime_url,
        deepgram_url=env.get("DEEPGRAM_URL", "").strip() or Settings.deepgram_url,
        echo_window_ms=_nonneg(env, "ECHO_WINDOW_MS", 0),
        realtime_speed=_speed(env.get("REALTIME_SPEED", "").strip()),
        vad=vad, limits=limits,
    )


def _data_path(raw: str) -> Path:
    """Sin DATA_PATH se usa el snapshot del repositorio; una ruta relativa que no exista desde el
    directorio actual se busca también desde backend/ (así funciona arrancando desde la raíz o desde backend/)."""
    if not raw:
        return REPO_DATA if REPO_DATA.is_dir() else Path("data")
    p = Path(raw)
    if p.is_absolute() or p.exists():
        return p
    if (BACKEND_DIR / p).exists():
        return BACKEND_DIR / p
    if REPO_DATA.is_dir():                        # p. ej. DATA_PATH=data de un .env antiguo
        return REPO_DATA
    return p


def read_env_file(path: Path) -> dict[str, str]:
    """Lee un archivo .env sencillo (CLAVE=valor). Acepta UTF-8 y UTF-16 (PowerShell)."""
    if not path.is_file():
        return {}
    raw = path.read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        out[key] = value
    return out


def load_settings_or_exit() -> Settings:
    """Carga la configuración; si es inválida termina el proceso con un mensaje claro.

    Lee `backend/.env` si existe; las variables del entorno del proceso tienen prioridad.
    """
    import logging
    import sys

    log = logging.getLogger(__name__)
    file_env = read_env_file(ENV_FILE)
    if file_env:
        log.info("Configuración leída de %s (%d variables)", ENV_FILE, len(file_env))
    else:
        log.warning("No se encontró %s: se usan solo las variables del entorno", ENV_FILE)
    try:
        settings = load_settings({**file_env, **os.environ})
        log.info("Datos en %s · voz %s", settings.data_path.resolve(),
                 "habilitada" if settings.voice_enabled else "apagada (VOICE_ENABLED no es true)")
        return settings
    except ConfigError as e:
        print(f"ERROR de configuración: {e}", file=sys.stderr)
        raise SystemExit(1) from None
