import json
import re
import time
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import load_settings
from app.main import create_app
from app.ws import export as X
from app.ws import protocol as P
from app.ws.session import InvalidTransition, SessionContext, SessionOptions
from tests.fake_voice import FakeBackend

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "backend" / "README.md"
START = {"type": "session.start", "v": 1, "protocol": "1.0"}


# --- esquema, tipos y ejemplos (2.7, 2.8, 2.9) --------------------------------------------
@pytest.fixture(scope="module")
def schema():
    return json.loads(X.SCHEMA_PATH.read_text(encoding="utf-8"))


def readme_examples() -> list[dict]:
    text = README.read_text(encoding="utf-8")
    out = []
    for block in re.findall(r"```json\n(.*?)```", text, flags=re.S):
        for line in block.strip().splitlines():
            out.append(json.loads(line))
    return out


def test_published_schema_matches_models():
    assert X.SCHEMA_PATH.read_text(encoding="utf-8") == X.schema_json(), \
        "ws-events.schema.json desactualizado: ejecuta `uv run python -m app.ws.export all`"


def test_published_typescript_matches_models():
    assert X.TS_PATH.read_text(encoding="utf-8") == X.build_ts(), \
        "ws-events.ts desactualizado: ejecuta `uv run python -m app.ws.export all`"


def test_export_check_command_passes_and_detects_staleness(tmp_path, monkeypatch):
    assert X.main(["all", "--check"]) == 0
    monkeypatch.setattr(X, "SCHEMA_PATH", tmp_path / "x.json")
    (tmp_path / "x.json").write_text("{}", encoding="utf-8")
    assert X.main(["schema", "--check"]) == 1


def test_schema_defines_every_message(schema):
    defs = set(schema["$defs"])
    for cls in P.CLIENT_TYPES + P.SERVER_TYPES:
        assert cls.__name__ in defs
    assert schema["x-protocol"] == "1.0"


def test_typescript_has_all_types_and_unions():
    ts = X.build_ts()
    for cls in P.CLIENT_TYPES + P.SERVER_TYPES:
        assert f"export interface {cls.__name__} " in ts
    assert "export type ServerMessage = SessionState | SessionBrief" in ts
    assert "export type ClientMessage = SessionStart | SessionStop | TextMessage | PlaybackPosition;" in ts
    assert 'type: "session.start";' in ts and "protocol: string;" in ts


def test_all_readme_examples_validate_against_schema(schema):
    examples = readme_examples()
    assert len(examples) >= 20
    for ex in examples:
        jsonschema.validate(ex, schema)


def test_readme_covers_every_message_type():
    seen = {e["type"] for e in readme_examples()}
    expected = {c.model_fields["type"].default for c in P.CLIENT_TYPES + P.SERVER_TYPES}
    assert expected <= seen, expected - seen


@pytest.mark.parametrize("bad", [
    {"type": "session.state", "v": 1, "state": "escuchando"},                      # sin seq
    {"type": "session.state", "v": 1, "seq": 1, "state": "dormido"},               # estado desconocido
    {"type": "nope", "v": 1},                                                      # tipo desconocido
    {"type": "session.start", "v": 2, "protocol": "1.0"},                          # v no soportada
    {"type": "text.message", "v": 1, "text": ""},                                  # vacío
    {"type": "sentiment", "v": 1, "seq": 1, "turn_id": "t", "utt_id": "u", "speaker": "s",
     "sentiment": "x", "emotion": "y", "score": 3},                                # score fuera de rango
    {"type": "error", "v": 1, "seq": 1, "code": "otro", "message": "m", "severity": "warning", "recoverable": True},
])
def test_invalid_examples_do_not_validate(schema, bad):
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, schema)


# --- máquina de estados ----------------------------------------------------------------
class _Conn:
    async def send(self, cls, **f):
        return f


async def test_state_machine_allows_a_turn_cycle_and_rejects_jumps():
    ctx = SessionContext(_Conn(), SessionOptions(), "enabled", None)
    for s in ("conectando", "listo", "escuchando", "pensando", "hablando", "escuchando"):
        await ctx.set_state(s)
    with pytest.raises(InvalidTransition):
        await ctx.set_state("listo")
    ctx.state = None
    with pytest.raises(InvalidTransition):
        await ctx.set_state("hablando")


def test_protocol_version_rules():
    assert P.protocol_supported("1.0") and P.protocol_supported("1.3")
    assert not P.protocol_supported("2.0") and not P.protocol_supported("x")


def test_turn_ids():
    ids = P.TurnIds()
    assert ids.BRIEF == "t-0000" and ids.next_turn() == "t-0001" and ids.next_turn() == "t-0002"
    assert ids.next_utt() == "u-0001"


