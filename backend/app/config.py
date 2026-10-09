"""Configuración del backend leída de variables de entorno.

Los valores nunca se imprimen: los errores nombran la variable, no su contenido.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

DATASET_ID = "s2ru-bqt6"
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


def _bool(env: Mapping[str, str], name: str) -> bool:
    return env.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


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
    origins = tuple(o.strip() for o in env.get("CORS_ORIGINS", "").split(",") if o.strip())
    return Settings(
        soda_app_token=env.get("SODA_APP_TOKEN", "").strip() or None,
        soda_page_size=_int(env, "SODA_PAGE_SIZE", 1000),
        soda_concurrency=_int(env, "SODA_CONCURRENCY", 4),
        soda_max_tries=_int(env, "SODA_MAX_TRIES", 5),
        data_path=Path(env.get("DATA_PATH", "").strip() or "data"),
        cors_origins=origins,
        voice_enabled=voice_enabled,
        openai_api_key=env.get("OPENAI_API_KEY", "").strip() or None,
        openai_realtime_model=env.get("OPENAI_REALTIME_MODEL", "").strip() or "gpt-realtime-mini",
        deepgram_api_key=env.get("DEEPGRAM_API_KEY", "").strip() or None,
    )


def load_settings_or_exit() -> Settings:
    """Carga la configuración; si es inválida termina el proceso con un mensaje claro."""
    import sys

    try:
        return load_settings()
    except ConfigError as e:
        print(f"ERROR de configuración: {e}", file=sys.stderr)
        raise SystemExit(1) from None
