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
import re
import time
from dataclasses import dataclass
from typing import Any

from websockets.asyncio.client import connect as ws_connect

from app.agent.instructions import INSTRUCTIONS
from app.agent.tools import MAX_ITEMS, AgentTools, ToolSession
from app.config import Settings
from app.voice.deepgram import DeepgramTap, Segment
from app.voice.speakers import SpeakerMap
from app.voice.transcript import UtteranceAssembler
from app.ws import protocol as P
from app.ws.session import InvalidTransition, SessionContext

log = logging.getLogger(__name__)

SETUP_TIMEOUT_S = 15.0
CLOSE_TIMEOUT_S = 2.0
FATAL_OPENAI_ERRORS = {"invalid_api_key", "insufficient_quota", "rate_limit_exceeded", "model_not_found"}
AUDIO_DELTAS = {"response.output_audio.delta", "response.audio.delta"}
TRANSCRIPT_DELTAS = {"response.output_audio_transcript.delta", "response.audio_transcript.delta",
                     "response.output_text.delta"}
TRANSCRIPT_DONES = {"response.output_audio_transcript.done", "response.audio_transcript.done",
                    "response.output_text.done"}
# Vocabulario para la transcripción de entrada (respaldo cuando falla Deepgram).
TRANSCRIPTION_PROMPT = ("Preguntas en español de Colombia sobre IPS (instituciones prestadoras de salud), REPS, "
                        "sedes, camas, consultorios, ambulancias, camillas, salas, nivel de atención, "
                        "departamentos y municipios de Colombia.")
BYTES_PER_MS = P.SAMPLE_RATE * 2 // 1000        # PCM16 mono 24 kHz: 48 bytes por milisegundo
PLAYBACK_MARGIN_MS = 600                        # colchón del cliente (cola de reproducción y red)


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
    response_id: str | None = None  # respuesta de OpenAI en curso para este turno
    item_id: str | None = None      # elemento de audio del asistente (para truncar)
    audio_bytes: int = 0            # audio enviado al cliente


def build_session_update(settings: Settings, tool_schemas: list[dict], audio_out: bool) -> dict:
    """Configuración de la sesión Realtime (formato GA)."""
    turn_detection = settings.vad.turn_detection()
    if settings.echo_window_ms:      # con ventana anti-eco el relé decide cuándo cancelar
        turn_detection["interrupt_response"] = False
    audio: dict[str, Any] = {"input": {
        "format": {"type": "audio/pcm", "rate": P.SAMPLE_RATE},
        "turn_detection": turn_detection,
        "transcription": {"model": settings.input_transcription_model, "language": "es",
                          "prompt": TRANSCRIPTION_PROMPT}}}
    if audio_out:
        audio["output"] = {"format": {"type": "audio/pcm", "rate": P.SAMPLE_RATE}, "voice": settings.realtime_voice,
                           "speed": settings.realtime_speed}
    return {"type": "session.update", "session": {
        "type": "realtime", "instructions": INSTRUCTIONS, "output_modalities": ["audio"] if audio_out else ["text"],
        "audio": audio, "tools": tool_schemas, "tool_choice": "auto"}}


def summarize_for_ui(result: dict) -> dict:
    """Resumen de evidencia para `agent.tool`: el resultado compacto de la tool, con listas de 10 como máximo."""
    out = {}
    for k, v in result.items():
        out[k] = v[:MAX_ITEMS] if isinstance(v, list) else v
    return out


def truncate_text(text: str, fraction: float) -> str:
    """Corta el texto del agente a la fracción reproducida, en un límite de palabra."""
    if fraction >= 1 or not text:
        return text
    cut = max(0, round(len(text) * fraction))
    m = re.match(r"^(.{0,%d})(?:\s|$)" % cut, text, flags=re.S)
    return (m.group(1) if m else text[:cut]).rstrip()