# --- cliente simulado (2.6) ---------------------------------------------------------------
class Harness:
    def __init__(self, voice=True, factory=None):
        self.backends: list[FakeBackend] = []
        env = {"DATA_PATH": str(ROOT / "data"), "VOICE_ENABLED": "true" if voice else "false",
               "OPENAI_API_KEY": "k", "DEEPGRAM_API_KEY": "k", "VOICE_PROVIDER": "openai", "SENTIMENT_ENABLED": "false"}

        def make():
            b = factory() if factory else FakeBackend()
            self.backends.append(b)
            return b

        self.client = TestClient(create_app(load_settings(env), backend_factory=make))

    def __enter__(self):
        self.client.__enter__()
        for _ in range(100):
            if self.client.get("/health").json()["status"] == "ready":
                return self
            time.sleep(0.05)
        raise AssertionError("datos no listos")

    def __exit__(self, *a):
        self.client.__exit__(*a)


def recv_n(ws, n):
    return [ws.receive_json() for _ in range(n)]


def assert_strictly_increasing(msgs):
    seqs = [m["seq"] for m in msgs]
    assert seqs == sorted(set(seqs)) and seqs[0] >= 1


def test_start_emits_states_and_brief_equal_to_rest(schema):
    with Harness() as h, h.client.websocket_connect("/ws") as ws:
        ws.send_json(START)
        msgs = recv_n(ws, 4)
        assert [m.get("state") for m in msgs if m["type"] == "session.state"] == ["conectando", "listo", "escuchando"]
        assert msgs[0]["protocol"] == "1.0" and msgs[0]["voice"] == "enabled"
        brief = next(m for m in msgs if m["type"] == "session.brief")
        rest = h.client.get("/api/brief").json()
        assert {k: brief[k] for k in ("texto", "preguntas", "fecha_corte", "origen")} == rest
        assert brief["turn_id"] == "t-0000"
        assert_strictly_increasing(msgs)
        for m in msgs:
            jsonschema.validate(m, schema)


def test_brief_skip_omits_brief_event():
    with Harness() as h, h.client.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        msgs = recv_n(ws, 3)
        assert [m["type"] for m in msgs] == ["session.state"] * 3
        assert [m["state"] for m in msgs] == ["conectando", "listo", "escuchando"]


def test_full_turn_by_text_follows_order_and_schema(schema):
    with Harness() as h, h.client.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        recv_n(ws, 3)
        ws.send_json({"type": "text.message", "v": 1, "text": "¿Cuántas IPS hay en Antioquia?"})
        msgs, frames = [], []
        while not (msgs and msgs[-1].get("state") == "escuchando"):
            raw = ws.receive()
            if raw.get("bytes") is not None:
                frames.append(raw["bytes"])
            else:
                msgs.append(json.loads(raw["text"]))
        types = [m["type"] for m in msgs]
        order = ["transcript.final", "session.state", "agent.tool", "agent.tool", "session.state", "audio.start",
                 "agent.text", "audio.end", "metrics", "session.state"]
        assert types == order
        assert msgs[0]["source"] == "text" and msgs[0]["speaker"] == "user" and msgs[0]["turn_id"] == "t-0001"
        assert [m["state"] for m in msgs if m["type"] == "session.state"] == ["pensando", "hablando", "escuchando"]
        assert frames == [b"\0" * 1920]
        assert_strictly_increasing(msgs)
        for m in msgs:
            jsonschema.validate(m, schema)
        assert "SELECT" not in json.dumps(msgs)


@pytest.mark.parametrize("payload,reason", [
    ("no es json", "JSON inválido"),
    ('{"v": 1}', "falta el campo type"),
    ('{"type": "raro", "v": 1}', "tipo de mensaje desconocido"),
    ("[1, 2]", "el mensaje debe ser un objeto JSON"),
    ('{"type": "text.message", "v": 1}', "campo inválido"),
])
def test_invalid_messages_keep_the_connection_open(payload, reason):
    with Harness() as h, h.client.websocket_connect("/ws") as ws:
        ws.send_text(payload)
        err = ws.receive_json()
        assert err["code"] == "invalid_message" and err["severity"] == "warning" and err["recoverable"]
        assert err["detail"]["reason"] == reason
        ws.send_json(START)                                  # la conexión sigue viva y arranca normal
        assert ws.receive_json()["state"] == "conectando"


def test_unsupported_protocol_lists_supported_versions():
    with Harness() as h, h.client.websocket_connect("/ws") as ws:
        ws.send_json({**START, "protocol": "2.0"})
        err = ws.receive_json()
        assert err["code"] == "unsupported_protocol" and err["detail"] == {"supported": ["1.0"]}


