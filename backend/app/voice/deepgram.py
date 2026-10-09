"""Bifurcación del audio del micrófono hacia Deepgram streaming (nova-3, español, diarización).

Corre en tareas propias: `feed()` nunca espera, de modo que un Deepgram lento o caído no retrasa
la ruta hacia OpenAI. Si la conexión falla se avisa con `on_status(False)` y se reintenta en
segundo plano; al recuperarla se avisa con `on_status(True)`. La clave solo viaja en la cabecera.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable
from urllib.parse import urlencode

from websockets.asyncio.client import connect as ws_connect

from app.config import Settings
from app.ws import protocol as P

log = logging.getLogger(__name__)

CONNECT_TIMEOUT_S = 2.0          # el aviso de degradación debe llegar en 2 s o menos
QUEUE_FRAMES = 250               # 10 s de audio; si se llena se descartan los más viejos
KEEPALIVE_S = 5.0
BACKOFF_S = (1.0, 2.0, 4.0, 8.0)


@dataclass
class Word:
    text: str
    start_ms: int                # relativo al inicio de la sesión
    end_ms: int
    speaker: int | None          # id de hablante de Deepgram


@dataclass
class Segment:
    is_final: bool
    transcript: str
    words: list[Word]


def build_url(settings: Settings) -> str:
    q = {"model": settings.deepgram_model, "language": "es", "diarize": "true", "encoding": "linear16",
         "sample_rate": P.SAMPLE_RATE, "channels": 1, "interim_results": "true", "smart_format": "true",
         "punctuate": "true", "endpointing": 300}
    return f"{settings.deepgram_url}?{urlencode(q)}"


def parse_results(msg: dict, offset_ms: int) -> Segment | None:
    """Convierte un mensaje `Results` de Deepgram en un segmento con tiempos de sesión."""
    if msg.get("type") != "Results":
        return None
    alts = (msg.get("channel") or {}).get("alternatives") or []
    if not alts:
        return None
    alt = alts[0]
    text = (alt.get("transcript") or "").strip()
    if not text:
        return None
    words = [Word(w.get("punctuated_word") or w.get("word", ""), offset_ms + round(w.get("start", 0) * 1000),
                  offset_ms + round(w.get("end", 0) * 1000), w.get("speaker")) for w in alt.get("words") or []]
    return Segment(bool(msg.get("is_final")), text, words)


HINTS = {401: "clave inválida (DEEPGRAM_API_KEY)", 402: "sin saldo en la cuenta de Deepgram",
         403: "la clave no tiene permiso para este modelo o función", 400: "parámetros rechazados"}


def describe_failure(e: Exception) -> str:
    """Motivo legible de un fallo de conexión, sin claves: código HTTP y error de Deepgram si los hay."""
    resp = getattr(e, "response", None)
    status = getattr(resp, "status_code", None)
    if status is None:
        return type(e).__name__
    headers = getattr(resp, "headers", None) or {}
    detail = headers.get("dg-error") or (getattr(resp, "body", b"") or b"")[:200].decode("utf-8", "replace")
    hint = HINTS.get(status, "")
    return f"HTTP {status}" + (f" ({hint})" if hint else "") + (f": {detail.strip()}" if detail.strip() else "")


class DeepgramTap:
    def __init__(self, settings: Settings, *, now_ms: Callable[[], int],
                 on_segment: Callable[[Segment], Awaitable[None]],
                 on_status: Callable[[bool], Awaitable[None]]) -> None:
        self._s = settings
        self._now_ms = now_ms
        self._on_segment = on_segment
        self._on_status = on_status
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(QUEUE_FRAMES)
        self._task: asyncio.Task | None = None
        self.healthy = False
        self._offset_ms: int | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    def feed(self, frame: bytes) -> None:
        if not self.healthy:
            return
        if self._queue.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self._queue.get_nowait()
        self._queue.put_nowait(frame)

    async def stop(self) -> None:
        task, self._task = self._task, None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        self.healthy = False

    async def _run(self) -> None:
        attempt, was_down = 0, False
        while True:
            try:
                ws = await asyncio.wait_for(ws_connect(
                    build_url(self._s), additional_headers={"Authorization": f"Token {self._s.deepgram_api_key}"},
                    max_size=None, open_timeout=CONNECT_TIMEOUT_S), CONNECT_TIMEOUT_S)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("No se pudo conectar con Deepgram: %s", describe_failure(e))
                ws = None
            if ws is not None:
                attempt = 0
                while not self._queue.empty():           # no se envía audio viejo de antes de la caída
                    self._queue.get_nowait()
                self._offset_ms = None
                self.healthy = True
                if was_down:
                    await self._on_status(True)
                try:
                    await self._pump(ws)
                except asyncio.CancelledError:
                    with contextlib.suppress(Exception):
                        await asyncio.wait_for(ws.close(), 1.0)
                    raise
                except Exception as e:  # noqa: BLE001
                    code = getattr(getattr(e, "rcvd", None), "code", None)
                    why = getattr(getattr(e, "rcvd", None), "reason", "")
                    log.warning("Conexión con Deepgram interrumpida: %s%s", type(e).__name__,
                                f" (código {code}: {why[:120]})" if code else "")
                with contextlib.suppress(Exception):
                    await asyncio.wait_for(ws.close(), 1.0)
            self.healthy = False
            if not was_down:
                was_down = True
                await self._on_status(False)
            await asyncio.sleep(BACKOFF_S[min(attempt, len(BACKOFF_S) - 1)])
            attempt += 1

    async def _pump(self, ws) -> None:
        sender = asyncio.create_task(self._send_loop(ws))
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    continue
                seg = parse_results(json.loads(raw), self._offset_ms or 0)
                if seg is not None:
                    await self._on_segment(seg)
        finally:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
        raise ConnectionError("Deepgram cerró la conexión")

    async def _send_loop(self, ws) -> None:
        while True:
            try:
                frame = await asyncio.wait_for(self._queue.get(), KEEPALIVE_S)
            except asyncio.TimeoutError:
                await ws.send(json.dumps({"type": "KeepAlive"}))
                continue
            if self._offset_ms is None:                 # los tiempos de Deepgram cuentan desde el primer audio
                self._offset_ms = max(0, self._now_ms() - P.FRAME_MS)
            await ws.send(frame)
