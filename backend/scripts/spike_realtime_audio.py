"""Spike ampliado de OpenAI Realtime con AUDIO real (grupo 0 de realtime-voice).

Pasos:
  1. `--synth`: sintetiza las 15 preguntas de oro a WAV (TTS de OpenAI) en tests/audio/gold/.
  2. `--run`: envía cada WAV a una sesión Realtime nueva como PCM16 24 kHz en frames de 40 ms a
     velocidad de tiempo real, con semantic_vad y server_vad (0,5 / 300 ms / 500 ms), para cada
     modelo candidato, N repeticiones. Guarda cada corrida en spike_audio_runs.jsonl (reanudable).
  3. `--report`: resume por (modelo, VAD), aplica la regla de decisión y guarda spike_audio_results.json.

Uso (desde backend/):
    uv run python scripts/spike_realtime_audio.py --synth
    uv run python scripts/spike_realtime_audio.py --run --repeats 5
    uv run python scripts/spike_realtime_audio.py --report

Latencias (todas medidas en el cliente):
    vad_silence_ms  = fin del audio de la pregunta -> evento speech_stopped del servidor
    first_audio_ms  = speech_stopped -> primer frame de audio de respuesta (cualquiera)
    perceived_ms    = vad_silence_ms + first_audio_ms (fin de la pregunta -> primer audio)
    answer_ms       = como perceived_ms pero hasta el primer audio de la respuesta FINAL
                      (descuenta una muletilla dicha antes de llamar a una tool)

La clave se lee del entorno o de backend/.env y nunca se imprime.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import statistics
import sys
import time
import wave
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from spike_realtime import (VAD_CANDIDATES, judge, load_env_file, open_session, redact,  # noqa: E402
                            session_config, words_to_digits)

from app.agent.gold import GOLD, Gold  # noqa: E402
from app.agent.tools import AgentTools, ToolSession  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.datastore.loader import load_snapshot  # noqa: E402
from app.datastore.store import Store  # noqa: E402

BACKEND = Path(__file__).resolve().parents[1]
AUDIO_DIR = BACKEND / "tests" / "audio" / "gold"
RUNS_FILE = Path(__file__).with_name("spike_audio_runs.jsonl")
RESULTS_FILE = Path(__file__).with_name("spike_audio_results.json")

CANDIDATES = ("gpt-realtime-mini", "gpt-realtime-2.1-mini", "gpt-realtime-2.1")
TTS_MODEL, TTS_VOICE = "gpt-4o-mini-tts", "alloy"
TTS_INSTRUCTIONS = "Habla en español neutro, con ritmo natural y claro, como alguien que hace una pregunta."
TRANSCRIPTION_MODEL = "gpt-live-transcribe"
RATE, FRAME_MS = 24000, 40
FRAME_BYTES = RATE * FRAME_MS // 1000 * 2          # 1.920 bytes
LEAD_SILENCE_MS, MAX_TRAIL_MS, RUN_TIMEOUT_S = 300, 4000, 45.0
FILTER_KEYS = ("departamento", "municipio", "naturaleza", "nivel_atencion")

# Regla de decisión (a)-(d)
MIN_CORRECT_PCT, MAX_P95_MS, TIE_MS = 98.0, 2500.0, 150.0


# --------------------------------------------------------------------------- síntesis
def trim_silence(pcm: bytes, *, threshold: int = 300, keep_ms: int = 60) -> bytes:
    """Recorta el silencio inicial y final del PCM16 para que el 'fin del audio' sea el fin de la voz."""
    import array
    samples = array.array("h")
    samples.frombytes(pcm[: len(pcm) // 2 * 2])
    idx = [i for i, s in enumerate(samples) if abs(s) > threshold]
    if not idx:
        return b""
    keep = RATE * keep_ms // 1000
    a, b = max(0, idx[0] - keep), min(len(samples), idx[-1] + keep)
    return samples[a:b].tobytes()


def write_wav(path: Path, pcm: bytes) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm)


def read_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, RATE), "WAV debe ser PCM16 mono 24 kHz"
        return w.readframes(w.getnframes())


def frames_of(pcm: bytes) -> list[bytes]:
    out = [pcm[i:i + FRAME_BYTES] for i in range(0, len(pcm), FRAME_BYTES)]
    if out and len(out[-1]) < FRAME_BYTES:
        out[-1] = out[-1] + b"\0" * (FRAME_BYTES - len(out[-1]))
    return out


def synthesize(api_key: str, force: bool = False) -> None:
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    manifest = []
    with httpx.Client(timeout=60, headers={"Authorization": f"Bearer {api_key}"}) as http:
        for g in GOLD:
            path = AUDIO_DIR / f"{g.id}.wav"
            if force or not path.exists():
                r = http.post("https://api.openai.com/v1/audio/speech", json={
                    "model": TTS_MODEL, "voice": TTS_VOICE, "input": g.question, "response_format": "pcm",
                    "instructions": TTS_INSTRUCTIONS})
                if r.status_code != 200:
                    raise SystemExit(f"TTS falló para {g.id}: HTTP {r.status_code}")
                write_wav(path, trim_silence(r.content))
            pcm = read_wav(path)
            manifest.append({"id": g.id, "question": g.question, "file": path.name,
                             "duration_ms": len(pcm) // 2 * 1000 // RATE, "tts_model": TTS_MODEL, "voice": TTS_VOICE})
    (AUDIO_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(manifest)} WAV en {AUDIO_DIR}")


# --------------------------------------------------------------------------- corrida
def call_filters(args: dict) -> dict:
    return {k: args[k] for k in FILTER_KEYS if k in args}


def expected_filters(g: Gold) -> dict[str, set]:
    """Filtros que la pregunta de oro justifica (de sus llamadas de referencia)."""
    out: dict[str, set] = {k: set() for k in FILTER_KEYS}
    for _name, args in g.calls:
        for k, v in call_filters(args).items():
            out[k].add(_norm_value(k, v))
    return out


def _norm_value(key: str, value: Any) -> Any:
    from app.agent.tools import norm
    return norm(value) if isinstance(value, str) else value


def classify_calls(g: Gold, calls: list[dict]) -> dict:
    """Filtros inventados, argumentos erróneos y llamadas innecesarias de una corrida."""
    exp = expected_filters(g)
    invented, wrong = [], []
    for c in calls:
        for k, v in call_filters(c["args"]).items():
            if not exp[k]:
                invented.append(f"{k}={v}")
            elif _norm_value(k, v) not in exp[k]:
                wrong.append(f"{k}={v}")
        if c.get("estado") == "error_validacion":
            wrong.append(f"{c['name']}:error_validacion")
    return {"invented_filters": invented, "wrong_args": wrong,
            "unneeded_call": bool(calls) and not g.calls}


async def run_one(model: str, vad: str, g: Gold, rep: int, pcm: bytes, api_key: str, tools: AgentTools,
                  cur) -> dict:
    base = {"model": model, "vad": vad, "id": g.id, "rep": rep, "kind": g.kind}
    cfg = session_config(tools.schemas(), vad=VAD_CANDIDATES[vad], transcription=TRANSCRIPTION_MODEL)
    try:
        ws, err = await open_session(model, api_key, cfg)
    except Exception as e:  # noqa: BLE001
        return {**base, "error": f"conexión: {type(e).__name__}"}
    if err:
        await ws.close()
        return {**base, "error": f"sesión: {(err.get('message') or 'error')[:100]}"}

    session = ToolSession(tools)
    session.begin_turn()
    clock = time.perf_counter
    t_start = clock()
    st: dict[str, Any] = {"t_end_audio": None, "t_stopped": None, "first_audio": None, "resp_first": None,
                          "answer_first": None, "filler": False, "calls": [], "transcript": "", "heard": "",
                          "audio_bytes": 0, "tool_ms": 0.0}
    stop = asyncio.Event()

    async def sender() -> None:
        lead = [b"\0" * FRAME_BYTES] * (LEAD_SILENCE_MS // FRAME_MS)
        speech = frames_of(pcm)
        trail = [b"\0" * FRAME_BYTES] * (MAX_TRAIL_MS // FRAME_MS)
        for i, fr in enumerate([*lead, *speech, *trail]):
            if stop.is_set():
                return
            delay = t_start + i * FRAME_MS / 1000 - clock()
            if delay > 0:
                await asyncio.sleep(delay)
            await ws.send(json.dumps({"type": "input_audio_buffer.append", "audio": base64.b64encode(fr).decode()}))
            if i == len(lead) + len(speech) - 1:
                st["t_end_audio"] = clock()

    send_task = asyncio.create_task(sender())
    try:
        deadline = t_start + RUN_TIMEOUT_S
        while True:
            raw = await asyncio.wait_for(ws.recv(), max(0.1, deadline - clock()))
            ev = json.loads(raw)
            et, now = ev["type"], clock()
            if et == "input_audio_buffer.speech_stopped" and st["t_stopped"] is None:
                st["t_stopped"] = now
            elif et in ("response.output_audio.delta", "response.audio.delta"):
                if st["first_audio"] is None:
                    st["first_audio"] = now
                if st["resp_first"] is None:
                    st["resp_first"] = now
                st["audio_bytes"] += len(ev.get("delta", "")) * 3 // 4
            elif et in ("response.output_audio_transcript.done", "response.audio_transcript.done"):
                st["transcript"] += ev.get("transcript", "")
            elif et == "conversation.item.input_audio_transcription.completed":
                st["heard"] += ev.get("transcript", "")
            elif et == "error":
                return {**base, "error": (ev.get("error", {}).get("message") or "error")[:120]}
            elif et == "response.done":
                resp = ev.get("response", {})
                if resp.get("status") not in (None, "completed", "cancelled"):
                    return {**base, "error": f"respuesta {resp.get('status')}"}
                fcalls = [o for o in resp.get("output", []) if o.get("type") == "function_call"]
                if not fcalls:
                    if resp.get("status") == "cancelled" and not st["transcript"]:
                        continue
                    st["answer_first"] = st["resp_first"]
                    break
                if st["resp_first"] is not None:
                    st["filler"] = True          # habló antes de llamar a la tool
                st["resp_first"] = None
                for fc in fcalls:
                    t1 = clock()
                    try:
                        args = json.loads(fc.get("arguments") or "{}")
                    except ValueError:
                        args = {}
                    out = session.call(fc["name"], args)
                    st["tool_ms"] += (clock() - t1) * 1000
                    st["calls"].append({"name": fc["name"], "args": args, "estado": out.get("estado"), "result": out})
                    await ws.send(json.dumps({"type": "conversation.item.create", "item": {
                        "type": "function_call_output", "call_id": fc["call_id"],
                        "output": json.dumps(out, ensure_ascii=False)}}))
                await ws.send(json.dumps({"type": "response.create"}))
    except asyncio.TimeoutError:
        return {**base, "error": "timeout", "no_turn_end": st["t_stopped"] is None}
    except Exception as e:  # noqa: BLE001
        return {**base, "error": f"{type(e).__name__}"}
    finally:
        stop.set()
        send_task.cancel()
        await asyncio.gather(send_task, return_exceptions=True)
        await ws.close()

    if st["t_stopped"] is None or st["t_end_audio"] is None or st["first_audio"] is None:
        return {**base, "error": "sin fin de turno o sin audio", "heard": st["heard"]}
    ms = lambda a, b: round((a - b) * 1000)  # noqa: E731
    run_like = {"transcript": st["transcript"], "results": [c["result"] for c in st["calls"]],
                "tools": [c["name"] for c in st["calls"]]}
    correct, why = judge(g, g.expected(cur), run_like)
    return {**base,
            "vad_silence_ms": ms(st["t_stopped"], st["t_end_audio"]),
            "first_audio_ms": ms(st["first_audio"], st["t_stopped"]),
            "perceived_ms": ms(st["first_audio"], st["t_end_audio"]),
            "answer_ms": ms(st["answer_first"], st["t_end_audio"]) if st["answer_first"] else None,
            "tool_ms": round(st["tool_ms"]), "filler": st["filler"],
            "tools": [c["name"] for c in st["calls"]],
            "calls": [{"name": c["name"], "args": c["args"], "estado": c["estado"]} for c in st["calls"]],
            **classify_calls(g, [{"name": c["name"], "args": c["args"], "estado": c["estado"]} for c in st["calls"]]),
            "correct": correct, "why": why, "heard": st["heard"],
            "answer": words_to_digits(st["transcript"])[:300], "audio_s": round(st["audio_bytes"] / 2 / RATE, 1)}


def load_done() -> set[tuple]:
    if not RUNS_FILE.exists():
        return set()
    done = set()
    for line in RUNS_FILE.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if "error" not in r:
            done.add((r["model"], r["vad"], r["id"], r["rep"]))
    return done


async def run_all(models: list[str], vads: list[str], repeats: int, concurrency: int, api_key: str, store: Store) -> None:
    tools = AgentTools(store)
    cur = store.cursor()
    done = load_done()
    pcms = {g.id: read_wav(AUDIO_DIR / f"{g.id}.wav") for g in GOLD}
    sem = asyncio.Semaphore(concurrency)
    lock = asyncio.Lock()
    todo = [(m, v, g, r) for m in models for v in vads for r in range(repeats) for g in GOLD
            if (m, v, g.id, r) not in done]
    print(f"{len(todo)} corridas pendientes ({len(done)} ya hechas)", flush=True)
    finished = 0

    async def job(m: str, v: str, g: Gold, r: int) -> None:
        nonlocal finished
        async with sem:
            res = await run_one(m, v, g, r, pcms[g.id], api_key, tools, cur)
        async with lock:
            with RUNS_FILE.open("a", encoding="utf-8") as f:
                f.write(redact(json.dumps(res, ensure_ascii=False)) + "\n")
            finished += 1
            if finished % 20 == 0 or finished == len(todo):
                print(f"  {finished}/{len(todo)}", flush=True)

    await asyncio.gather(*(job(*t) for t in todo))


# --------------------------------------------------------------------------- resumen y decisión
def pct(xs: list[float], q: float) -> int | None:
    if not xs:
        return None
    s = sorted(xs)
    k = (len(s) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return round(s[lo] + (s[hi] - s[lo]) * (k - lo))


def summarize(runs: list[dict]) -> dict[tuple, dict]:
    """Resumen por (modelo, vad)."""
    groups: dict[tuple, list[dict]] = {}
    for r in runs:
        groups.setdefault((r["model"], r["vad"]), []).append(r)
    out = {}
    for key, rs in groups.items():
        ok = [r for r in rs if "error" not in r]
        errors = [r for r in rs if "error" in r]
        perceived = [r["perceived_ms"] for r in ok]
        cifras = [r for r in ok if r["kind"] == "cifra"]
        honest = [r for r in ok if r["kind"] == "honestidad"]
        out[key] = {
            "runs": len(rs), "errors": len(errors),
            "error_kinds": sorted({e["error"] for e in errors})[:3],
            "perceived_median": pct(perceived, .5), "perceived_p95": pct(perceived, .95),
            "perceived_max": max(perceived) if perceived else None,
            "vad_silence_median": pct([r["vad_silence_ms"] for r in ok], .5),
            "first_audio_median": pct([r["first_audio_ms"] for r in ok], .5),
            "answer_median": pct([r["answer_ms"] for r in ok if r.get("answer_ms")], .5),
            "answer_p95": pct([r["answer_ms"] for r in ok if r.get("answer_ms")], .95),
            "cifras_correct_pct": round(100 * sum(1 for r in cifras if r["correct"]) / len(cifras), 1) if cifras else None,
            "honesty_correct_pct": round(100 * sum(1 for r in honest if r["correct"]) / len(honest), 1) if honest else None,
            "invented_filters": sum(len(r["invented_filters"]) for r in ok),
            "invented_runs": sum(1 for r in ok if r["invented_filters"]),
            "wrong_args": sum(len(r["wrong_args"]) for r in ok),
            "unneeded_calls": sum(1 for r in ok if r["unneeded_call"]),
            "filler_pct": round(100 * sum(1 for r in ok if r["filler"]) / len(ok), 1) if ok else None,
            "filler_runs": sum(1 for r in ok if r["filler"]),
        }
    return out


def passes_a(s: dict) -> bool:
    return (s["cifras_correct_pct"] or 0) >= MIN_CORRECT_PCT and s["invented_filters"] == 0


def decide(summary: dict[tuple, dict]) -> dict:
    """Regla: (a) descartar <98 % o con filtros inventados; (b) menor latencia percibida mediana con
    p95 <= 2.500 ms; (c) empate a menos de 150 ms -> el más preciso; (d) si ninguno pasa (a) -> el más
    preciso y guardián de filtros."""
    def precision(item):  # más cifras correctas, menos filtros inventados, menos argumentos erróneos
        k, s = item
        return (-(s["cifras_correct_pct"] or 0), s["invented_filters"], s["wrong_args"], s["perceived_median"] or 1e9)

    items = list(summary.items())
    passing = [(k, s) for k, s in items if passes_a(s)]
    if not passing:
        k, s = min(items, key=precision)
        return {"rule": "d", "model": k[0], "vad": k[1], "needs_filter_guard": True,
                "reason": "ningún candidato pasa (a): se elige el más preciso e implementa el guardián de filtros"}
    eligible = [(k, s) for k, s in passing if (s["perceived_p95"] or 1e9) <= MAX_P95_MS]
    if not eligible:
        k, s = min(passing, key=precision)
        return {"rule": "b-fallback", "model": k[0], "vad": k[1], "needs_filter_guard": False,
                "reason": "pasan (a) pero ninguno cumple p95 <= 2.500 ms: se elige el más preciso"}
    eligible.sort(key=lambda it: it[1]["perceived_median"])
    best = eligible[0]
    near = [it for it in eligible if it[1]["perceived_median"] - best[1]["perceived_median"] < TIE_MS]
    rule = "c" if len(near) > 1 else "b"
    k, s = min(near, key=precision) if len(near) > 1 else best
    return {"rule": rule, "model": k[0], "vad": k[1], "needs_filter_guard": False,
            "reason": ("empate a menos de 150 ms: gana el más preciso" if rule == "c"
                       else "menor latencia percibida mediana entre los que pasan (a) con p95 <= 2.500 ms"),
            "tied": [f"{a[0]}/{a[1]}" for a, _ in near] if rule == "c" else []}


def format_table(summary: dict[tuple, dict]) -> str:
    head = (f"{'modelo':<24}{'VAD':<14}{'n':>4}{'err':>4}{'mediana':>9}{'p95':>7}{'máx':>7}{'vad_sil':>8}"
            f"{'resp.med':>9}{'%cifras':>8}{'%honest':>8}{'filtros_inv':>12}{'args_err':>9}{'muletilla':>10}")
    lines = [head, "-" * len(head)]
    for (m, v), s in sorted(summary.items()):
        lines.append(f"{m:<24}{v:<14}{s['runs']:>4}{s['errors']:>4}{s['perceived_median'] or '-':>9}"
                     f"{s['perceived_p95'] or '-':>7}{s['perceived_max'] or '-':>7}{s['vad_silence_median'] or '-':>8}"
                     f"{s['answer_median'] or '-':>9}{s['cifras_correct_pct'] if s['cifras_correct_pct'] is not None else '-':>8}"
                     f"{s['honesty_correct_pct'] if s['honesty_correct_pct'] is not None else '-':>8}"
                     f"{s['invented_filters']:>12}{s['wrong_args']:>9}{s['filler_runs']:>5} ({s['filler_pct']}%)")
    lines.append("\nlatencias en ms: percibida = fin de la pregunta -> primer audio; resp.med = hasta el audio de la respuesta final")
    return "\n".join(lines)


def load_runs() -> list[dict]:
    if not RUNS_FILE.exists():
        return []
    return [json.loads(l) for l in RUNS_FILE.read_text(encoding="utf-8").splitlines() if l.strip()]


def report() -> int:
    runs = load_runs()
    if not runs:
        print("No hay corridas; ejecuta --run", file=sys.stderr)
        return 2
    summary = summarize(runs)
    print(format_table(summary))
    decision = decide({k: s for k, s in summary.items() if s["runs"] - s["errors"] > 0})
    print("\nDecisión:", json.dumps(decision, ensure_ascii=False))
    RESULTS_FILE.write_text(json.dumps({
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "rule": {"min_correct_pct": MIN_CORRECT_PCT,
                                                                   "max_p95_ms": MAX_P95_MS, "tie_ms": TIE_MS},
        "summary": {f"{m}|{v}": s for (m, v), s in summary.items()}, "decision": decision}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    return 0


async def main_async(a: argparse.Namespace) -> int:
    load_env_file(BACKEND / ".env")
    key = os.environ.get("OPENAI_API_KEY", "")
    if a.report:
        return report()
    if not key:
        print("Falta la variable de entorno OPENAI_API_KEY (entorno o backend/.env)", file=sys.stderr)
        return 2
    if a.synth:
        synthesize(key, force=a.force)
    if a.run:
        store = Store()
        if not load_snapshot(store, load_settings({"DATA_PATH": str(BACKEND.parent / "data")})):
            print("No se pudo cargar el snapshot", file=sys.stderr)
            return 2
        await run_all(a.models.split(","), a.vads.split(","), a.repeats, a.concurrency, key, store)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--synth", action="store_true")
    ap.add_argument("--force", action="store_true", help="regenera los WAV existentes")
    ap.add_argument("--run", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--models", default=",".join(CANDIDATES))
    ap.add_argument("--vads", default="semantic_vad,server_vad")
    ap.add_argument("--repeats", type=int, default=5)
    ap.add_argument("--concurrency", type=int, default=6)
    return asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
