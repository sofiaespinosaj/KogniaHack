"""Spike de modelo para OpenAI Realtime (tareas 0.1 a 0.3 de realtime-voice).

Abre Realtime por WebSocket con las tools de grounded-agent, envía preguntas de oro por TEXTO,
recibe el audio de respuesta y mide `first_audio_ms` (envío de la pregunta -> primer fragmento
de audio). Comprueba también qué modelos de transcripción de entrada y qué VAD acepta la API.

Uso (desde backend/):
    uv run python scripts/spike_realtime.py
    uv run python scripts/spike_realtime.py --models gpt-realtime-mini,gpt-realtime-2.1 --repeats 2

La clave se lee SOLO del entorno o de backend/.env (OPENAI_API_KEY) y nunca se imprime.
Límite conocido: con entrada por texto no interviene el VAD, así que la latencia percibida real
es `vad_silence_ms + first_audio_ms`; aquí se mide la parte del modelo y las tools.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from websockets.asyncio.client import connect  # noqa: E402
from websockets.exceptions import InvalidStatus, WebSocketException  # noqa: E402

from app.agent.gold import GOLD, Gold  # noqa: E402
from app.agent.instructions import INSTRUCTIONS  # noqa: E402
from app.agent.text_agent import check_answer  # noqa: E402
from app.agent.tools import AgentTools, ToolSession  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.datastore.loader import load_snapshot  # noqa: E402
from app.datastore.store import Store  # noqa: E402

URL = "wss://api.openai.com/v1/realtime"
DEFAULT_MODELS = ("gpt-realtime-mini", "gpt-realtime-2.1")
# 3 preguntas con tool (cifras) y 2 fuera de la fuente (sin tool)
QUESTION_IDS = ("4.1", "4.6", "4.7b", "4.9", "4.10")
TRANSCRIPTION_CANDIDATES = ("gpt-live-transcribe", "gpt-4o-mini-transcribe", "gpt-4o-transcribe", "whisper-1")
VAD_CANDIDATES = {"semantic_vad": {"type": "semantic_vad"},
                  "server_vad": {"type": "server_vad", "threshold": 0.5, "prefix_padding_ms": 300,
                                 "silence_duration_ms": 500}}
TIMEOUT_S = 60.0
AUDIO_DELTA_EVENTS = {"response.output_audio.delta", "response.audio.delta"}
TRANSCRIPT_DONE_EVENTS = {"response.output_audio_transcript.done", "response.audio_transcript.done"}


# --------------------------------------------------------------------------- entorno
def load_env_file(path: Path) -> None:
    """Carga KEY=VALUE de un .env sin sobrescribir el entorno y sin imprimir nada."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        v = v.strip().strip("'\"")
        if v:
            os.environ.setdefault(k.strip(), v)


# --------------------------------------------------------------------------- cifras habladas
_UNITS = {"cero": 0, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
          "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "trece": 13, "catorce": 14,
          "quince": 15, "dieciseis": 16, "diecisiete": 17, "dieciocho": 18, "diecinueve": 19, "veinte": 20,
          "veintiun": 21, "veintiuno": 21, "veintiuna": 21, "veintidos": 22, "veintitres": 23,
          "veinticuatro": 24, "veinticinco": 25, "veintiseis": 26, "veintisiete": 27, "veintiocho": 28,
          "veintinueve": 29, "treinta": 30, "cuarenta": 40, "cincuenta": 50, "sesenta": 60, "setenta": 70,
          "ochenta": 80, "noventa": 90, "cien": 100, "ciento": 100, "doscientos": 200, "doscientas": 200,
          "trescientos": 300, "trescientas": 300, "cuatrocientos": 400, "cuatrocientas": 400,
          "quinientos": 500, "quinientas": 500, "seiscientos": 600, "seiscientas": 600, "setecientos": 700,
          "setecientas": 700, "ochocientos": 800, "ochocientas": 800, "novecientos": 900, "novecientas": 900}
_MIL, _MILLON = {"mil"}, {"millon", "millones"}


