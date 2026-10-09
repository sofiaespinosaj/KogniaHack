"""Prueba de humo contra la URL pública del backend (deployment-readme).

    uv run python -m scripts.smoke https://<backend>.onrender.com --origin https://<front>.vercel.app

Verifica `/health` (datos listos y voz habilitada), `GET /api/brief` (texto y de 3 a 5 preguntas) y una sesión
WebSocket (`wss://.../ws`) con `text.message` que debe producir `transcript.final`, `agent.tool`, `agent.text`
final y `metrics` en 20 s o menos. Envía el `Origin` del frontend para probar CORS. Nunca imprime claves.
Código de salida 0 si todo pasa; 1 si algo falla.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time

import httpx
from websockets.asyncio.client import connect

QUESTION = "¿Cuántas IPS hay en total?"
TURN_TIMEOUT_S = 20


def ok(msg: str) -> None:
    print(f"OK    {msg}", flush=True)


class Fail(Exception):
    pass


def check_http(base: str, origin: str | None) -> None:
    headers = {"Origin": origin} if origin else {}
    with httpx.Client(timeout=15) as c:
        t0 = time.monotonic()
        h = c.get(f"{base}/health", headers=headers)
        ms = round((time.monotonic() - t0) * 1000)
        if h.status_code != 200:
            raise Fail(f"/health respondió HTTP {h.status_code}")
        body = h.json()
        if body.get("status") not in ("ready", "degraded"):
            raise Fail(f"/health: datos no listos (status={body.get('status')}, error={body.get('error')})")
        ok(f"/health en {ms} ms: datos {body['status']} ({body['data'].get('rows')} filas, origen "
           f"{body['data'].get('source')})")
        if body.get("voice") != "enabled":
            raise Fail("/health: la voz está apagada (VOICE_ENABLED no es true)")
        keys = body.get("voice_keys") or {}
        ok(f"voz habilitada con {body.get('voice_provider')}; claves presentes: "
           + ", ".join(k for k, v in keys.items() if v))
        if origin and h.headers.get("access-control-allow-origin") != origin:
            raise Fail(f"CORS: el backend no permite el origen {origin} (revisa CORS_ORIGINS)")
        if origin:
            ok(f"CORS permite {origin}")
        b = c.get(f"{base}/api/brief", headers=headers)
        if b.status_code != 200:
            raise Fail(f"/api/brief respondió HTTP {b.status_code}")
        brief = b.json()
        if not brief.get("texto") or not 3 <= len(brief.get("preguntas", [])) <= 5:
            raise Fail("/api/brief: falta el texto o no trae de 3 a 5 preguntas")
        ok(f"/api/brief: «{brief['texto'][:60]}…» y {len(brief['preguntas'])} preguntas")


async def check_ws(ws_url: str, origin: str | None) -> None:
    headers = {"Origin": origin} if origin else None
    async with connect(ws_url, additional_headers=headers, max_size=None, open_timeout=15) as ws:
        await ws.send(json.dumps({"type": "session.start", "v": 1, "protocol": "1.0", "brief": "skip"}))
        await expect(ws, lambda m: m["type"] == "session.state" and m["state"] == "escuchando", "sesión lista")
        ok("sesión WebSocket iniciada (WSS)" if ws_url.startswith("wss") else "sesión WebSocket iniciada")
        t0 = time.monotonic()
        await ws.send(json.dumps({"type": "text.message", "v": 1, "text": QUESTION}))
        seen: dict[str, dict] = {}
        frames = 0
        deadline = t0 + TURN_TIMEOUT_S
        while time.monotonic() < deadline:
            raw = await asyncio.wait_for(ws.recv(), deadline - time.monotonic())
            if isinstance(raw, bytes):
                frames += 1
                continue
            m = json.loads(raw)
            if m["type"] == "error" and m["severity"] == "fatal":
                raise Fail(f"error fatal en la sesión: {m['code']} ({m['message']})")
            if m["type"] == "agent.text" and not m["final"]:
                continue
            seen.setdefault(m["type"], m)
            if m["type"] == "metrics":
                break
        missing = [t for t in ("transcript.final", "agent.tool", "agent.text", "metrics") if t not in seen]
        if missing:
            raise Fail(f"el turno no completó en {TURN_TIMEOUT_S} s; faltó: {', '.join(missing)}")
        met = seen["metrics"]
        ok(f"turno completo en {round((time.monotonic() - t0) * 1000)} ms: tool {seen['agent.tool']['name']}, "
           f"primer audio {met.get('first_audio_ms')} ms, {frames} frames de audio")
        ok(f"respuesta: «{seen['agent.text']['text'][:90]}»")
        await ws.send(json.dumps({"type": "session.stop", "v": 1}))


async def expect(ws, cond, what: str) -> dict:
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        raw = await asyncio.wait_for(ws.recv(), deadline - time.monotonic())
        if isinstance(raw, bytes):
            continue
        m = json.loads(raw)
        if m["type"] == "error" and m["severity"] == "fatal":
            raise Fail(f"{what}: error {m['code']} ({m['message']})")
        if cond(m):
            return m
    raise Fail(f"{what}: tiempo agotado")


def main() -> None:
    ap = argparse.ArgumentParser(description="Prueba de humo del backend desplegado")
    ap.add_argument("url", help="URL base del backend, p. ej. https://lumi-backend.onrender.com")
    ap.add_argument("--origin", default=None, help="Origen del frontend para probar CORS, p. ej. https://lumi.vercel.app")
    args = ap.parse_args()
    base = args.url.rstrip("/")
    ws_url = base.replace("https://", "wss://").replace("http://", "ws://") + "/ws"
    try:
        check_http(base, args.origin)
        asyncio.run(check_ws(ws_url, args.origin))
    except Fail as e:
        print(f"FALLA {e}", flush=True)
        sys.exit(1)
    except Exception as e:  # noqa: BLE001
        print(f"FALLA {type(e).__name__}: {str(e)[:200]}", flush=True)
        sys.exit(1)
    print("Prueba de humo superada.")


if __name__ == "__main__":
    main()
