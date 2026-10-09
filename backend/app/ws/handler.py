"""Manejo de una conexión WebSocket: despacha frames binarios (audio) y JSON (eventos)."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from fastapi import WebSocket

from app.config import WsLimits
from app.ws import protocol as P
from app.ws.limits import SessionLimiter
from app.ws.session import BackendFactory, Connection, SessionContext, SessionOptions, _Throttle

log = logging.getLogger(__name__)


class ConnectionHandler:
    def __init__(self, ws: WebSocket, *, voice_enabled: bool, backend_factory: BackendFactory | None,
                 brief_provider: Callable[[], dict | None], data_ready: Callable[[], bool],
                 limiter: SessionLimiter | None = None, limits: WsLimits | None = None,
                 client_ip: str = "desconocida") -> None:
        self.conn = Connection(ws)
        self._limiter = limiter
        self._limits = limits or WsLimits()
        self._ip = client_ip
        self._holds_slot = False
        self._timer: asyncio.Task | None = None
        self._voice_enabled = voice_enabled
        self._factory = backend_factory
        self._brief = brief_provider
        self._data_ready = data_ready
        self.ctx: SessionContext | None = None
        self.backend: Any = None
        self._throttle = _Throttle()

    @property
    def active(self) -> bool:
        return self.ctx is not None

    # -- entrada ------------------------------------------------------------------
    async def on_binary(self, frame: bytes) -> None:
        if not self.active:
            if self._throttle.ok("no_session_audio"):   # evita inundar de errores a un cliente que sigue enviando audio
                await self.conn.error("no_active_session")
            return
        if not frame or len(frame) % 2 or len(frame) > P.MAX_AUDIO_FRAME_BYTES:
            if self._throttle.ok("bad_audio"):
                await self.conn.error("invalid_message", detail={"reason": "frame de audio inválido"})
            return
        await self.backend.on_audio(frame)

    async def on_text(self, raw: str) -> None:
        try:
            data = json.loads(raw)
        except ValueError:
            await self.conn.error("invalid_message", detail={"reason": "JSON inválido"})
            return
        msg, err = P.parse_client_message(data)
        if err:
            await self.conn.error("invalid_message", detail=err)
            return
        if isinstance(msg, P.SessionStart):
            await self._start(msg)
        elif isinstance(msg, P.SessionStop):
            await self._stop()
        elif not self.active:
            await self.conn.error("no_active_session")
        elif isinstance(msg, P.TextMessage):
            turn_id = self.ctx.ids.next_turn()
            ts = self.ctx.ts_ms
            await self.ctx.emit(P.TranscriptFinal, turn_id=turn_id, utt_id=self.ctx.ids.next_utt(), speaker="user",
                                ts=ts, ts_end=ts, text=msg.text, source="text", degraded=False)
            await self.backend.on_text(turn_id, msg.text)
        elif isinstance(msg, P.PlaybackPosition):
            await self.backend.on_playback(msg.turn_id, msg.played_ms)

    # -- ciclo de vida ------------------------------------------------------------
    async def _start(self, msg: P.SessionStart) -> None:
        if self.active:
            await self.conn.error("session_already_active")
            return
        if not P.protocol_supported(msg.protocol):
            await self.conn.error("unsupported_protocol", detail={"supported": P.SUPPORTED_PROTOCOLS})
            return
        if not self._voice_enabled or self._factory is None:
            await self.conn.error("voice_disabled")
            return
        brief = self._brief() if self._data_ready() else None
        if brief is None:
            await self.conn.error("data_unavailable")
            return
        if self._limiter is not None:
            reason = self._limiter.try_acquire(self._ip)
            if reason:
                log.warning("Límite de sesiones alcanzado: %s (ip=%s)", reason, self._ip)
                await self.conn.error("session_limit", detail={"reason": reason})
                return
            self._holds_slot = True
        ctx = SessionContext(self.conn, SessionOptions(brief=msg.brief, audio_out=msg.audio_out), "enabled", brief)
        backend = self._factory()
        await ctx.set_state("conectando")
        try:
            await backend.start(ctx)
        except Exception as e:  # noqa: BLE001 - nunca se exponen trazas ni claves al cliente
            log.error("No se pudo iniciar la voz: %s", type(e).__name__)
            ctx.state = "error"
            await self.conn.error("openai_unavailable")
            await self.conn.send(P.SessionState, state="error", detail="voz no disponible")
            await _safe_stop(backend)
            self._release_slot()
            return
        self.ctx, self.backend = ctx, backend
        self._timer = asyncio.create_task(self._duration_guard(ctx))
        ctx.on_fatal = self._release_after_failure
        await ctx.set_state("listo")
        if msg.brief == "speak":
            await ctx.emit(P.SessionBrief, texto=brief["texto"], preguntas=brief["preguntas"],
                           fecha_corte=brief["fecha_corte"], origen=brief["origen"])
        await backend.begin(ctx)

    async def _stop(self) -> None:
        if not self.active:
            await self.conn.error("no_active_session")
            return
        await self.close_session(final_state=True)
        try:
            await self.conn.ws.close(code=1000)
        except Exception:  # noqa: BLE001
            pass
        self.conn.closed = True

    async def _release_after_failure(self) -> None:
        # se ejecuta en otra tarea: el relé que falló no puede cancelarse a sí mismo
        asyncio.create_task(self.close_session())

    async def _duration_guard(self, ctx: SessionContext) -> None:
        """Aviso `session_expiring` a los 13 minutos y cierre ordenado con `session_limit` a los 15."""
        lim = self._limits
        await asyncio.sleep(lim.warn_seconds)
        if self.ctx is not ctx:
            return
        await self.conn.error("session_expiring", detail={"seconds_left": lim.max_seconds - lim.warn_seconds})
        await asyncio.sleep(lim.max_seconds - lim.warn_seconds)
        if self.ctx is not ctx:
            return
        log.warning("Límite de sesiones alcanzado: duration (ip=%s)", self._ip)
        await self.conn.error("session_limit", detail={"reason": "duration"})
        self._timer = None                       # no se cancela a sí mismo al cerrar
        await self.close_session(final_state=True)
        try:
            await self.conn.ws.close(code=1000)
        except Exception:  # noqa: BLE001
            pass
        self.conn.closed = True

    def _release_slot(self) -> None:
        if self._holds_slot and self._limiter is not None:
            self._limiter.release()
        self._holds_slot = False

    async def close_session(self, *, final_state: bool = False) -> None:
        """Libera la sesión (idempotente). Se usa al parar, al desconectar y ante errores."""
        ctx, backend, timer = self.ctx, self.backend, self._timer
        self.ctx = self.backend = self._timer = None
        if timer is not None and timer is not asyncio.current_task():
            timer.cancel()
        self._release_slot()
        if backend is not None:
            await _safe_stop(backend)
        if final_state and ctx is not None and not self.conn.closed:
            await self.conn.send(P.SessionState, state="listo", detail="sesión finalizada")

    async def cleanup(self) -> None:
        await self.close_session()


async def _safe_stop(backend: Any) -> None:
    try:
        await backend.stop()
    except Exception as e:  # noqa: BLE001
        log.warning("Error al cerrar el relé de voz: %s", type(e).__name__)
