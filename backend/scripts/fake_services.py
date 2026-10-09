"""Servidores simulados de OpenAI Realtime y Deepgram para probar la voz sin claves ni red.

Uso local (pruebas de extremo a extremo con el frontend):

    uv run python -m scripts.fake_services
    # proveedor groq (por defecto):
    GROQ_BASE_URL=http://127.0.0.1:9103/openai/v1 DEEPGRAM_TTS_URL=http://127.0.0.1:9103/v1/speak \
        DEEPGRAM_URL=ws://127.0.0.1:9102 VOICE_ENABLED=true GROQ_API_KEY=fake DEEPGRAM_API_KEY=fake \
        uv run uvicorn app.main:app
    # proveedor openai: VOICE_PROVIDER=openai OPENAI_REALTIME_URL=ws://127.0.0.1:9101 OPENAI_API_KEY=fake ...

Comportamiento simulado (suficiente para el contrato, no para la calidad):
- OpenAI: `session.created/updated`; VAD por energía sobre el audio recibido (`speech_started`,
  `speech_stopped` tras 300 ms de silencio) con transcripción de entrada fija; una pregunta provoca
  una llamada a `count_ips` y, con su salida, una respuesta hablada con audio (tono) y transcripción;
  `response.cancel` y `conversation.item.truncate` se registran.
- Deepgram: por cada ráfaga de voz envía un resultado parcial y uno final; el hablante alterna
  (0, 1, 0...) entre ráfagas para probar la diarización.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import re
import struct
from dataclasses import dataclass, field
from typing import Any

from websockets.asyncio.server import ServerConnection, serve

RATE = 24000
ENERGY = 1500           # amplitud media a partir de la cual hay voz
SILENCE_MS = 300
USER_QUESTION = "¿Cuántas IPS hay en total?"


def tone(ms: int, freq: float = 330.0, amp: int = 6000) -> bytes:
    n = RATE * ms // 1000
    return struct.pack(f"<{n}h", *(int(amp * math.sin(2 * math.pi * freq * i / RATE)) for i in range(n)))


def level(pcm: bytes) -> float:
    n = len(pcm) // 2
    if not n:
        return 0.0
    vals = struct.unpack(f"<{n}h", pcm[: n * 2])
    return sum(abs(v) for v in vals) / n


class EnergyVad:
    def __init__(self) -> None:
        self.speaking = False
        self.silence_ms = 0.0
        self.pos_ms = 0.0
        self.start_ms = 0.0

    def push(self, pcm: bytes) -> str | None:
        ms = len(pcm) / 2 / RATE * 1000
        loud = level(pcm) > ENERGY
        self.pos_ms += ms
        if loud:
            self.silence_ms = 0
            if not self.speaking:
                self.speaking, self.start_ms = True, self.pos_ms - ms
                return "started"
        elif self.speaking:
            self.silence_ms += ms
            if self.silence_ms >= SILENCE_MS:
                self.speaking = False
                return "stopped"
        return None


@dataclass
class OpenAIState:
    received: list[dict] = field(default_factory=list)
    connections: int = 0
    open_connections: int = 0
    word_delay: float = 0.06       # pausa entre palabras de la respuesta simulada
    word_ms: int = 240             # audio por palabra
    drop_after_session: bool = False


class FakeOpenAI:
    def __init__(self, state: OpenAIState | None = None) -> None:
        self.state = state or OpenAIState()
        self._live: set[ServerConnection] = set()

    async def drop_all(self) -> None:
        for ws in list(self._live):
            await ws.close()

    async def handler(self, ws: ServerConnection) -> None:
        st = self.state
        st.connections += 1
        st.open_connections += 1
        self._live.add(ws)
        vad = EnergyVad()
        n = {"resp": 0, "item": 0, "call": 0}
        session: dict[str, Any] = {}
        pending_output: list[dict] = []
        question = {"text": USER_QUESTION}
        current: dict[str, Any] = {"task": None}

        async def send(ev: dict) -> None:
            await ws.send(json.dumps(ev, ensure_ascii=False))

        async def respond(kind: str, text: str = "") -> None:
            n["resp"] += 1
            rid = f"resp_{n['resp']}"
            await send({"type": "response.created", "response": {"id": rid, "status": "in_progress"}})
            try:
                if kind == "call":
                    await asyncio.sleep(0.05)
                    n["call"] += 1
                    m = re.search(r"en ([A-ZÁÉÍÓÚ][\wáéíóúñ ]+?)\?", question["text"])
                    args = {"departamento": m.group(1)} if m else {}
                    fc = {"type": "function_call", "name": "count_ips", "call_id": f"call_{n['call']}",
                          "arguments": json.dumps(args, ensure_ascii=False)}
                    await send({"type": "response.done", "response": {"id": rid, "status": "completed",
                                                                       "output": [fc]}})
                    return
                n["item"] += 1
                item_id = f"item_{n['item']}"
                audio = "audio" in session.get("output_modalities", ["audio"])
                said = ""
                for w in text.split():
                    await asyncio.sleep(st.word_delay)
                    said = f"{said} {w}".strip()
                    delta = (" " if said != w else "") + w
                    if audio:
                        await send({"type": "response.output_audio.delta", "response_id": rid, "item_id": item_id,
                                    "delta": base64.b64encode(tone(st.word_ms)).decode()})
                        await send({"type": "response.output_audio_transcript.delta", "response_id": rid,
                                    "item_id": item_id, "delta": delta})
                    else:
                        await send({"type": "response.output_text.delta", "response_id": rid, "item_id": item_id,
                                    "delta": delta})
                done = "response.output_audio_transcript.done" if audio else "response.output_text.done"
                await send({"type": done, "response_id": rid, "item_id": item_id,
                            ("transcript" if audio else "text"): said})
                await send({"type": "response.done", "response": {"id": rid, "status": "completed", "output": [
                    {"type": "message", "id": item_id, "role": "assistant"}]}})
            except asyncio.CancelledError:
                await send({"type": "response.done", "response": {"id": rid, "status": "cancelled", "output": []}})
                raise

        def start_response(kind: str, text: str = "") -> None:
            task = current["task"]
            if task is not None and not task.done():
                task.cancel()
            current["task"] = asyncio.create_task(respond(kind, text))

        try:
            await send({"type": "session.created", "session": {"id": "sess_fake"}})
            async for raw in ws:
                ev = json.loads(raw)
                et = ev.get("type")
                if et != "input_audio_buffer.append":
                    st.received.append(ev)
                if et == "session.update":
                    session = ev.get("session", {})
                    await send({"type": "session.updated", "session": session})
                    if st.drop_after_session:
                        await asyncio.sleep(0.2)
                        await ws.close()
                        return
                elif et == "input_audio_buffer.append":
                    edge = vad.push(base64.b64decode(ev.get("audio", "")))
                    if edge == "started":
                        await send({"type": "input_audio_buffer.speech_started",
                                    "audio_start_ms": round(vad.start_ms)})
                        task = current["task"]
                        td = (session.get("audio") or {}).get("input", {}).get("turn_detection") or {}
                        if td.get("interrupt_response", True) and task is not None and not task.done():
                            task.cancel()
                    elif edge == "stopped":
                        await send({"type": "input_audio_buffer.speech_stopped", "audio_end_ms": round(vad.pos_ms)})
                        await send({"type": "input_audio_buffer.committed", "item_id": "item_user"})
                        question["text"] = USER_QUESTION
                        start_response("call")
                        await asyncio.sleep(0.03)
                        await send({"type": "conversation.item.input_audio_transcription.completed",
                                    "item_id": "item_user", "content_index": 0, "transcript": USER_QUESTION})
                elif et == "conversation.item.create":
                    item = ev.get("item", {})
                    if item.get("type") == "function_call_output":
                        pending_output.append(json.loads(item.get("output") or "{}"))
                    elif item.get("type") == "message":
                        question["text"] = item["content"][0].get("text", "")
                elif et == "response.create":
                    instr = (ev.get("response") or {}).get("instructions")
                    if instr:
                        start_response("say", instr.split("nada: ", 1)[-1])
                    elif pending_output:
                        out = pending_output.pop()
                        pending_output.clear()
                        valor = out.get("valor")
                        start_response("say", f"En total hay {valor} IPS con esos criterios.")
                    else:
                        start_response("call")
                elif et == "response.cancel":
                    task = current["task"]
                    if task is not None and not task.done():
                        task.cancel()
                    else:
                        await send({"type": "error", "error": {"type": "invalid_request_error",
                                                               "code": "response_cancel_not_active"}})
                elif et == "conversation.item.truncate":
                    await send({"type": "conversation.item.truncated", "item_id": ev.get("item_id"),
                                "audio_end_ms": ev.get("audio_end_ms")})
        finally:
            task = current["task"]
            if task is not None:
                task.cancel()
            self._live.discard(ws)
            st.open_connections -= 1


@dataclass
class DeepgramState:
    connections: int = 0
    open_connections: int = 0
    paths: list[str] = field(default_factory=list)
    auth: list[str] = field(default_factory=list)
    frames: int = 0
    fail: bool = False


class FakeDeepgram:
    WORDS = ["cuántas", "IPS", "hay", "en", "total"]

    def __init__(self, state: DeepgramState | None = None) -> None:
        self.state = state or DeepgramState()

    async def handler(self, ws: ServerConnection) -> None:
        st = self.state
        if st.fail:
            await ws.close(code=1011)
            return
        st.connections += 1
        st.open_connections += 1
        st.paths.append(ws.request.path)
        st.auth.append(ws.request.headers.get("Authorization", ""))
        vad = EnergyVad()
        bursts = 0
        try:
            async for raw in ws:
                if isinstance(raw, str):
                    continue                          # KeepAlive / CloseStream
                st.frames += 1
                edge = vad.push(raw)
                if edge == "started":
                    await ws.send(json.dumps(self._result(vad.start_ms / 1000, vad.pos_ms / 1000, bursts, False)))
                elif edge == "stopped":
                    end = (vad.pos_ms - vad.silence_ms) / 1000
                    await ws.send(json.dumps(self._result(vad.start_ms / 1000, end, bursts, True)))
                    bursts += 1
        finally:
            st.open_connections -= 1

    def _result(self, start: float, end: float, burst: int, final: bool) -> dict:
        words = self.WORDS if final else self.WORDS[:2]
        step = max(0.05, (end - start) / len(words))
        ws = [{"word": w.lower(), "punctuated_word": (w.capitalize() if i == 0 else w) + ("?" if final and i == len(words) - 1 else ""),
               "start": round(start + i * step, 3), "end": round(start + (i + 1) * step, 3), "confidence": 0.95,
               "speaker": burst % 2} for i, w in enumerate(words)]
        text = " ".join(w["punctuated_word"] for w in ws)
        return {"type": "Results", "is_final": final, "speech_final": final, "start": start, "duration": end - start,
                "channel": {"alternatives": [{"transcript": text, "confidence": 0.95, "words": ws}]}}


@dataclass
class HttpState:
    """Groq (chat con tools) y Deepgram TTS simulados."""
    chats: list[dict] = field(default_factory=list)
    speak_texts: list[str] = field(default_factory=list)
    speak_params: list[dict] = field(default_factory=list)
    ms_per_char: int = 60           # duración del audio sintetizado por carácter
    chunk_delay: float = 0.0        # pausa entre trozos de audio
    llm_delay: float = 0.02         # pausa entre trozos de texto
    groq_status: int = 200          # p. ej. 401 para simular una clave inválida
    chat_failures: list = field(default_factory=list)   # [(status, retry_after | None, solo_modelo | None)]
    fail_after_tool: int = 0        # status con que fallan TODAS las rondas que ya traen el resultado de una tool
    empty_after_tool: bool = False  # el modelo responde vacío tras recibir el resultado de una tool
    sentiment_calls: list = field(default_factory=list)
    sentiment_delay: float = 0.0    # para simular un modelo de sentimiento lento
    sentiment_reply: str | None = None   # contenido fijo (p. ej. JSON inválido) en lugar del clasificador


def make_http_app(state: HttpState):
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse, StreamingResponse
    from starlette.routing import Route

    def sse(obj) -> str:
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    async def models(request: Request):
        if state.groq_status != 200 or not request.headers.get("authorization", "").startswith("Bearer "):
            return JSONResponse({"error": {"message": "Invalid API Key"}}, status_code=state.groq_status or 401)
        return JSONResponse({"data": [{"id": "openai/gpt-oss-120b"}]})

    async def chat(request: Request):
        if state.groq_status != 200:
            return JSONResponse({"error": {"message": "fallo simulado"}}, status_code=state.groq_status)
        body = await request.json()
        if not body.get("stream"):                      # clasificación de sentimiento (JSON, sin streaming)
            state.sentiment_calls.append(body)
            if state.sentiment_delay:
                await asyncio.sleep(state.sentiment_delay)
            text = body["messages"][-1]["content"].split("ENUNCIADO a clasificar:")[-1].lower()
            if state.sentiment_reply is not None:
                content = state.sentiment_reply
            elif any(w in text for w in ("gracias", "genial", "excelente", "perfecto")):
                content = json.dumps({"sentiment": "positivo", "emotion": "alegría", "score": 0.7})
            elif any(w in text for w in ("no entiendo", "no sirve", "otra vez", "mal")):
                content = json.dumps({"sentiment": "negativo", "emotion": "frustración", "score": -0.6})
            else:
                content = json.dumps({"sentiment": "neutral", "emotion": "curiosity", "score": 0.1})
            return JSONResponse({"choices": [{"message": {"role": "assistant", "content": content}}]})
        state.chats.append(body)
        for i, (status, retry, only_model) in enumerate(state.chat_failures):
            if only_model is None or only_model == body["model"]:
                state.chat_failures.pop(i)
                headers = {"retry-after": str(retry)} if retry is not None else {}
                return JSONResponse({"error": {"message": f"fallo simulado {status}",
                                               "code": "rate_limit_exceeded" if status == 429 else "tool_use_failed"}},
                                    status_code=status, headers=headers)
        msgs = body["messages"]
        last = msgs[-1]
        if last["role"] == "tool" and state.fail_after_tool:
            return JSONResponse({"error": {"message": "fallo simulado tras la tool"}}, status_code=state.fail_after_tool)

        async def gen():
            if last["role"] == "tool" and state.empty_after_tool:
                pass
            elif last["role"] == "tool":
                valor = json.loads(last["content"]).get("valor")
                text = f"En total hay {valor} IPS. ¿Quieres saber algo más?"
                for w in text.split(" "):
                    await asyncio.sleep(state.llm_delay)
                    yield sse({"choices": [{"index": 0, "delta": {"content": w + " "}}]})
            else:
                m = re.search(r"en ([A-ZÁÉÍÓÚ][\wáéíóúñ ]+?)\?", last.get("content") or "")
                args = json.dumps({"departamento": m.group(1)} if m else {}, ensure_ascii=False)
                n = sum(1 for x in msgs if x["role"] == "tool") + 1
                yield sse({"choices": [{"index": 0, "delta": {"tool_calls": [
                    {"index": 0, "id": f"call_{n}", "type": "function",
                     "function": {"name": "count_ips", "arguments": ""}}]}}]})
                for part in (args[: len(args) // 2], args[len(args) // 2:]):
                    yield sse({"choices": [{"index": 0, "delta": {"tool_calls": [
                        {"index": 0, "function": {"arguments": part}}]}}]})
            yield sse({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
            yield "data: [DONE]\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream")

    async def speak(request: Request):
        text = (await request.json())["text"]
        state.speak_texts.append(text)
        state.speak_params.append(dict(request.query_params))
        pcm = tone(max(200, len(text) * state.ms_per_char))

        async def gen():
            for i in range(0, len(pcm), 4800):
                if state.chunk_delay:
                    await asyncio.sleep(state.chunk_delay)
                yield pcm[i:i + 4800]

        return StreamingResponse(gen(), media_type="application/octet-stream")

    return Starlette(routes=[Route("/openai/v1/models", models), Route("/openai/v1/chat/completions", chat,
                                                                          methods=["POST"]),
                             Route("/v1/speak", speak, methods=["POST"])])


async def serve_http(state: HttpState, host: str, port: int):
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(make_http_app(state), host=host, port=port, log_level="warning",
                                           lifespan="off"))
    server.install_signal_handlers = lambda: None   # puede correr fuera del hilo principal
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    return server, task


async def serve_fakes(openai_port: int, deepgram_port: int, host: str = "127.0.0.1",
                      openai: FakeOpenAI | None = None, deepgram: FakeDeepgram | None = None):
    openai = openai or FakeOpenAI()
    deepgram = deepgram or FakeDeepgram()
    s1 = await serve(openai.handler, host, openai_port, max_size=None)
    s2 = await serve(deepgram.handler, host, deepgram_port, max_size=None)
    return s1, s2


async def _main(args) -> None:
    s1, s2 = await serve_fakes(args.openai_port, args.deepgram_port, args.host)
    await serve_http(HttpState(), args.host, args.http_port)
    print(f"OpenAI simulado en ws://{args.host}:{args.openai_port} · Deepgram (STT) simulado en "
          f"ws://{args.host}:{args.deepgram_port} · Groq y Deepgram TTS simulados en "
          f"http://{args.host}:{args.http_port} (GROQ_BASE_URL=.../openai/v1, DEEPGRAM_TTS_URL=.../v1/speak)",
          flush=True)
    async with s1, s2:
        await asyncio.Future()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--openai-port", type=int, default=9101)
    ap.add_argument("--deepgram-port", type=int, default=9102)
    ap.add_argument("--http-port", type=int, default=9103)
    asyncio.run(_main(ap.parse_args()))
