"""Voz por etapas: Deepgram escucha, Groq piensa (con las tools sobre DuckDB) y Deepgram Aura-2 habla.

Alternativa a OpenAI Realtime (`VOICE_PROVIDER=groq`) con el mismo contrato de eventos:
- Oído: Deepgram streaming (`nova-3`, español, diarización). El fin del turno del usuario lo marca
  Deepgram (`speech_final` tras `ENDPOINTING_MS` de silencio, o `UtteranceEnd`).
- Cerebro: Groq (API compatible con OpenAI) con streaming y function calling; las tools corren aquí.
- Voz: Deepgram Aura-2 en español (`DEEPGRAM_TTS_MODEL`), una petición por frase para empezar a hablar
  antes de que termine la respuesta. El texto del agente se emite al ritmo de las frases que suenan.
- Barge-in: cualquier transcripción del usuario mientras el agente piensa o suena lo interrumpe,
  salvo que coincida con lo que el agente está diciendo (eco del altavoz).
Las claves solo viajan en cabeceras hacia Groq y Deepgram; nunca se registran ni llegan al cliente.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import unicodedata
from typing import Any, AsyncIterator

import httpx

from app.agent.instructions import INSTRUCTIONS
from app.agent.tools import AgentTools, ToolSession
from app.config import Settings
from app.voice.deepgram import DeepgramTap, Segment
from app.voice.relay import BYTES_PER_MS, PLAYBACK_MARGIN_MS, RelayError, Turn, summarize_for_ui, truncate_text
from app.voice.speakers import SpeakerMap
from app.voice.transcript import UtteranceAssembler
from app.ws import protocol as P
from app.ws.session import InvalidTransition, SessionContext

log = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 3
HISTORY_TURNS = 4                    # turnos de usuario que se conservan en el contexto del LLM
MAX_COMPLETION_TOKENS = 512          # respuestas de una a tres frases (más el razonamiento breve de gpt-oss)
MAX_RETRY_WAIT_S = 4.0               # si Groq pide esperar hasta esto, se espera; si no, se usa el modelo de respaldo
LLM_HIDDEN_TOOLS = {"group_by"}      # top_n con n hasta 10 cubre lo mismo: una tool menos en cada petición
LLM_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
TTS_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
FALLBACK_TEXT = "Perdona, tuve un problema para consultar los datos. ¿Me repites la pregunta?"
BUSY_TEXT = "Estoy recibiendo muchas preguntas a la vez. Dame unos segundos y vuelve a preguntarme, por favor."
ECHO_OVERLAP = 0.7                   # fracción de palabras del usuario que coinciden con el agente = eco
SENTENCE_END = re.compile(r"(.+?[.!?;:…])(\s+|$)", re.S)
MAX_CHUNK = 180                      # frase larga sin puntuación: se corta en una coma o un espacio
FIRST_CHUNK = 60                     # la primera frase se corta antes, en una coma, para empezar a hablar ya
TTS_AHEAD = 2                        # frases que se sintetizan por adelantado mientras suena la actual
FILLERS = ("Déjame revisar.", "Un momento, lo consulto.", "Ya te digo.", "Dame un segundo.")


class GroqError(RuntimeError):
    def __init__(self, status: int | None, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def _retry_after(headers) -> float | None:
    """Segundos que Groq pide esperar (cabecera retry-after); None si no lo dice."""
    raw = headers.get("retry-after")
    try:
        return float(raw) if raw is not None else None
    except ValueError:
        return None


def _compact_params(params: dict) -> dict:
    """Esquema más liviano para el LLM: sin la lista de 33 departamentos en cada tool (el servidor
    reconoce el nombre aunque venga sin tildes o abreviado). Ahorra cerca de la mitad de los tokens."""
    if "properties" not in params:
        return params
    props = {}
    for key, p in params["properties"].items():
        if key == "departamento":
            p = {"type": "string", "description": "Departamento completo (p. ej. Antioquia, Caldas), solo si "
                                                  "preguntan por todo el departamento. Para ciudades como Cali, "
                                                  "Bogotá, Medellín, Barranquilla, Cartagena usa siempre municipio."}
        else:
            p = _loose(p)
        props[key] = p
    return {**params, "properties": props}


def _loose(p: dict) -> dict:
    """Groq rechaza con HTTP 400 una llamada cuyos argumentos no cumplen el esquema (p. ej. «camas» frente al
    enum «CAMAS» o n=20 con máximo 10). Las listas cerradas y los rangos pasan a la descripción: guían al modelo
    sin bloquearlo, y el servidor normaliza y valida, devolviendo un error que el modelo puede corregir."""
    p = dict(p)
    notes = []
    if "enum" in p:
        notes.append("valores: " + ", ".join(str(v) for v in p.pop("enum")))
    if "minimum" in p or "maximum" in p:
        notes.append(f"entre {p.pop('minimum', 1)} y {p.pop('maximum', 10)}")
    for k in ("minLength", "maxLength"):
        p.pop(k, None)
    if notes:
        p["description"] = (p.get("description", "") + " (" + "; ".join(notes) + ")").strip()
    return p


def chat_tools(realtime_schemas: list[dict]) -> list[dict]:
    """Tools en formato Chat Completions a partir de los esquemas de `agent-tools`."""
    return [{"type": "function", "function": {"name": t["name"], "description": t.get("description", ""),
                                              "parameters": _compact_params(t["parameters"])}}
            for t in realtime_schemas if t["name"] not in LLM_HIDDEN_TOOLS]


def speakable(text: str) -> str:
    """Quita marcas de formato que la voz leería en voz alta."""
    text = re.sub(r"[*_#`>|]+", "", text)
    text = re.sub(r"^\s*[-•]\s+", "", text, flags=re.M)
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(buf: str, *, first: bool = False) -> tuple[list[str], str]:
    """Separa las frases completas del texto pendiente. Con `first`, corta antes en una coma."""
    out, pos = [], 0
    for m in SENTENCE_END.finditer(buf):
        out.append(m.group(1).strip())
        pos = m.end()
    rest = buf[pos:]
    if first and not out and len(rest) > FIRST_CHUNK:
        cut = rest.rfind(",", 0, len(rest) - 1)
        if cut >= FIRST_CHUNK // 2:
            return [rest[:cut + 1].strip()], rest[cut + 1:]
    if len(rest) > MAX_CHUNK:
        cut = max(rest.rfind(",", 0, MAX_CHUNK), rest.rfind(" ", 0, MAX_CHUNK))
        if cut > 0:
            out.append(rest[:cut + 1].strip())
            rest = rest[cut + 1:]
    return [s for s in out if s], rest


def _tokens(text: str) -> list[str]:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", text)


def is_echo(user_text: str, agent_text: str) -> bool:
    """El micrófono captó la voz del agente: casi todas las palabras están en lo que el agente dice."""
    words = _tokens(user_text)
    agent = set(_tokens(agent_text))
    if not words or not agent:
        return False
    return sum(w in agent for w in words) / len(words) >= ECHO_OVERLAP


class GroqLLM:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._s = settings
        self._http = http
        self._headers = {"Authorization": f"Bearer {settings.groq_api_key}"}

    async def check(self) -> None:
        """Valida la clave y la red al iniciar la sesión (falla rápido y con motivo claro)."""
        try:
            r = await self._http.get(f"{self._s.groq_base_url}/models", headers=self._headers, timeout=5.0)
        except httpx.HTTPError as e:
            raise RelayError(f"Groq no responde ({type(e).__name__})") from None
        if r.status_code == 401:
            raise RelayError("clave de Groq inválida (GROQ_API_KEY)")
        if r.status_code >= 400:
            raise RelayError(f"Groq respondió HTTP {r.status_code}")

    async def stream(self, messages: list[dict], tools: list[dict], *,
                     model: str | None = None) -> AsyncIterator[tuple[str, Any]]:
        """Produce ("text", delta) y, al final, ("tool_calls", [...]) si el modelo pide tools."""
        model = model or self._s.groq_model
        body: dict[str, Any] = {"model": model, "messages": messages, "tools": tools,
                                "tool_choice": "auto", "stream": True, "temperature": 0.3,
                                "max_completion_tokens": MAX_COMPLETION_TOKENS}
        if "gpt-oss" in model:
            body["reasoning_effort"] = "low"
        calls: dict[int, dict] = {}
        async with self._http.stream("POST", f"{self._s.groq_base_url}/chat/completions", json=body,
                                     headers=self._headers, timeout=LLM_TIMEOUT) as r:
            if r.status_code >= 400:
                detail = (await r.aread())[:300].decode("utf-8", "replace")
                raise GroqError(r.status_code, detail, _retry_after(r.headers))
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                chunk = json.loads(data)
                if chunk.get("error"):
                    raise GroqError(None, str(chunk["error"])[:300])
                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    if delta.get("content"):
                        yield "text", delta["content"]
                    for tc in delta.get("tool_calls") or []:
                        acc = calls.setdefault(tc.get("index", 0), {"id": "", "name": "", "arguments": ""})
                        acc["id"] = tc.get("id") or acc["id"]
                        fn = tc.get("function") or {}
                        acc["name"] += fn.get("name") or ""
                        acc["arguments"] += fn.get("arguments") or ""
        if calls:
            yield "tool_calls", [calls[i] for i in sorted(calls)]


class DeepgramTTS:
    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self._s = settings
        self._http = http
        params: dict[str, Any] = {"model": settings.deepgram_tts_model, "encoding": "linear16",
                                  "sample_rate": P.SAMPLE_RATE, "container": "none"}
        if settings.deepgram_tts_speed:
            params["speed"] = settings.deepgram_tts_speed
        self._params = params
        self._headers = {"Authorization": f"Token {settings.deepgram_api_key}"}

    async def synth(self, text: str) -> AsyncIterator[bytes]:
        async with self._http.stream("POST", self._s.deepgram_tts_url, params=self._params, json={"text": text},
                                     headers=self._headers, timeout=TTS_TIMEOUT) as r:
            if r.status_code >= 400:
                detail = r.headers.get("dg-error") or (await r.aread())[:200].decode("utf-8", "replace")
                raise RuntimeError(f"Deepgram TTS HTTP {r.status_code}: {detail}")
            async for chunk in r.aiter_bytes():
                if chunk:
                    yield chunk


class CascadeVoice:
    def __init__(self, settings: Settings, tools: AgentTools, *, http: httpx.AsyncClient | None = None) -> None:
        self._s = settings
        self._tools = tools
        self._session = ToolSession(tools)
        self._own_http = http is None
        self._http = http or httpx.AsyncClient()
        self.llm = GroqLLM(settings, self._http)
        self.tts = DeepgramTTS(settings, self._http)
        self.ctx: SessionContext | None = None
        self.deepgram: DeepgramTap | None = None
        self._closing = False
        self.history: list[dict] = []
        self.turn: Turn | None = None             # turno del agente en curso (pensando o hablando)
        self._task: asyncio.Task | None = None
        self._last_spoken: Turn | None = None     # turno terminado cuyo audio puede seguir sonando
        self._spoken: dict[str, str] = {}         # texto ya enviado a la voz, por turno
        self.played: dict[str, int] = {}
        self._speakers = SpeakerMap()
        self._asm: UtteranceAssembler | None = None
        self._user_turn_id: str | None = None     # turno del usuario que está hablando
        self._user_text: list[str] = []           # enunciados completos del turno del usuario

    # -- ciclo de vida ------------------------------------------------------------
    async def start(self, ctx: SessionContext) -> None:
        self.ctx = ctx
        try:
            await self.llm.check()
        except RelayError as e:
            log.error("No se pudo iniciar Groq: %s", e)
            await self.stop()
            raise
        self.history = [{"role": "system", "content": INSTRUCTIONS}]
        self._asm = UtteranceAssembler(ctx, self._speakers)
        self.deepgram = DeepgramTap(self._s, now_ms=lambda: ctx.ts_ms, on_segment=self._on_segment,
                                    on_status=self._on_deepgram_status)
        self.deepgram.start()

    async def begin(self, ctx: SessionContext) -> None:
        if ctx.options.brief == "speak" and ctx.brief:
            turn = Turn(P.TurnIds.BRIEF, "brief", time.monotonic())
            self._launch(turn, self._speak_brief(turn, ctx.brief["texto"]))
        else:
            await self._state("escuchando")

    async def stop(self) -> None:
        self._closing = True
        task, self._task = self._task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if self.deepgram is not None:
            await self.deepgram.stop()
        if self._own_http:
            await self._http.aclose()

    # -- entradas del cliente -----------------------------------------------------
    async def on_audio(self, frame: bytes) -> None:
        if self.deepgram is not None and not self._closing:
            self.deepgram.feed(frame)

    async def on_text(self, turn_id: str, text: str) -> None:
        await self._barge_in(time.monotonic())
        turn = Turn(turn_id, "text", time.monotonic())
        self._launch(turn, self._answer(turn, text))

    async def on_playback(self, turn_id: str, played_ms: int) -> None:
        self.played[turn_id] = played_ms

    # -- utilidades ---------------------------------------------------------------
    async def _state(self, state: str, detail: str | None = None) -> None:
        try:
            await self.ctx.set_state(state, detail)
        except InvalidTransition as e:
            log.debug("Transición ignorada: %s", e)

    def _launch(self, turn: Turn, coro) -> None:
        self.turn = turn
        self._task = asyncio.create_task(coro)

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def _still_playing(self, now: float) -> bool:
        last = self._last_spoken
        if last is None or last.t_first_audio is None:
            return False
        duration_ms = last.audio_bytes / BYTES_PER_MS
        played = self.played.get(last.id)
        return (now - last.t_first_audio) * 1000 < duration_ms + PLAYBACK_MARGIN_MS and \
            (played is None or played < duration_ms - 50)

    def _agent_now_text(self) -> str:
        turn = self.turn if self.busy else self._last_spoken
        return self._spoken.get(turn.id, "") if turn else ""

    # -- Deepgram -> turnos del usuario --------------------------------------------
    async def _on_segment(self, seg: Segment) -> None:
        ctx = self.ctx
        if ctx is None or self._closing:
            return
        now = time.monotonic()
        if seg.transcript:
            agent_active = self.busy or self._still_playing(now)
            if agent_active and is_echo(seg.transcript, self._agent_now_text()):
                log.info("Segmento descartado como eco del agente (%d palabras)", len(seg.words))
                return
            if agent_active:
                await self._barge_in(now)
            if self._user_turn_id is None:
                self._user_turn_id = ctx.ids.next_turn()
                await self._state("escuchando")
            self._user_text += await self._asm.on_segment(seg, self._user_turn_id)
        if seg.speech_final and self._user_turn_id is not None:
            self._user_text += await self._asm.flush(self._user_turn_id)
            if self._user_text:
                await self._end_user_turn(now)

    async def _end_user_turn(self, now: float) -> None:
        text = " ".join(self._user_text).strip()
        turn_id = self._user_turn_id or self.ctx.ids.next_turn()
        self._user_text, self._user_turn_id = [], None
        await self._barge_in(now)
        turn = Turn(turn_id, "voice", now)
        self._launch(turn, self._answer(turn, text))

    async def _on_deepgram_status(self, healthy: bool) -> None:
        ctx = self.ctx
        if ctx is None or self._closing:
            return
        if not healthy:
            await ctx.error("deepgram_unavailable", message="No puedo escucharte en este momento (la transcripción "
                                                            "no está disponible); puedes escribir tu pregunta.")
        elif ctx.state is not None:
            await ctx.emit(P.SessionState, state=ctx.state, detail="transcripción con hablantes restablecida")

    # -- barge-in -------------------------------------------------------------------
    async def _barge_in(self, now: float) -> None:
        """El usuario habla o escribe: el agente calla, piense o hable, y el contexto conserva lo escuchado."""
        ctx = self.ctx
        if self.busy:
            turn, task = self.turn, self._task
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self._task = None
            await self._close_interrupted(turn, now, include_metrics=turn.kind != "brief")
        elif self._still_playing(now):
            await self._close_interrupted(self._last_spoken, now, include_metrics=False)
        self._last_spoken = None
        if ctx.state in ("pensando", "hablando"):
            await self._state("escuchando")

    async def _close_interrupted(self, turn: Turn, now: float, *, include_metrics: bool) -> None:
        ctx = self.ctx
        sent_ms = turn.audio_bytes // BYTES_PER_MS
        played = self.played.get(turn.id)
        if played is None and turn.t_first_audio is not None:
            played = round((now - turn.t_first_audio) * 1000)
        played_ms = min(played or 0, sent_ms)
        if turn.audio_started:
            await ctx.emit(P.AudioClear, turn_id=turn.id)
        spoken = self._spoken.get(turn.id, "")
        text = truncate_text(spoken, played_ms / sent_ms if sent_ms else 0.0)
        if spoken or turn.audio_started:
            await ctx.emit(P.AgentText, turn_id=turn.id, text=text, final=True, interrupted=True)
        if include_metrics:
            first = round((turn.t_first_audio - turn.t0) * 1000) if turn.t_first_audio else None
            await ctx.emit(P.Metrics, turn_id=turn.id, first_audio_ms=first,
                           tool_ms=round(turn.tool_ms) if turn.has_tools else None,
                           total_ms=round((now - turn.t0) * 1000), interrupted=True)
        self._remember_assistant(turn, text + " [interrumpido por el usuario]" if text else "")
        if self.turn is turn:
            self.turn = None
        log.info("Barge-in en %s (%d de %d ms reproducidos)", turn.id, played_ms, sent_ms)

    def _remember_assistant(self, turn: Turn, text: str) -> None:
        """Deja en el historial lo que el usuario realmente escuchó del agente."""
        if turn.kind == "brief" or not text:
            return
        last = self.history[-1] if self.history else None
        if last and last.get("role") == "assistant" and last.get("_turn") == turn.id:
            last["content"] = text
        else:
            self.history.append({"role": "assistant", "content": text, "_turn": turn.id})

    # -- turnos del agente ------------------------------------------------------------
    async def _speak_brief(self, turn: Turn, text: str) -> None:
        q: asyncio.Queue[str | None] = asyncio.Queue()
        sentences, rest = split_sentences(text + " ")
        for s in sentences + ([rest.strip()] if rest.strip() else []):
            q.put_nowait(s)
        q.put_nowait(None)
        try:
            await self._speak_loop(turn, q)
        except Exception as e:  # noqa: BLE001
            log.error("No se pudo hablar el brief: %s", str(e)[:200])
        await self._finish(turn)

    async def _answer(self, turn: Turn, user_text: str) -> None:
        self._session.begin_turn()
        self._trim_history()
        self.history.append({"role": "user", "content": user_text})
        await self._state("pensando")
        q: asyncio.Queue[str | None] = asyncio.Queue()
        speaker = asyncio.create_task(self._speak_loop(turn, q))
        try:
            try:
                await self._think(turn, q)
            except GroqError as e:
                log.error("Error de Groq (HTTP %s): %s", e.status, str(e)[:200])
                if e.status == 401:
                    q.put_nowait(None)
                    await speaker
                    await self.ctx.fail("openai_unavailable", "clave de Groq inválida")
                    return
                q.put_nowait(BUSY_TEXT if e.status == 429 else FALLBACK_TEXT)
            except httpx.HTTPError as e:
                log.error("Groq no respondió: %s", type(e).__name__)
                q.put_nowait(FALLBACK_TEXT)
            q.put_nowait(None)
            try:
                await speaker
            except Exception as e:  # noqa: BLE001
                log.error("Deepgram TTS falló: %s", str(e)[:200])
        except asyncio.CancelledError:
            speaker.cancel()
            await asyncio.gather(speaker, return_exceptions=True)
            raise
        self._remember_assistant(turn, self._spoken.get(turn.id, ""))
        await self._finish(turn)

    async def _think(self, turn: Turn, q: asyncio.Queue) -> None:
        """Rondas de LLM: el texto va frase a frase a la voz; las tools se ejecutan aquí."""
        tools = chat_tools(self._tools.schemas())
        messages = [{k: v for k, v in m.items() if not k.startswith("_")} for m in self.history]
        queued = 0
        for _ in range(MAX_TOOL_ROUNDS):
            buf, text, calls = "", "", None
            async for kind, value in self._llm_round(messages, tools):
                if kind == "text":
                    buf += value
                    text += value
                    sentences, buf = split_sentences(buf, first=queued == 0)
                    for s in sentences:
                        q.put_nowait(s)
                        queued += 1
                else:
                    calls = value
            if buf.strip():
                q.put_nowait(buf.strip())
                queued += 1
            if not calls:
                return
            if queued == 0 and self.ctx.options.audio_out:   # nada dicho aún: una muletilla mientras consulta
                q.put_nowait(FILLERS[len(self.history) % len(FILLERS)])
                queued += 1
            messages.append({"role": "assistant", "content": text or None, "tool_calls": [
                {"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["arguments"]}}
                for c in calls]})
            for c in calls:
                messages.append({"role": "tool", "tool_call_id": c["id"],
                                 "content": await self._run_tool(turn, c)})
        log.warning("Se alcanzó el máximo de rondas de tools en %s", turn.id)

    async def _llm_round(self, messages: list[dict], tools: list[dict]) -> AsyncIterator[tuple[str, Any]]:
        """Una ronda de LLM con recuperación: límite de uso (429) -> espera corta o modelo de respaldo;
        llamada a tool rechazada por Groq (400) o fallo del servidor (5xx) -> un reintento y luego respaldo."""
        models = [self._s.groq_model]
        if self._s.groq_fallback_model and self._s.groq_fallback_model != self._s.groq_model:
            models.append(self._s.groq_fallback_model)
        last: GroqError | None = None
        for model in models:
            for attempt in range(2):
                started = False
                try:
                    async for item in self.llm.stream(messages, tools, model=model):
                        started = True
                        yield item
                    if model != self._s.groq_model:
                        log.info("Respondió el modelo de respaldo %s", model)
                    return
                except GroqError as e:
                    if started or e.status == 401:
                        raise
                    last = e
                    log.warning("Groq %s respondió HTTP %s (intento %d): %s", model, e.status, attempt + 1,
                                str(e)[:160])
                    if e.status == 429:
                        if attempt == 0 and e.retry_after is not None and e.retry_after <= MAX_RETRY_WAIT_S:
                            await asyncio.sleep(e.retry_after)
                            continue
                        break                                   # sin cuota: siguiente modelo
                    if attempt == 0 and (e.status == 400 or (e.status or 0) >= 500):
                        await asyncio.sleep(0.3)
                        continue
                    break
        raise last if last else GroqError(None, "sin modelo disponible")

    async def _run_tool(self, turn: Turn, call: dict) -> str:
        ctx = self.ctx
        try:
            args = json.loads(call["arguments"] or "{}")
        except ValueError:
            args = {}
        if not isinstance(args, dict):
            args = {}
        turn.has_tools = True
        await ctx.emit(P.AgentTool, turn_id=turn.id, call_id=call["id"], name=call["name"], args=args,
                       status="running")
        t1 = time.monotonic()
        out = await asyncio.to_thread(self._session.call, call["name"], args)
        turn.tool_ms += (time.monotonic() - t1) * 1000
        failed = out.get("estado") in ("error_validacion", "limite_llamadas")
        await ctx.emit(P.AgentTool, turn_id=turn.id, call_id=call["id"], name=call["name"], args=args,
                       status="error" if failed else "done", summary=summarize_for_ui(out))
        return json.dumps(out, ensure_ascii=False)

    async def _speak_loop(self, turn: Turn, q: asyncio.Queue) -> None:
        """Convierte cada frase en voz y la envía en frames de 40 ms; el texto sale cuando su frase suena.

        Las frases siguientes se sintetizan por adelantado (`TTS_AHEAD`) mientras suena la actual, para que
        no haya silencios entre frases.
        """
        ctx = self.ctx
        if not ctx.options.audio_out:
            while (sentence := await q.get()) is not None:
                sentence = speakable(sentence)
                if sentence:
                    self._spoken[turn.id] = f"{self._spoken.get(turn.id, '')} {sentence}".strip()
                    await ctx.emit(P.AgentText, turn_id=turn.id, text=self._spoken[turn.id], final=False,
                                   interrupted=False)
            return
        sem = asyncio.Semaphore(TTS_AHEAD)
        ready: asyncio.Queue = asyncio.Queue()
        fetchers: list[asyncio.Task] = []

        async def fetch(sentence: str, out: asyncio.Queue) -> None:
            try:
                async with sem:
                    async for chunk in self.tts.synth(sentence):
                        out.put_nowait(chunk)
            except Exception as e:  # noqa: BLE001 - se re-lanza al reproducir esa frase
                out.put_nowait(e)
            out.put_nowait(None)

        async def produce() -> None:
            while (sentence := await q.get()) is not None:
                sentence = speakable(sentence)
                if sentence:
                    chunks: asyncio.Queue = asyncio.Queue()
                    fetchers.append(asyncio.create_task(fetch(sentence, chunks)))
                    ready.put_nowait((sentence, chunks))
            ready.put_nowait(None)

        producer = asyncio.create_task(produce())
        buf = b""
        try:
            while (item := await ready.get()) is not None:
                sentence, chunks = item
                spoken = f"{self._spoken.get(turn.id, '')} {sentence}".strip()
                announced = False
                while (chunk := await chunks.get()) is not None:
                    if isinstance(chunk, Exception):
                        raise chunk
                    if not turn.audio_started:
                        turn.audio_started, turn.t_first_audio = True, time.monotonic()
                        await self._state("hablando")
                        await ctx.emit(P.AudioStart, turn_id=turn.id)
                    if not announced:
                        announced = True
                        self._spoken[turn.id] = spoken
                        await ctx.emit(P.AgentText, turn_id=turn.id, text=spoken, final=False, interrupted=False)
                    buf += chunk
                    while len(buf) >= P.FRAME_BYTES:
                        frame, buf = buf[:P.FRAME_BYTES], buf[P.FRAME_BYTES:]
                        turn.audio_bytes += len(frame)
                        await ctx.conn.send_audio(frame)
            if buf and turn.audio_started:
                turn.audio_bytes += P.FRAME_BYTES
                await ctx.conn.send_audio(buf.ljust(P.FRAME_BYTES, b"\0"))
        finally:
            producer.cancel()
            for f in fetchers:
                f.cancel()
            await asyncio.gather(producer, *fetchers, return_exceptions=True)

    async def _finish(self, turn: Turn) -> None:
        ctx, now = self.ctx, time.monotonic()
        await ctx.emit(P.AgentText, turn_id=turn.id, text=self._spoken.get(turn.id, ""), final=True,
                       interrupted=False)
        if turn.audio_started:
            await ctx.emit(P.AudioEnd, turn_id=turn.id)
            self._last_spoken = turn
        if turn.kind != "brief":
            first = round((turn.t_first_audio - turn.t0) * 1000) if turn.t_first_audio else None
            await ctx.emit(P.Metrics, turn_id=turn.id, first_audio_ms=first,
                           vad_silence_ms=self._s.endpointing_ms if turn.kind == "voice" else None,
                           tool_ms=round(turn.tool_ms) if turn.has_tools else None,
                           total_ms=round((now - turn.t0) * 1000))
        if self.turn is turn:
            self.turn = None
        await self._state("escuchando")

    def _trim_history(self) -> None:
        """Conserva el sistema y los últimos turnos completos (sin cortar una ronda de tools)."""
        users = [i for i, m in enumerate(self.history) if m["role"] == "user"]
        if len(users) >= HISTORY_TURNS:
            cut = users[-(HISTORY_TURNS - 1)]
            self.history = self.history[:1] + self.history[cut:]
