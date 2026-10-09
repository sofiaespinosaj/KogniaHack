"""Prueba de las preguntas de oro por voz (tareas 7.1 y 7.2 de realtime-voice).

Envía por el WebSocket del backend el audio sintético de `tests/audio/gold/*.wav` (PCM16 mono 24 kHz)
a ritmo real, en frames de 40 ms y seguido de silencio, y registra por turno `first_audio_ms`,
`vad_silence_ms` y la latencia percibida (`vad_silence_ms` + `first_audio_ms`).

    uv run python -m scripts.voice_golden --url wss://<backend>/ws --runs 20
    uv run python -m scripts.voice_golden --url ws://127.0.0.1:8000/ws --runs 3 --fast   # local

Falla (código 1) si la mediana de `first_audio_ms` supera 1.500 ms; el p95 de 2.500 ms es una meta
orientativa que solo se marca en el informe. Escribe el informe JSON con `--out`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
import wave
from pathlib import Path

from websockets.asyncio.client import connect

GOLD = Path(__file__).resolve().parents[1] / "tests" / "audio" / "gold"
FRAME_BYTES, FRAME_S = 1920, 0.04
P50_LIMIT_MS, P95_GOAL_MS = 1500, 2500
TURN_TIMEOUT_S = 30


def load_gold() -> list[dict]:
    items = json.loads((GOLD / "manifest.json").read_text(encoding="utf-8"))
    for it in items:
        with wave.open(str(GOLD / it["file"])) as w:
            assert w.getframerate() == 24000 and w.getnchannels() == 1 and w.getsampwidth() == 2
            it["pcm"] = w.readframes(w.getnframes())
    return items


def pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, max(0, round(q * (len(s) - 1))))]


async def run_one(url: str, item: dict, origin: str | None, fast: bool) -> dict:
    headers = {"Origin": origin} if origin else None
    async with connect(url, additional_headers=headers, max_size=None) as ws:
        await ws.send(json.dumps({"type": "session.start", "v": 1, "protocol": "1.0", "brief": "skip"}))
        while True:
            m = json.loads(await ws.recv())
            if m["type"] == "error" and m["severity"] == "fatal":
                return {"id": item["id"], "error": m["code"]}
            if m["type"] == "session.state" and m["state"] == "escuchando":
                break
        pcm = item["pcm"] + b"\0" * (FRAME_BYTES * 40)        # 1,6 s de silencio para cerrar el turno

        async def feed():
            for i in range(0, len(pcm), FRAME_BYTES):
                await ws.send(pcm[i:i + FRAME_BYTES].ljust(FRAME_BYTES, b"\0"))
                await asyncio.sleep(0 if fast else FRAME_S)

        sender = asyncio.create_task(feed())
        out: dict = {"id": item["id"], "question": item["question"], "user_text": None, "agent_text": None,
                     "tools": []}
        deadline = time.monotonic() + TURN_TIMEOUT_S
        try:
            while time.monotonic() < deadline:
                raw = await asyncio.wait_for(ws.recv(), deadline - time.monotonic())
                if isinstance(raw, bytes):
                    continue
                m = json.loads(raw)
                if m["type"] == "transcript.final":
                    out["user_text"] = m["text"]
                elif m["type"] == "agent.tool" and m["status"] != "running":
                    out["tools"].append(m["name"])
                elif m["type"] == "agent.text" and m["final"]:
                    out["agent_text"] = m["text"]
                elif m["type"] == "metrics" and m.get("interrupted"):
                    out["interruptions"] = out.get("interruptions", 0) + 1   # el VAD partió la pregunta
                elif m["type"] == "metrics":
                    out.update({k: m.get(k) for k in ("first_audio_ms", "vad_silence_ms", "tool_ms", "total_ms")})
                    if out["first_audio_ms"] is not None:
                        out["perceived_ms"] = (out.get("vad_silence_ms") or 0) + out["first_audio_ms"]
                    return out
                elif m["type"] == "error" and m["severity"] == "fatal":
                    out["error"] = m["code"]
                    return out
            out["error"] = "timeout"
            return out
        except asyncio.TimeoutError:
            out["error"] = "timeout"
            return out
        finally:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)


async def main_async(args) -> int:
    items = load_gold()
    runs = []
    for i in range(args.runs):
        item = items[i % len(items)]
        try:
            r = await run_one(args.url, item, args.origin, args.fast)
        except Exception as e:  # noqa: BLE001
            r = {"id": item["id"], "error": type(e).__name__}
        runs.append(r)
        print(f"{r['id']:>6}  first_audio={r.get('first_audio_ms')}  vad_silence={r.get('vad_silence_ms')}  "
              f"percibida={r.get('perceived_ms')}  tools={r.get('tools')}  {r.get('error', '')}", flush=True)
    firsts = [r["first_audio_ms"] for r in runs if r.get("first_audio_ms") is not None]
    perceived = [r["perceived_ms"] for r in runs if r.get("perceived_ms") is not None]
    p50, p95 = pct(firsts, .5), pct(firsts, .95)
    report = {
        "url": args.url, "runs": runs, "ok_runs": len(firsts), "errors": len(runs) - len(firsts),
        "first_audio_p50": p50, "first_audio_p95": p95,
        "perceived_p50": pct(perceived, .5), "perceived_p95": pct(perceived, .95),
        "p50_limit_ms": P50_LIMIT_MS, "p95_goal_ms": P95_GOAL_MS,
        "p95_within_goal": p95 is not None and p95 <= P95_GOAL_MS,
        "passed": p50 is not None and p50 <= P50_LIMIT_MS,
    }
    if firsts:
        report["first_audio_mean"] = round(statistics.mean(firsts))
    print(json.dumps({k: v for k, v in report.items() if k != "runs"}, ensure_ascii=False, indent=2))
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if not report["p95_within_goal"]:
        print("Aviso: el p95 de first_audio_ms está fuera de la meta orientativa de 2.500 ms", file=sys.stderr)
    return 0 if report["passed"] else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="Preguntas de oro por voz: latencia del primer audio")
    ap.add_argument("--url", required=True, help="URL del WebSocket, p. ej. wss://backend/ws")
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--origin", default=None, help="Cabecera Origin (si el backend la exige)")
    ap.add_argument("--fast", action="store_true", help="Envía el audio sin esperar el tiempo real (solo local)")
    ap.add_argument("--out", default=None, help="Ruta del informe JSON")
    sys.exit(asyncio.run(main_async(ap.parse_args())))


if __name__ == "__main__":
    main()