def test_voice_disabled_error():
    with Harness(voice=False) as h, h.client.websocket_connect("/ws") as ws:
        ws.send_json(START)
        err = ws.receive_json()
        assert err["code"] == "voice_disabled" and err["severity"] == "fatal"


def test_no_active_session_for_audio_and_messages():
    with Harness() as h, h.client.websocket_connect("/ws") as ws:
        ws.send_bytes(b"\0" * 1920)
        assert ws.receive_json()["code"] == "no_active_session"
        ws.send_json({"type": "text.message", "v": 1, "text": "hola"})
        assert ws.receive_json()["code"] == "no_active_session"
        ws.send_json({"type": "session.stop", "v": 1})
        assert ws.receive_json()["code"] == "no_active_session"


def test_audio_is_forwarded_and_bad_frames_rejected():
    with Harness() as h, h.client.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        recv_n(ws, 3)
        ws.send_bytes(b"\1\0" * 960)
        ws.send_bytes(b"\1")                                  # impar: inválido
        err = ws.receive_json()
        assert err["code"] == "invalid_message"
        ws.send_json({"type": "playback.position", "v": 1, "turn_id": "t-0001", "played_ms": 500})
        ws.send_json({"type": "session.stop", "v": 1})
        final = ws.receive_json()
        assert final["type"] == "session.state" and final["detail"] == "sesión finalizada"
        b = h.backends[0]
        assert b.frames == [b"\1\0" * 960] and b.played == [("t-0001", 500)] and b.stopped


def test_second_start_is_rejected_without_affecting_session():
    with Harness() as h, h.client.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        recv_n(ws, 3)
        ws.send_json(START)
        assert ws.receive_json()["code"] == "session_already_active"
        ws.send_bytes(b"\0" * 1920)
        ws.send_json({"type": "session.stop", "v": 1})
        ws.receive_json()
        assert len(h.backends) == 1 and len(h.backends[0].frames) == 1


def test_stop_sends_final_state_then_closes():
    with Harness() as h, h.client.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        recv_n(ws, 3)
        ws.send_json({"type": "session.stop", "v": 1})
        assert ws.receive_json()["type"] == "session.state"
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
        assert h.backends[0].stopped


def test_abrupt_close_releases_backend():
    with Harness() as h:
        with h.client.websocket_connect("/ws") as ws:
            ws.send_json({**START, "brief": "skip"})
            recv_n(ws, 3)
        for _ in range(50):
            if h.backends[0].stopped:
                break
            time.sleep(0.05)
        assert h.backends[0].stopped


def test_reconnection_starts_a_new_session_with_seq_from_1():
    with Harness() as h:
        with h.client.websocket_connect("/ws") as ws:
            ws.send_json(START)
            first = recv_n(ws, 4)
        with h.client.websocket_connect("/ws") as ws:
            ws.send_json({**START, "brief": "skip"})
            second = recv_n(ws, 3)
        assert first[0]["seq"] == 1 and second[0]["seq"] == 1
        assert len(h.backends) == 2 and all(m["type"] == "session.state" for m in second)


def test_openai_failure_reports_error_keeps_socket_open_and_allows_retry(schema):
    calls = {"n": 0}

    def factory():
        calls["n"] += 1
        return FakeBackend(fail=calls["n"] == 1)

    with Harness(factory=factory) as h, h.client.websocket_connect("/ws") as ws:
        ws.send_json(START)
        msgs = recv_n(ws, 3)
        assert [m["type"] for m in msgs] == ["session.state", "error", "session.state"]
        assert msgs[1]["code"] == "openai_unavailable" and msgs[2]["state"] == "error"
        assert "sk-secret" not in json.dumps(msgs) and "RuntimeError" not in json.dumps(msgs)
        for m in msgs:
            jsonschema.validate(m, schema)
        ws.send_json({**START, "brief": "skip"})              # reintento en la misma conexión
        assert ws.receive_json()["state"] == "conectando"


def test_data_unavailable_before_load(tmp_path):
    env = {"DATA_PATH": str(tmp_path), "VOICE_ENABLED": "true", "OPENAI_API_KEY": "k", "DEEPGRAM_API_KEY": "k", "VOICE_PROVIDER": "openai", "SENTIMENT_ENABLED": "false"}
    with TestClient(create_app(load_settings(env), backend_factory=FakeBackend)) as c:
        time.sleep(0.3)
        with c.websocket_connect("/ws") as ws:
            ws.send_json(START)
            assert ws.receive_json()["code"] == "data_unavailable"
