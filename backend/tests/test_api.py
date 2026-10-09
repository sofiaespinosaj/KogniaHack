import time
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app

ROOT = Path(__file__).resolve().parents[2]
FRONT = "http://localhost:5173"


def make_client(data=ROOT / "data", **env):
    return TestClient(create_app(load_settings({"DATA_PATH": str(data), **env})))


def wait_ready(c):
    for _ in range(100):
        if c.get("/health").json()["status"] == "ready":
            return
        time.sleep(0.05)
    raise AssertionError("los datos no llegaron a ready")


def test_brief_endpoint_returns_text_and_3_to_5_questions():
    with make_client() as c:
        wait_ready(c)
        r = c.get("/api/brief")
        assert r.status_code == 200
        body = r.json()
        assert set(body) == {"texto", "preguntas", "fecha_corte", "origen"}
        assert "9.320 IPS" in body["texto"] and "5 de noviembre de 2022" in body["texto"]
        assert 3 <= len(body["preguntas"]) <= 5 and all(isinstance(q, str) for q in body["preguntas"])
        assert body["fecha_corte"] == "2022-11-05" and body["origen"] == "snapshot"


def test_brief_endpoint_is_deterministic():
    with make_client() as c:
        wait_ready(c)
        assert c.get("/api/brief").json() == c.get("/api/brief").json()


def test_brief_endpoint_503_without_data(tmp_path):
    with make_client(tmp_path) as c:
        time.sleep(0.3)
        r = c.get("/api/brief")
        assert r.status_code == 503 and r.json()["status"] in ("unavailable", "loading")


def test_cors_allows_dev_front_origin():
    with make_client(CORS_ORIGINS=FRONT) as c:
        pre = c.options("/api/brief", headers={"Origin": FRONT, "Access-Control-Request-Method": "GET"})
        assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] == FRONT
        wait_ready(c)
        got = c.get("/api/brief", headers={"Origin": FRONT})
        assert got.headers["access-control-allow-origin"] == FRONT


def test_cors_rejects_other_origins():
    with make_client(CORS_ORIGINS=FRONT) as c:
        pre = c.options("/api/brief", headers={"Origin": "http://evil.example",
                                               "Access-Control-Request-Method": "GET"})
        assert "access-control-allow-origin" not in pre.headers


def test_env_example_lists_dev_front_origin():
    line = next(l for l in (ROOT / "backend" / ".env.example").read_text(encoding="utf-8").splitlines()
                if l.startswith("CORS_ORIGINS="))
    assert FRONT in line.split("=", 1)[1].split(",")
