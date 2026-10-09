"""Relé de voz: una conexión servidor a servidor con OpenAI Realtime por sesión.

Reenvía el audio del micrófono, ejecuta las tools de grounded-agent en el servidor y traduce los
eventos de OpenAI al contrato del WebSocket (`app/ws/protocol.py`). La clave de OpenAI solo
se usa en la cabecera del handshake: nunca se registra ni se envía al cliente.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
from dataclasses import dataclass
from typing import Any

from websockets.asyncio.client import connect as ws_connect

from app.agent.instructions import INSTRUCTIONS
from app.agent.tools import MAX_ITEMS, AgentTools, ToolSession
from app.config import Settings
from app.ws import protocol as P
from app.ws.session import InvalidTransition, SessionContext

log = logging.getLogger(__name__)

REALTIME_URL = "wss://api.openai.com/v1/realtime"
SETUP_TIMEOUT_S = 15.0
CLOSE_TIMEOUT_S = 2.0
FATAL_OPENAI_ERRORS = {"invalid_api_key", "insufficient_quota", "rate_limit_exceeded", "model_not_found"}
AUDIO_DELTAS = {"response.output_audio.delta", "response.audio.delta"}
TRANSCRIPT_DELTAS = {"response.output_audio_transcript.delta", "response.audio_transcript.delta",
                     "response.output_text.delta"}
TRANSCRIPT_DONES = {"response.output_audio_transcript.done", "response.audio_transcript.done",
                    "response.output_text.done"}


class RelayError(RuntimeError):
    """No se pudo establecer la sesión con OpenAI. El mensaje nunca contiene claves."""


@dataclass
class Turn:
    id: str
    kind: str                       # "voice" | "text" | "brief"
    t0: float                       # referencia de latencia: fin de habla del VAD, envío del texto o inicio del brief
    t_first_audio: float | None = None
    tool_ms: float = 0.0
    has_tools: bool = False
    text: str = ""
    audio_started: bool = False
    interrupted: bool = False


def build_session_update(settings: Settings, tool_schemas: list[dict], audio_out: bool) -> dict:
    """Configuración de la sesión Realtime (formato GA)."""
    audio: dict[str, Any] = {"input": {
        "format": {"type": "audio/pcm", "rate": P.SAMPLE_RATE},
        "turn_detection": settings.vad.turn_detection(),
        "transcription": {"model": settings.input_transcription_model}}}
    if audio_out:
        audio["output"] = {"format": {"type": "audio/pcm", "rate": P.SAMPLE_RATE}, "voice": settings.realtime_voice}
    return {"type": "session.update", "session": {
        "type": "realtime", "instructions": INSTRUCTIONS, "output_modalities": ["audio"] if audio_out else ["text"],
        "audio": audio, "tools": tool_schemas, "tool_choice": "auto"}}


def summarize_for_ui(result: dict) -> dict:
    """Resumen de evidencia para `agent.tool`: el resultado compacto de la tool, con listas de 10 como máximo."""
    out = {}
    for k, v in result.items():
        out[k] = v[:MAX_ITEMS] if isinstance(v, list) else v
    return out


class RealtimeRelay:
    def __init__(self, settings: Settings, tools: AgentTools, *, url: str = REALTIME_URL) -> None:
        self._s = settings
        self._tools = tools
        self._session = ToolSession(tools)
        self._url = url
        self.ctx: SessionContext | None = None
        self.ws: Any = None
        self._reader: asyncio.Task | None = None
        self._closing = False
        self.turn: Turn | None = None           # turno cuya respuesta está en curso
        self._user_turn: Turn | None = None     # último turno de voz del usuario (para asociar la transcripción)
        self._utt_start_ms = 0
        self._utt_end_ms = 0
        self._audio_buf = b""
        self.played: dict[str, int] = {}
        self.fallback_transcripts = True        # sin Deepgram, el texto del usuario sale de OpenAI (degradado)

    # -- ciclo de vida ------------------------------------------------------------
    async def start(self, ctx: SessionContext) -> None:
        self.ctx = ctx
        key = self._s.openai_api_key
        if not key:
            raise RelayError("sin clave de OpenAI")
        try:
            self.ws = await ws_connect(f"{self._url}?model={self._s.openai_realtime_model}",
                                       additional_headers={"Authorization": f"Bearer {key}"},
                                       max_size=None, open_timeout=SETUP_TIMEOUT_S)
            await self._expect("session.created")
            await self.ws.send(json.dumps(build_session_update(self._s, self._tools.schemas(), ctx.options.audio_out)))
            await self._expect("session.updated")
        except RelayError:
            await self.stop()
            raise
        except Exception as e:  # noqa: BLE001
            await self.stop()
            raise RelayError(type(e).__name__) from None
        self._reader = asyncio.create_task(self._read_loop())

    async def _expect(self, event_type: str) -> dict:
        while True:
            ev = json.loads(await asyncio.wait_for(self.ws.recv(), SETUP_TIMEOUT_S))
            if ev["type"] == event_type:
                return ev
            if ev["type"] == "error":
                raise RelayError("OpenAI rechazó la configuración de la sesión")

    async def begin(self, ctx: SessionContext) -> None:
        if ctx.options.brief == "speak" and ctx.brief:
            self.turn = Turn(P.TurnIds.BRIEF, "brief", time.monotonic())
            await self._send({"type": "response.create", "response": {
                "instructions": "Di en voz alta este texto de bienvenida, tal cual, sin añadir ni quitar nada: "
                                + ctx.brief["texto"]}})
        else:
            await self._state("escuchando")

    async def stop(self) -> None:
        self._closing = True
        reader, ws = self._reader, self.ws
        self._reader = self.ws = None
        if reader is not None and reader is not asyncio.current_task():
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
        if ws is not None:
            try:
                await asyncio.wait_for(ws.close(), CLOSE_TIMEOUT_S)
            except Exception:  # noqa: BLE001
                pass

    # -- entradas del cliente -----------------------------------------------------
    async def on_audio(self, frame: bytes) -> None:
        if self.ws is not None and not self._closing:
            await self._send({"type": "input_audio_buffer.append", "audio": base64.b64encode(frame).decode()})

    async def on_text(self, turn_id: str, text: str) -> None:
        self._session.begin_turn()
        self.turn = Turn(turn_id, "text", time.monotonic())
        await self._state("pensando")
        await self._send({"type": "conversation.item.create", "item": {
            "type": "message", "role": "user", "content": [{"type": "input_text", "text": text}]}})
        await self._send({"type": "response.create"})

    async def on_playback(self, turn_id: str, played_ms: int) -> None:
        self.played[turn_id] = played_ms

    # -- utilidades ---------------------------------------------------------------
    async def _send(self, payload: dict) -> None:
        if self.ws is None:
            return
        try:
            await self.ws.send(json.dumps(payload, ensure_ascii=False))
        except Exception:  # noqa: BLE001 - el bucle de lectura detecta la caída
            log.warning("No se pudo enviar a OpenAI (%s)", payload.get("type"))

    async def _state(self, state: str, detail: str | None = None) -> None:
        try:
            await self.ctx.set_state(state, detail)
        except InvalidTransition as e:
            log.debug("Transición ignorada: %s", e)

    # -- eventos de OpenAI -> contrato -------------------------------------------------
    async def _read_loop(self) -> None:
        try:
            async for raw in self.ws:
                try:
                    await self._on_event(json.loads(raw))
                except Exception as e:  # noqa: BLE001 - un evento malo no tumba la sesión
                    log.error("Error procesando evento de OpenAI: %s", type(e).__name__)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            log.warning("Conexión con OpenAI interrumpida: %s", type(e).__name__)
        if not self._closing:
            await self.ctx.fail("openai_unavailable", "conexión con OpenAI perdida")

    async def _on_event(self, ev: dict) -> None:
        et = ev.get("type", "")
        ctx = self.ctx
        now = time.monotonic()
        if et == "input_audio_buffer.speech_started":
            self._utt_start_ms = ctx.ts_ms
        elif et == "input_audio_buffer.speech_stopped":
            self._utt_end_ms = ctx.ts_ms
            self._session.begin_turn()
            self._user_turn = self.turn = Turn(ctx.ids.next_turn(), "voice", now)
            await self._state("pensando")
        elif et == "conversation.item.input_audio_transcription.completed":
            await self._on_user_transcript(ev.get("transcript", ""))
        elif et in AUDIO_DELTAS:
            await self._on_audio_delta(ev.get("delta", ""), now)
        elif et in TRANSCRIPT_DELTAS:
            await self._on_agent_text(ev.get("delta", ""))
        elif et in TRANSCRIPT_DONES:
            if self.turn is not None and (ev.get("transcript") or ev.get("text")):
                self.turn.text = ev.get("transcript") or ev.get("text")
        elif et == "response.done":
            await self._on_response_done(ev.get("response", {}), now)
        elif et == "error":
            code = (ev.get("error") or {}).get("code") or (ev.get("error") or {}).get("type") or "unknown"
            log.warning("Error de OpenAI: %s", str(code)[:60])
            if code in FATAL_OPENAI_ERRORS:
                await ctx.fail("openai_unavailable", "servicio de voz no disponible")

    async def _on_user_transcript(self, text: str) -> None:
        text = (text or "").strip()
        if not text or not self.fallback_transcripts or self._user_turn is None:
            return
        await self.ctx.emit(P.TranscriptFinal, turn_id=self._user_turn.id, utt_id=self.ctx.ids.next_utt(),
                            speaker="user", ts=self._utt_start_ms, ts_end=max(self._utt_end_ms, self._utt_start_ms),
                            text=text, source="openai", degraded=True)

    async def _on_audio_delta(self, delta_b64: str, now: float) -> None:
        turn = self.turn
        if turn is None or not self.ctx.options.audio_out:
            return
        if not turn.audio_started:
            turn.audio_started, turn.t_first_audio = True, now
            await self._state("hablando")
            await self.ctx.emit(P.AudioStart, turn_id=turn.id)
        self._audio_buf += base64.b64decode(delta_b64)
        while len(self._audio_buf) >= P.FRAME_BYTES:      # el contrato fija frames de 40 ms
            frame, self._audio_buf = self._audio_buf[:P.FRAME_BYTES], self._audio_buf[P.FRAME_BYTES:]
            await self.ctx.conn.send_audio(frame)

    async def _on_agent_text(self, delta: str) -> None:
        turn = self.turn
        if turn is None or not delta:
            return
        turn.text += delta
        await self.ctx.emit(P.AgentText, turn_id=turn.id, text=turn.text, final=False, interrupted=False)

    async def _on_response_done(self, resp: dict, now: float) -> None:
        turn = self.turn
        calls = [o for o in resp.get("output", []) if o.get("type") == "function_call"]
        if calls and turn is not None:
            await self._run_tools(turn, calls)
            return
        if turn is not None:
            await self._finish_turn(turn, now)

    async def _run_tools(self, turn: Turn, calls: list[dict]) -> None:
        ctx = self.ctx
        turn.has_tools = True
        for fc in calls:
            try:
                args = json.loads(fc.get("arguments") or "{}")
            except ValueError:
                args = {}
            call_id = fc.get("call_id", "")
            await ctx.emit(P.AgentTool, turn_id=turn.id, call_id=call_id, name=fc.get("name", ""), args=args,
                           status="running")
            t1 = time.monotonic()
            out = await asyncio.to_thread(self._session.call, fc.get("name", ""), args)
            turn.tool_ms += (time.monotonic() - t1) * 1000
            failed = out.get("estado") in ("error_validacion", "limite_llamadas")
            await ctx.emit(P.AgentTool, turn_id=turn.id, call_id=call_id, name=fc.get("name", ""), args=args,
                           status="error" if failed else "done", summary=summarize_for_ui(out))
            await self._send({"type": "conversation.item.create", "item": {
                "type": "function_call_output", "call_id": call_id, "output": json.dumps(out, ensure_ascii=False)}})
        await self._send({"type": "response.create"})

    async def _finish_turn(self, turn: Turn, now: float) -> None:
        ctx = self.ctx
        if self._audio_buf and turn.audio_started:          # resto parcial: se rellena a 40 ms
            await ctx.conn.send_audio(self._audio_buf.ljust(P.FRAME_BYTES, b"\0"))
        self._audio_buf = b""
        await ctx.emit(P.AgentText, turn_id=turn.id, text=turn.text, final=True, interrupted=turn.interrupted)
        if turn.audio_started:
            await ctx.emit(P.AudioEnd, turn_id=turn.id)
        if turn.kind != "brief":
            first = round((turn.t_first_audio - turn.t0) * 1000) if turn.t_first_audio else None
            await ctx.emit(P.Metrics, turn_id=turn.id, first_audio_ms=first,
                           vad_silence_ms=self._s.vad.configured_silence_ms if turn.kind == "voice" else None,
                           tool_ms=round(turn.tool_ms) if turn.has_tools else None,
                           total_ms=round((now - turn.t0) * 1000))
        self.turn = None
        await self._state("escuchando")