class RealtimeRelay:
    def __init__(self, settings: Settings, tools: AgentTools, *, url: str | None = None) -> None:
        self._s = settings
        self._tools = tools
        self._session = ToolSession(tools)
        self._url = url or settings.openai_realtime_url
        self.ctx: SessionContext | None = None
        self.ws: Any = None
        self._reader: asyncio.Task | None = None
        self._closing = False
        self.turn: Turn | None = None           # turno cuya respuesta está en curso
        self._user_turn: Turn | None = None     # último turno de voz del usuario (para asociar la transcripción)
        self._pending_turn_id: str | None = None  # turno del usuario que está hablando (antes del fin de habla)
        self._utt_start_ms = 0
        self._utt_end_ms = 0
        self._audio_buf = b""
        self._dead_responses: set[str] = set()
        self.played: dict[str, int] = {}
        self.deepgram: DeepgramTap | None = None
        self._speakers = SpeakerMap()
        self._asm: UtteranceAssembler | None = None
        self._asm_turn: str | None = None       # turno al que pertenece el enunciado en curso
        self._deepgram_warned = False
        self._last_spoken: Turn | None = None   # turno ya terminado en OpenAI cuyo audio puede seguir sonando

    @property
    def fallback_transcripts(self) -> bool:
        """Sin Deepgram sano, el texto del usuario sale de la transcripción de entrada de OpenAI (degradado)."""
        return self.deepgram is None or not self.deepgram.healthy

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
        self._closing = False
        self._asm = UtteranceAssembler(ctx, self._speakers)
        self._reader = asyncio.create_task(self._read_loop())
        if self._s.deepgram_api_key:
            self.deepgram = DeepgramTap(self._s, now_ms=lambda: ctx.ts_ms, on_segment=self._on_segment,
                                        on_status=self._on_deepgram_status)
            self.deepgram.start()

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
        reader, ws, dg = self._reader, self.ws, self.deepgram
        self._reader = self.ws = None
        if dg is not None:
            await dg.stop()
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
            if self.deepgram is not None:
                self.deepgram.feed(frame)        # no espera: Deepgram nunca retrasa a OpenAI

    async def on_text(self, turn_id: str, text: str) -> None:
        now = time.monotonic()
        if self.turn is not None:                # escribir encima del agente también lo interrumpe
            await self._interrupt(self.turn, now)
        elif self._still_playing(now):
            await self._interrupt_playback(self._last_spoken, now)
        self._last_spoken = None
        self._session.begin_turn()
        self.turn = Turn(turn_id, "text", now)
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

    def _transcript_turn_id(self) -> str:
        """Turno al que se asocia lo que dice el usuario."""
        if self._pending_turn_id is None and self._user_turn is None:
            self._pending_turn_id = self.ctx.ids.next_turn()
        return self._pending_turn_id or self._user_turn.id

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

    def _stale(self, ev: dict) -> bool:
        """Eventos de una respuesta cancelada o ajena al turno en curso."""
        rid = ev.get("response_id") or (ev.get("response") or {}).get("id")
        if rid is None:
            return False
        if rid in self._dead_responses:
            return True
        turn = self.turn
        return turn is None or (turn.response_id is not None and rid != turn.response_id)

    async def _on_event(self, ev: dict) -> None:
        et = ev.get("type", "")
        ctx = self.ctx
        now = time.monotonic()
        if et == "input_audio_buffer.speech_started":
            await self._on_speech_started(now)
        elif et == "input_audio_buffer.speech_stopped":
            self._utt_end_ms = ctx.ts_ms
            turn_id = self._pending_turn_id or ctx.ids.next_turn()
            self._pending_turn_id = None
            self._session.begin_turn()
            self._user_turn = self.turn = Turn(turn_id, "voice", now)
            await self._state("pensando")
        elif et == "conversation.item.input_audio_transcription.completed":
            await self._on_user_transcript(ev.get("transcript", ""))
        elif et == "response.created":
            rid = (ev.get("response") or {}).get("id")
            if self.turn is not None and rid and rid not in self._dead_responses:
                self.turn.response_id = rid
        elif self._stale(ev):
            return
        elif et in AUDIO_DELTAS:
            if self.turn is not None and ev.get("item_id"):
                self.turn.item_id = ev["item_id"]
            await self._on_audio_delta(ev.get("delta", ""), now)
        elif et in TRANSCRIPT_DELTAS:
            await self._on_agent_text(ev.get("delta", ""))
        elif et in TRANSCRIPT_DONES:
            if self.turn is not None and (ev.get("transcript") or ev.get("text")):
                self.turn.text = ev.get("transcript") or ev.get("text")
        elif et == "response.done":
            resp = ev.get("response", {})
            if resp.get("status") == "cancelled":
                return
            await self._on_response_done(resp, now)
        elif et == "error":
            code = (ev.get("error") or {}).get("code") or (ev.get("error") or {}).get("type") or "unknown"
            log.warning("Error de OpenAI: %s", str(code)[:60])
            if code in FATAL_OPENAI_ERRORS:
                await ctx.fail("openai_unavailable", "servicio de voz no disponible")

    async def _on_speech_started(self, now: float) -> None:
        ctx = self.ctx
        turn = self.turn
        if turn is not None and turn.audio_started and self._s.echo_window_ms and turn.t_first_audio is not None \
                and (now - turn.t_first_audio) * 1000 < self._s.echo_window_ms:
            log.info("Detección de voz ignorada por la ventana anti-eco")
            return
        self._utt_start_ms = ctx.ts_ms
        if self._pending_turn_id is None:
            self._pending_turn_id = ctx.ids.next_turn()
        if turn is not None:                     # el usuario habla con una respuesta en curso: barge-in
            await self._interrupt(turn, now)
        elif self._still_playing(now):           # OpenAI ya terminó pero el cliente sigue reproduciendo
            await self._interrupt_playback(self._last_spoken, now)
        self._last_spoken = None
        await self._state("escuchando")

    def _still_playing(self, now: float) -> bool:
        """OpenAI genera el audio más rápido que tiempo real: el cliente puede seguir sonando segundos después."""
        last = self._last_spoken
        if last is None or last.t_first_audio is None:
            return False
        duration_ms = last.audio_bytes / BYTES_PER_MS
        elapsed_ms = (now - last.t_first_audio) * 1000
        played = self.played.get(last.id)
        return elapsed_ms < duration_ms + PLAYBACK_MARGIN_MS and (played is None or played < duration_ms - 50)

    async def _interrupt_playback(self, turn: Turn, now: float) -> None:
        """Barge-in sobre un turno ya generado: el cliente calla y el modelo olvida lo no escuchado."""
        ctx = self.ctx
        duration_ms = turn.audio_bytes // BYTES_PER_MS
        played = self.played.get(turn.id)
        played_ms = min(played if played is not None else round((now - turn.t_first_audio) * 1000), duration_ms)
        await ctx.emit(P.AudioClear, turn_id=turn.id)
        if turn.item_id:
            await self._send({"type": "conversation.item.truncate", "item_id": turn.item_id, "content_index": 0,
                              "audio_end_ms": played_ms})
        text = truncate_text(turn.text, played_ms / duration_ms if duration_ms else 0.0)
        await ctx.emit(P.AgentText, turn_id=turn.id, text=text, final=True, interrupted=True)
        log.info("Barge-in durante la reproducción de %s (%d de %d ms)", turn.id, played_ms, duration_ms)

    async def _interrupt(self, turn: Turn, now: float) -> None:
        """Barge-in: vacía el audio del cliente, cancela la respuesta y trunca lo no reproducido."""
        ctx = self.ctx
        turn.interrupted = True
        self.turn = None
        if turn.response_id:
            self._dead_responses.add(turn.response_id)
        sent_ms = turn.audio_bytes // BYTES_PER_MS
        if turn.audio_started:
            await ctx.emit(P.AudioClear, turn_id=turn.id)
        self._audio_buf = b""
        await self._send({"type": "response.cancel"})
        played = self.played.get(turn.id)
        played_ms = sent_ms if played is None else min(played, sent_ms)
        if turn.audio_started and turn.item_id:
            await self._send({"type": "conversation.item.truncate", "item_id": turn.item_id, "content_index": 0,
                              "audio_end_ms": played_ms})
        text = truncate_text(turn.text, played_ms / sent_ms if sent_ms else 0.0)
        if turn.text or turn.audio_started:
            await ctx.emit(P.AgentText, turn_id=turn.id, text=text, final=True, interrupted=True)
        if turn.kind != "brief":
            first = round((turn.t_first_audio - turn.t0) * 1000) if turn.t_first_audio else None
            await ctx.emit(P.Metrics, turn_id=turn.id, first_audio_ms=first,
                           tool_ms=round(turn.tool_ms) if turn.has_tools else None,
                           total_ms=round((now - turn.t0) * 1000), interrupted=True)
        log.info("Barge-in en %s (%d ms reproducidos)", turn.id, played_ms)

    async def _on_user_transcript(self, text: str) -> None:
        text = (text or "").strip()
        if not text or not self.fallback_transcripts or self._user_turn is None:
            return
        await self.ctx.emit(P.TranscriptFinal, turn_id=self._user_turn.id, utt_id=self.ctx.ids.next_utt(),
                            speaker="user", ts=self._utt_start_ms, ts_end=max(self._utt_end_ms, self._utt_start_ms),
                            text=text, source="openai", degraded=True)

    # -- Deepgram -> contrato -----------------------------------------------------------
    async def _on_segment(self, seg: Segment) -> None:
        if self.ctx is None or self._closing or self._asm is None:
            return
        if seg.transcript:
            if self._asm.cur is None:
                self._asm_turn = self._transcript_turn_id()
            await self._asm.on_segment(seg, self._asm_turn)
        if seg.speech_final and self._asm_turn is not None:
            await self._asm.flush(self._asm_turn)

    async def _on_deepgram_status(self, healthy: bool) -> None:
        ctx = self.ctx
        if ctx is None or self._closing:
            return
        if not healthy:
            await ctx.error("deepgram_unavailable")
        elif ctx.state is not None:
            await ctx.emit(P.SessionState, state=ctx.state, detail="transcripción con hablantes restablecida")

    # -- audio y texto del agente -------------------------------------------------------
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
            turn.audio_bytes += len(frame)
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
        if self.turn is turn:                    # si el usuario interrumpió durante la tool, no se responde
            turn.response_id = None
            await self._send({"type": "response.create"})

    async def _finish_turn(self, turn: Turn, now: float) -> None:
        ctx = self.ctx
        if self._audio_buf and turn.audio_started:          # resto parcial: se rellena a 40 ms
            turn.audio_bytes += P.FRAME_BYTES
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
        if turn.audio_started:
            self._last_spoken = turn
        await self._state("escuchando")