def _strip_accents(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _format_spoken(value: int) -> str:
    """'45 mil' conserva la precisión con que se dijo; el resto va en dígitos con puntos."""
    if value >= 1_000_000 and value % 1_000_000 == 0:
        return f"{value // 1_000_000} millones"
    if value >= 1000 and value % 1000 == 0:
        return f"{value // 1000} mil"
    return f"{value:,}".replace(",", ".")


def words_to_digits(text: str) -> str:
    """Convierte cifras dichas con palabras ('nueve mil trescientos veinte') a dígitos.

    Solo convierte secuencias de 10 o más, para no tocar 'un departamento' o 'tres niveles'."""
    text = re.sub(r"(\d+)\s+mil\s+(\d{1,3})\b",
                  lambda m: _format_spoken(int(m.group(1)) * 1000 + int(m.group(2))), text)
    tokens = re.findall(r"\w+|\W+", text)
    out, i = [], 0
    while i < len(tokens):
        word = _strip_accents(tokens[i]).lower()
        after_digits = bool(out) and out[-1].strip() == "" and len(out) > 1 and out[-2][-1:].isdigit()
        if (word in _UNITS or word in _MIL or word in _MILLON) and not (word in _MIL | _MILLON and after_digits):
            j, run = i, []
            while j < len(tokens):
                w = _strip_accents(tokens[j]).lower()
                if w in _UNITS or w in _MIL or w in _MILLON:
                    run.append(w)
                    j += 1
                elif w.strip() == "" or (w == "y" and j + 1 < len(tokens)):
                    # espacios y el 'y' de 'treinta y cinco' continúan la secuencia solo si sigue una palabra numérica
                    k = j + 1
                    while k < len(tokens) and (tokens[k].strip() == "" or _strip_accents(tokens[k]).lower() == "y"):
                        k += 1
                    nxt = _strip_accents(tokens[k]).lower() if k < len(tokens) else ""
                    if nxt in _UNITS or nxt in _MIL or nxt in _MILLON:
                        j = k
                    else:
                        break
                else:
                    break
            total = current = 0
            for w in run:
                if w in _UNITS:
                    current += _UNITS[w]
                elif w in _MIL:
                    total += max(current, 1) * 1000
                    current = 0
                else:
                    total += max(current, 1) * 1_000_000
                    current = 0
            value = total + current
            if value >= 10:
                out.append(_format_spoken(value))
                i = j
                continue
        out.append(tokens[i])
        i += 1
    return "".join(out)


# --------------------------------------------------------------------------- sesión Realtime
def session_config(tools: list[dict], *, voice: str = "marin", vad: dict | None = None,
                   transcription: str | None = None) -> dict:
    inp: dict[str, Any] = {"format": {"type": "audio/pcm", "rate": 24000}}
    if vad is not None:
        inp["turn_detection"] = vad
    if transcription:
        inp["transcription"] = {"model": transcription}
    return {"type": "session.update", "session": {
        "type": "realtime", "output_modalities": ["audio"], "instructions": INSTRUCTIONS,
        "audio": {"input": inp, "output": {"format": {"type": "audio/pcm", "rate": 24000}, "voice": voice}},
        "tools": tools, "tool_choice": "auto"}}


async def _recv(ws, timeout: float) -> dict:
    raw = await asyncio.wait_for(ws.recv(), timeout)
    return json.loads(raw)


async def open_session(model: str, api_key: str, config: dict):
    """Abre el WebSocket y aplica la configuración. Devuelve (ws, error|None)."""
    ws = await connect(f"{URL}?model={model}", additional_headers={"Authorization": f"Bearer {api_key}"},
                       max_size=None, open_timeout=20)
    await _recv(ws, 20)  # session.created
    await ws.send(json.dumps(config))
    while True:
        ev = await _recv(ws, 20)
        if ev["type"] == "session.updated":
            return ws, None
        if ev["type"] == "error":
            return ws, ev.get("error", {})


async def ask(ws, session: ToolSession, question: str) -> dict:
    """Envía una pregunta por texto y mide la respuesta hablada. Ejecuta las tools en el servidor."""
    session.begin_turn()
    await ws.send(json.dumps({"type": "conversation.item.create", "item": {
        "type": "message", "role": "user", "content": [{"type": "input_text", "text": question}]}}))
    t0 = time.perf_counter()
    await ws.send(json.dumps({"type": "response.create"}))
    first_audio_ms = answer_audio_ms = resp_first = None
    audio_bytes, tool_ms, transcript, results, calls = 0, 0.0, "", [], []
    deadline = t0 + TIMEOUT_S
    while True:
        ev = await _recv(ws, max(0.1, deadline - time.perf_counter()))
        et = ev["type"]
        if et in AUDIO_DELTA_EVENTS:
            now_ms = (time.perf_counter() - t0) * 1000
            if first_audio_ms is None:
                first_audio_ms = now_ms
            if resp_first is None:
                resp_first = now_ms
            audio_bytes += len(base64.b64decode(ev.get("delta", "")))
        elif et in TRANSCRIPT_DONE_EVENTS:
            transcript += ev.get("transcript", "")
        elif et == "error":
            return {"error": ev.get("error", {}).get("message", "error")[:200]}
        elif et == "response.done":
            resp = ev.get("response", {})
            if resp.get("status") not in (None, "completed"):
                return {"error": f"respuesta {resp.get('status')}", "detail": str(resp.get("status_details"))[:200]}
            fcalls = [o for o in resp.get("output", []) if o.get("type") == "function_call"]
            if not fcalls:
                answer_audio_ms = resp_first
                break
            resp_first = None   # audio previo a una tool (muletilla): no es la respuesta
            for fc in fcalls:
                t1 = time.perf_counter()
                try:
                    args = json.loads(fc.get("arguments") or "{}")
                except ValueError:
                    args = {}
                out = session.call(fc["name"], args)
                tool_ms += (time.perf_counter() - t1) * 1000
                results.append(out)
                calls.append(fc["name"])
                await ws.send(json.dumps({"type": "conversation.item.create", "item": {
                    "type": "function_call_output", "call_id": fc["call_id"],
                    "output": json.dumps(out, ensure_ascii=False)}}))
            await ws.send(json.dumps({"type": "response.create"}))
    return {"first_audio_ms": first_audio_ms, "answer_audio_ms": answer_audio_ms, "total_ms": (time.perf_counter() - t0) * 1000,
            "tool_ms": tool_ms, "tools": calls, "results": results, "transcript": transcript,
            "audio_s": audio_bytes / 2 / 24000}


def judge(g: Gold, expected: Any, run: dict) -> tuple[bool | None, str]:
    """(correcto, motivo) sobre la transcripción hablada, con las cifras dichas en palabras convertidas."""
    if "error" in run:
        return None, run["error"]
    text = words_to_digits(run["transcript"])
    ok, why = check_answer(g, expected, text, run["results"])
    if g.kind == "honestidad" and not g.calls and run["tools"]:
        return False, "llamó a una tool en una pregunta fuera de la fuente"
    return ok, why


# --------------------------------------------------------------------------- sondeos (0.3)
async def probe(model: str, api_key: str, tools: list[dict]) -> dict:
    """Qué modelos de transcripción y qué VAD acepta la API para este modelo."""
    res: dict[str, dict] = {"vad": {}, "transcription": {}}
    for name, vad in VAD_CANDIDATES.items():
        ws, err = await open_session(model, api_key, session_config(tools, vad=vad))
        res["vad"][name] = "ok" if err is None else (err.get("message") or "error")[:120]
        await ws.close()
    for tm in TRANSCRIPTION_CANDIDATES:
        ws, err = await open_session(model, api_key, session_config(tools, transcription=tm))
        res["transcription"][tm] = "ok" if err is None else (err.get("message") or "error")[:120]
        await ws.close()
    return res


# --------------------------------------------------------------------------- informe
def redact(text: str) -> str:
    """Oculta cualquier fragmento con forma de clave antes de imprimir o guardar."""
    return re.sub(r"sk-[A-Za-z0-9_*.-]+", "sk-***", text)


def format_report(report: dict) -> str:
    lines = []
    for model, data in report["models"].items():
        lines.append(f"\n== {model} ==")
        if "connect_error" in data:
            lines.append(f"  no se pudo usar el modelo: {data['connect_error']}")
            continue
        lines.append(f"  {'id':<6}{'tools':<22}{'first_audio_ms':>15}{'answer_ms':>10}{'tool_ms':>9}{'total_ms':>10}  {'cifras/honestidad':<20}")
        for r in data["runs"]:
            fa = f"{r['first_audio_ms']:.0f}" if r.get("first_audio_ms") is not None else "-"
            am = f"{r['answer_audio_ms']:.0f}" if r.get("answer_audio_ms") is not None else "-"
            verdict = {True: "SI", False: "NO", None: "ERROR"}[r["correct"]]
            lines.append(f"  {r['id']:<6}{','.join(r['tools']) or '(sin tool)':<22}{fa:>15}{am:>10}"
                         f"{r.get('tool_ms', 0):>9.0f}{r.get('total_ms', 0):>10.0f}  {verdict} {r['why'][:40]}")
        s = data["summary"]
        lines.append(f"  mediana first_audio_ms = {s['median_first_audio_ms']}  (sin tool: {s['median_no_tool']}; "
                     f"con tool: {s['median_with_tool']})  máx = {s['max_first_audio_ms']}")
        lines.append(f"  mediana answer_ms = {s['median_answer_ms']}  (sin tool: {s['median_answer_no_tool']}; "
                     f"con tool: {s['median_answer_with_tool']})  máx = {s['max_answer_ms']}")
        lines.append(f"  correctas = {s['correct']}/{s['total']}")
        for kind in ("vad", "transcription"):
            lines.append(f"  {kind}: " + "; ".join(f"{k}={v}" for k, v in data["probe"][kind].items()))
    return "\n".join(lines)


def _median(xs: list[float]) -> int | None:
    return round(statistics.median(xs)) if xs else None


async def run_model(model: str, api_key: str, store: Store, repeats: int) -> dict:
    tools = AgentTools(store)
    specs = tools.schemas()
    questions = [g for g in GOLD if g.id in QUESTION_IDS]
    cur = store.cursor()
    try:
        probe_res = await probe(model, api_key, specs)
        ws, err = await open_session(model, api_key, session_config(specs, vad=VAD_CANDIDATES["server_vad"]))
    except (InvalidStatus, WebSocketException, OSError, asyncio.TimeoutError) as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        return {"connect_error": f"{type(e).__name__}" + (f" HTTP {status}" if status else "")}
    if err:
        await ws.close()
        return {"connect_error": (err.get("message") or "error")[:150]}
    await ws.close()
    runs = []
    cfg = session_config(specs, vad=VAD_CANDIDATES["server_vad"])
    for _ in range(repeats):
        for g in questions:
            # sesión nueva por pregunta: sin contexto previo el modelo no puede responder de memoria
            ws, err = await open_session(model, api_key, cfg)
            if err:
                runs.append({"id": g.id, "question": g.question, "correct": None, "why": (err.get("message") or "error")[:80],
                             "tools": []})
                await ws.close()
                continue
            try:
                run = await ask(ws, ToolSession(tools), g.question)
            finally:
                await ws.close()
            correct, why = judge(g, g.expected(cur), run)
            runs.append({"id": g.id, "question": g.question, "correct": correct, "why": why,
                         **{k: v for k, v in run.items() if k != "results"},
                         "answer_digits": words_to_digits(run.get("transcript", ""))[:300]})
    fa = [r["first_audio_ms"] for r in runs if r.get("first_audio_ms") is not None]
    summary = {
        "median_first_audio_ms": _median(fa),
        "median_no_tool": _median([r["first_audio_ms"] for r in runs if not r.get("tools") and r.get("first_audio_ms")]),
        "median_with_tool": _median([r["first_audio_ms"] for r in runs if r.get("tools") and r.get("first_audio_ms")]),
        "max_first_audio_ms": round(max(fa)) if fa else None,
        "median_answer_ms": _median([r["answer_audio_ms"] for r in runs if r.get("answer_audio_ms")]),
        "median_answer_no_tool": _median([r["answer_audio_ms"] for r in runs if not r.get("tools") and r.get("answer_audio_ms")]),
        "median_answer_with_tool": _median([r["answer_audio_ms"] for r in runs if r.get("tools") and r.get("answer_audio_ms")]),
        "max_answer_ms": round(max(r["answer_audio_ms"] for r in runs if r.get("answer_audio_ms"))) if any(r.get("answer_audio_ms") for r in runs) else None,
        "correct": sum(1 for r in runs if r["correct"]), "total": len(runs)}
    return {"runs": runs, "summary": summary, "probe": probe_res}


async def main_async(args: argparse.Namespace) -> int:
    load_env_file(Path(__file__).resolve().parents[1] / ".env")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        print("Falta la variable de entorno OPENAI_API_KEY (entorno o backend/.env)", file=sys.stderr)
        return 2
    store = Store()
    if not load_snapshot(store, load_settings({"DATA_PATH": args.data})):
        print("No se pudo cargar el snapshot", file=sys.stderr)
        return 2
    report: dict[str, Any] = {"measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "repeats": args.repeats,
                              "note": "entrada por texto: first_audio_ms no incluye el silencio del VAD", "models": {}}
    for model in args.models.split(","):
        report["models"][model] = await run_model(model.strip(), api_key, store, args.repeats)
    print(redact(format_report(report)))
    Path(args.out).write_text(redact(json.dumps(report, ensure_ascii=False, indent=2)), encoding="utf-8")
    print(f"\nResultados guardados en {args.out}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    ap.add_argument("--repeats", type=int, default=1)
    ap.add_argument("--data", default=str(Path(__file__).resolve().parents[2] / "data"))
    ap.add_argument("--out", default=str(Path(__file__).with_name("spike_realtime_results.json")))
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
