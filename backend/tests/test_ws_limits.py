"""Protección del WebSocket público: origen, sesiones simultáneas, por IP y duración (6.2 a 6.4, 6.7)."""
import logging
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import load_settings
from app.main import create_app
from app.ws.limits import SessionLimiter, origin_allowed
from tests.fake_voice import FakeBackend

ROOT = Path(__file__).resolve().parents[2]
START = {"type": "session.start", "v": 1, "protocol": "1.0", "brief": "skip"}


def client(**extra) -> TestClient:
    env = {"DATA_PATH": str(ROOT / "data"), "VOICE_ENABLED": "true", "OPENAI_API_KEY": "sk-secret-123",
           "DEEPGRAM_API_KEY": "dg-secret-456", "VOICE_PROVIDER": "openai", "SENTIMENT_ENABLED": "false", "CORS_ORIGINS": "http://localhost:5173,https://*.vercel.app",
           **extra}
    c = TestClient(create_app(load_settings(env), backend_factory=FakeBackend))
    c.__enter__()
    for _ in range(100):
        if c.get("/health").json()["status"] == "ready":
            return c
        time.sleep(0.05)
    raise AssertionError("datos no listos")


def started(ws) -> list[dict]:
    ws.send_json(START)
    return [ws.receive_json() for _ in range(3)]


def test_origin_rules():
    allowed = ("http://localhost:5173", "https://*.vercel.app")
    assert origin_allowed("http://localhost:5173", allowed)
    assert origin_allowed("https://kognia-git-main-sofia.vercel.app", allowed)
    assert not origin_allowed("https://evil.com", allowed)
    assert not origin_allowed("https://x.vercel.app.evil.com", allowed)
    assert origin_allowed(None, allowed)                     # sin Origin: clientes que no son navegador


def test_disallowed_origin_is_rejected_with_403_and_logged(caplog):
    c = client()
    with caplog.at_level(logging.WARNING):
        with pytest.raises(WebSocketDisconnect) as e:
            with c.websocket_connect("/ws", headers={"origin": "https://evil.com"}):
                pass
    assert e.value.code == 1008
    assert "https://evil.com" in caplog.text
    with c.websocket_connect("/ws", headers={"origin": "http://localhost:5173"}) as ws:
        assert started(ws)[0]["state"] == "conectando"
    c.__exit__(None, None, None)


def test_cors_allows_vercel_previews():
    c = client()
    r = c.get("/health", headers={"Origin": "https://kognia-abc123.vercel.app"})
    assert r.headers["access-control-allow-origin"] == "https://kognia-abc123.vercel.app"
    assert "access-control-allow-origin" not in c.get("/health", headers={"Origin": "https://evil.com"}).headers
    c.__exit__(None, None, None)


def test_concurrent_limit(caplog):
    c = client(WS_MAX_SESSIONS="1")
    with c.websocket_connect("/ws") as a:
        started(a)
        with caplog.at_level(logging.WARNING), c.websocket_connect("/ws") as b:
            b.send_json(START)
            err = b.receive_json()
            assert err["code"] == "session_limit" and err["detail"] == {"reason": "concurrent"}
        assert "concurrent" in caplog.text and "sk-secret" not in caplog.text and "dg-secret" not in caplog.text
        a.send_json({"type": "text.message", "v": 1, "text": "hola"})   # la sesión activa sigue intacta
        assert a.receive_json()["type"] == "transcript.final"
    with c.websocket_connect("/ws") as d:                     # al cerrar se libera el cupo
        assert started(d)[0]["state"] == "conectando"
    c.__exit__(None, None, None)


def test_rate_limit_per_ip(caplog):
    c = client(WS_SESSIONS_PER_MINUTE="2")
    for _ in range(2):
        with c.websocket_connect("/ws") as ws:
            started(ws)
    with caplog.at_level(logging.WARNING), c.websocket_connect("/ws") as ws:
        ws.send_json(START)
        err = ws.receive_json()
        assert err["code"] == "session_limit" and err["detail"] == {"reason": "rate"}
    assert "rate" in caplog.text and "ip=" in caplog.text
    # otra IP (detrás del proxy) no se ve afectada
    with c.websocket_connect("/ws", headers={"x-forwarded-for": "10.0.0.9"}) as ws:
        assert started(ws)[0]["state"] == "conectando"
    c.__exit__(None, None, None)


def test_duration_warns_then_closes(caplog):
    c = client(SESSION_WARN_SECONDS="1", SESSION_MAX_SECONDS="2")
    with caplog.at_level(logging.WARNING), c.websocket_connect("/ws") as ws:
        started(ws)
        warn = ws.receive_json()
        assert warn["code"] == "session_expiring" and warn["severity"] == "warning"
        assert warn["detail"] == {"seconds_left": 1}
        end = ws.receive_json()
        assert end["code"] == "session_limit" and end["detail"] == {"reason": "duration"}
        assert ws.receive_json()["type"] == "session.state"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
    assert "duration" in caplog.text
    c.__exit__(None, None, None)


def test_limiter_unit():
    lim = SessionLimiter(2, 3)
    assert lim.try_acquire("a") is None and lim.try_acquire("a") is None
    assert lim.try_acquire("b") == "concurrent"
    lim.release()
    assert lim.try_acquire("a") is None
    lim.release()
    assert lim.try_acquire("a") == "rate"
