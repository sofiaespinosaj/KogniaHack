"""Conexión WebSocket y contexto de sesión: numeración por `seq`, máquina de estados y emisión de eventos."""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Protocol

from fastapi import WebSocket
from pydantic import BaseModel

from app.ws import protocol as P

log = logging.getLogger(__name__)

# Transiciones permitidas de session.state. `error` puede alcanzarse desde cualquier estado.
TRANSITIONS: dict[str | None, set[str]] = {
    None: {"conectando"},
    "conectando": {"listo", "error"},
    "listo": {"escuchando", "pensando", "hablando", "error"},
    "escuchando": {"pensando", "hablando", "error"},
    "pensando": {"hablando", "escuchando", "error"},
    "hablando": {"escuchando", "pensando", "error"},
    "error": {"conectando"},
}


class InvalidTransition(RuntimeError):
    pass


class Connection:
    """Una conexión WebSocket. `seq` crece por conexión y se asigna al enviar, bajo un lock."""

    def __init__(self, ws: WebSocket) -> None:
        self.ws = ws
        self.seq = 0
        self._lock = asyncio.Lock()
        self.closed = False

    async def send(self, cls: type[BaseModel], **fields: Any) -> dict:
        async with self._lock:
            self.seq += 1
            msg = cls(seq=self.seq, **fields)
            data = msg.model_dump(mode="json", exclude_none=True)
            if not self.closed:
                try:
                    await self.ws.send_json(data)
                except Exception:  # noqa: BLE001 - cliente ya desconectado
                    self.closed = True
            return data

    async def send_audio(self, frame: bytes) -> None:
        async with self._lock:
            if not self.closed:
                try:
                    await self.ws.send_bytes(frame)
                except Exception:  # noqa: BLE001
                    self.closed = True

    async def error(self, code: str, *, detail: dict | None = None, message: str | None = None,
                    severity: str | None = None, recoverable: bool | None = None) -> dict:
        text, sev, rec = P.ERROR_TEXT[code]
        return await self.send(P.ErrorMsg, code=code, message=message or text, severity=severity or sev,
                               recoverable=rec if recoverable is None else recoverable, detail=detail)


@dataclass
class SessionOptions:
    brief: str = "speak"
    audio_out: bool = True


class SessionContext:
    """Lo que un backend de voz necesita para hablar con el cliente."""

    def __init__(self, conn: Connection, options: SessionOptions, voice_status: str, brief: dict | None) -> None:
        self.conn = conn
        self.options = options
        self.brief = brief
        self.voice_status = voice_status
        self.ids = P.TurnIds()
        self.state: str | None = None
        self.started = time.monotonic()
        self.on_fatal: Any = None   # callback async del manejador: libera la sesión tras un fallo fatal
        self.on_final: Any = None   # callback síncrono tras cada transcript.final humano (sentimiento)

    @property
    def ts_ms(self) -> int:
        """Milisegundos desde el inicio de la sesión (para `ts` y `ts_end`)."""
        return round((time.monotonic() - self.started) * 1000)

    async def set_state(self, state: str, detail: str | None = None) -> None:
        if state == self.state:
            return
        if state not in TRANSITIONS.get(self.state, set()):
            raise InvalidTransition(f"{self.state} -> {state}")
        self.state = state
        first = state in ("conectando", "listo")
        await self.conn.send(P.SessionState, state=state, detail=detail,
                             protocol=P.PROTOCOL if first else None, voice=self.voice_status if first else None)

    async def emit(self, cls: type[BaseModel], **fields: Any) -> dict:
        data = await self.conn.send(cls, **fields)
        if cls is P.TranscriptFinal and self.on_final is not None and fields.get("speaker") != "agent":
            try:
                self.on_final(data)      # el análisis corre aparte: nunca retrasa ni rompe la voz
            except Exception as e:  # noqa: BLE001
                log.warning("No se pudo lanzar el análisis de sentimiento: %s", type(e).__name__)
        return data

    async def error(self, code: str, **kw: Any) -> dict:
        return await self.conn.error(code, **kw)

    async def fail(self, code: str, detail: str | None = None) -> None:
        """Fallo fatal de la voz: error tipificado, estado `error`, WebSocket abierto y sesión liberada."""
        if self.state == "error":
            return
        await self.conn.error(code)
        self.state = "error"
        await self.conn.send(P.SessionState, state="error", detail=detail)
        if self.on_fatal is not None:
            await self.on_fatal()


class VoiceBackend(Protocol):
    """Contrato entre el manejador del WebSocket y el relé de voz (OpenAI Realtime, o uno simulado)."""

    async def start(self, ctx: SessionContext) -> None:
        """Abre las conexiones externas. Debe lanzar excepción si OpenAI no está disponible."""

    async def begin(self, ctx: SessionContext) -> None:
        """La sesión está `listo` y el brief ya se emitió: habla el brief (si procede) y pasa a escuchar."""

    async def on_audio(self, frame: bytes) -> None: ...

    async def on_text(self, turn_id: str, text: str) -> None: ...

    async def on_playback(self, turn_id: str, played_ms: int) -> None: ...

    async def stop(self) -> None: ...


BackendFactory = Any  # Callable[[], VoiceBackend]; se mantiene flexible para inyectar simulados en pruebas


@dataclass
class _Throttle:
    interval: float = 1.0
    last: dict[str, float] = field(default_factory=dict)

    def ok(self, key: str) -> bool:
        now = time.monotonic()
        if now - self.last.get(key, -1e9) >= self.interval:
            self.last[key] = now
            return True
        return False
