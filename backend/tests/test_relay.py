"""Relé de voz de extremo a extremo contra OpenAI Realtime y Deepgram simulados (scripts/fake_services.py)."""
import asyncio
import json
import socket
import struct
import threading
import time
from pathlib import Path

import jsonschema
import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app
from app.voice.relay import truncate_text
from app.ws import export as X
from scripts.fake_services import DeepgramState, FakeDeepgram, FakeOpenAI, OpenAIState, serve_fakes

ROOT = Path(__file__).resolve().parents[2]
START = {"type": "session.start", "v": 1, "protocol": "1.0"}
LOUD = struct.pack("<960h", *([8000, -8000] * 480))        # 40 ms de "voz"
QUIET = b"\0" * 1920                                       # 40 ms de silencio
SCHEMA = json.loads(X.SCHEMA_PATH.read_text(encoding="utf-8"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Fakes:
    """OpenAI y Deepgram simulados en un hilo con su propio bucle de eventos."""

    def __init__(self) -> None:
        self.openai = FakeOpenAI(OpenAIState())
        self.deepgram = FakeDeepgram(DeepgramState())
        self.oa_port, self.dg_port = free_port(), free_port()
        self.loop = asyncio.new_event_loop()
        ready = threading.Event()

        def run():
            asyncio.set_event_loop(self.loop)
            self.servers = self.loop.run_until_complete(
                serve_fakes(self.oa_port, self.dg_port, openai=self.openai, deepgram=self.deepgram))
            ready.set()
            self.loop.run_forever()

        self.thread = threading.Thread(target=run, daemon=True)
        self.thread.start()
        ready.wait(5)

    def call(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self.loop).result(5)

    def close(self) -> None:
        async def shutdown():
            for s in self.servers:
                s.close()
            for s in self.servers:
                try:
                    await asyncio.wait_for(s.wait_closed(), 2)
                except asyncio.TimeoutError:
                    pass
        self.call(shutdown())
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(5)


@pytest.fixture
def fakes():
    f = Fakes()
    yield f
    f.close()


def make_client(fakes: Fakes, **extra) -> TestClient:
    env = {"DATA_PATH": str(ROOT / "data"), "VOICE_ENABLED": "true", "OPENAI_API_KEY": "sk-test-secret",
           "DEEPGRAM_API_KEY": "dg-test-secret", "VOICE_PROVIDER": "openai", "SENTIMENT_ENABLED": "false", "OPENAI_REALTIME_URL": f"ws://127.0.0.1:{fakes.oa_port}",
           "DEEPGRAM_URL": f"ws://127.0.0.1:{fakes.dg_port}", **extra}
    return TestClient(create_app(load_settings(env)))


class Live:
    def __init__(self, client: TestClient) -> None:
        self.client = client

    def __enter__(self):
        self.client.__enter__()
        for _ in range(100):
            if self.client.get("/health").json()["status"] == "ready":
                return self.client
            time.sleep(0.05)
        raise AssertionError("datos no listos")

    def __exit__(self, *a):
        self.client.__exit__(*a)


def collect(ws, until, limit=400):
    """Lee mensajes (JSON y binarios) hasta que `until(msgs)` sea verdadero."""
    msgs, frames = [], []
    for _ in range(limit):
        raw = ws.receive()
        if raw.get("bytes") is not None:
            frames.append(raw["bytes"])
            continue
        msgs.append(json.loads(raw["text"]))
        if until(msgs):
            return msgs, frames
    raise AssertionError(f"no se cumplió la condición: {[m['type'] for m in msgs]}")


def state_is(state):
    return lambda msgs: msgs[-1]["type"] == "session.state" and msgs[-1]["state"] == state


def speak(ws, loud_frames=10, quiet_frames=10):
    for _ in range(loud_frames):
        ws.send_bytes(LOUD)
    for _ in range(quiet_frames):
        ws.send_bytes(QUIET)


def test_brief_is_spoken_under_t0000_with_40ms_frames(fakes):
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json(START)
        msgs, frames = collect(ws, lambda m: m[-1]["type"] == "audio.end")
        types = [m["type"] for m in msgs]
        assert types[:3] == ["session.state", "session.state", "session.brief"]
        assert msgs[2]["turn_id"] == "t-0000"
        start = next(m for m in msgs if m["type"] == "audio.start")
        assert start["turn_id"] == "t-0000"
        final = [m for m in msgs if m["type"] == "agent.text" and m["final"]][-1]
        assert final["text"] == msgs[2]["texto"] and final["turn_id"] == "t-0000"
        assert frames and all(len(f) == 1920 for f in frames)
        assert "metrics" not in types                       # el brief no es un turno medido
        for m in msgs:
            jsonschema.validate(m, SCHEMA)


def test_text_turn_runs_tool_on_server_and_reports_metrics(fakes):
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        collect(ws, state_is("escuchando"))
        ws.send_json({"type": "text.message", "v": 1, "text": "¿Cuántas IPS hay en Antioquia?"})
        msgs, frames = collect(ws, lambda m: m[-1]["type"] == "metrics")
        for m in msgs:
            jsonschema.validate(m, SCHEMA)
        tools = [m for m in msgs if m["type"] == "agent.tool"]
        assert [t["status"] for t in tools] == ["running", "done"]
        assert tools[1]["args"] == {"departamento": "Antioquia"} and isinstance(tools[1]["summary"]["valor"], int)
        valor = tools[1]["summary"]["valor"]
        final = next(m for m in msgs if m["type"] == "agent.text" and m["final"])
        assert str(valor) in final["text"] and not final["interrupted"]
        metrics = msgs[-1]
        assert metrics["turn_id"] == "t-0001" and metrics["first_audio_ms"] >= 0
        assert metrics["tool_ms"] >= 0 and metrics["total_ms"] >= metrics["first_audio_ms"]
        assert "vad_silence_ms" not in metrics               # turno por texto
        assert frames and all(len(f) == 1920 for f in frames)
        out = [e for e in fakes.openai.state.received if e["type"] == "conversation.item.create"
               and e["item"]["type"] == "function_call_output"]
        assert json.loads(out[0]["item"]["output"])["valor"] == valor
        assert "SELECT" not in json.dumps(msgs) and "sk-test-secret" not in json.dumps(msgs)


def test_session_update_registers_tools_instructions_and_vad(fakes):
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        collect(ws, state_is("escuchando"))
    upd = next(e for e in fakes.openai.state.received if e["type"] == "session.update")["session"]
    names = {t["name"] for t in upd["tools"]}
    assert {"count_ips", "count_sedes", "sum_capacidad"} <= names
    assert "IPS" in upd["instructions"]
    td = upd["audio"]["input"]["turn_detection"]
    assert td["type"] == "server_vad" and td["silence_duration_ms"] == 500 and td["interrupt_response"]
    assert upd["audio"]["input"]["transcription"]["model"]
    assert upd["audio"]["output"]["voice"] == "marin" and upd["audio"]["output"]["speed"] == 0.9
    assert upd["audio"]["input"]["transcription"]["language"] == "es"
    assert "IPS" in upd["audio"]["input"]["transcription"]["prompt"]


def test_audio_out_false_answers_with_text_only(fakes):
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip", "audio_out": False})
        collect(ws, state_is("escuchando"))
        ws.send_json({"type": "text.message", "v": 1, "text": "¿Cuántas IPS hay en total?"})
        msgs, frames = collect(ws, lambda m: m[-1]["type"] == "metrics")
        assert frames == [] and "audio.start" not in [m["type"] for m in msgs]
        assert any(m["type"] == "agent.text" and m["final"] and m["text"] for m in msgs)


def test_voice_turn_uses_deepgram_labels_and_reports_vad_silence(fakes):
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        collect(ws, state_is("escuchando"))
        time.sleep(0.3)                                       # Deepgram conectado
        speak(ws)
        msgs, _ = collect(ws, lambda m: m[-1]["type"] == "metrics")
        for m in msgs:
            jsonschema.validate(m, SCHEMA)
        partial = next(m for m in msgs if m["type"] == "transcript.partial")
        final = next(m for m in msgs if m["type"] == "transcript.final")
        assert partial["utt_id"] == final["utt_id"] and final["source"] == "deepgram" and not final["degraded"]
        assert final["speaker"] == "speaker_1" and final["ts_end"] >= final["ts"]
        assert final["turn_id"] == msgs[-1]["turn_id"] == "t-0001"
        assert not any(m["type"] == "transcript.final" and m["source"] == "openai" for m in msgs)
        assert msgs[-1]["vad_silence_ms"] == 500 and msgs[-1]["first_audio_ms"] is not None
        st = fakes.deepgram.state
        assert "model=nova-3" in st.paths[0] and "language=es" in st.paths[0] and "diarize=true" in st.paths[0]
        assert "sample_rate=24000" in st.paths[0] and st.auth[0] == "Token dg-test-secret"


def test_two_voices_get_two_stable_speaker_labels(fakes):
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip", "audio_out": False})
        collect(ws, state_is("escuchando"))
        time.sleep(0.3)
        speakers = []
        for _ in range(3):                                    # ráfagas: hablante 0, 1, 0
            speak(ws)
            msgs, _ = collect(ws, lambda m: m[-1]["type"] == "metrics")
            speakers += [m["speaker"] for m in msgs if m["type"] == "transcript.final"]
        assert speakers == ["speaker_1", "speaker_2", "speaker_1"]


def test_barge_in_clears_audio_cancels_and_truncates(fakes):
    fakes.openai.state.word_delay = 0.25                      # respuesta lenta para poder interrumpir
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        collect(ws, state_is("escuchando"))
        ws.send_json({"type": "text.message", "v": 1, "text": "¿Cuántas IPS hay en total?"})
        collect(ws, lambda m: m[-1]["type"] == "agent.text")
        ws.send_json({"type": "playback.position", "v": 1, "turn_id": "t-0001", "played_ms": 100})
        t0 = time.monotonic()
        for _ in range(3):
            ws.send_bytes(LOUD)
        msgs, _ = collect(ws, lambda m: m[-1]["type"] == "audio.clear")
        clear_ms = (time.monotonic() - t0) * 1000
        msgs2, _ = collect(ws, lambda m: m[-1]["type"] == "session.state")
        allm = msgs + msgs2
        assert allm[-1]["state"] == "escuchando"
        final = next(m for m in allm if m["type"] == "agent.text" and m["final"])
        assert final["interrupted"] and final["turn_id"] == "t-0001"
        metrics = next(m for m in allm if m["type"] == "metrics")
        assert metrics["interrupted"] is True
        assert clear_ms < 300
        rec = fakes.openai.state.received
        assert any(e["type"] == "response.cancel" for e in rec)
        trunc = next(e for e in rec if e["type"] == "conversation.item.truncate")
        assert trunc["audio_end_ms"] == 100 and trunc["content_index"] == 0
        # el turno cancelado no vuelve a emitir audio ni texto
        for _ in range(10):
            ws.send_bytes(QUIET)
        late, frames = collect(ws, lambda m: m[-1]["type"] == "metrics")
        assert all(m.get("turn_id") != "t-0001" for m in late if "turn_id" in m)


def test_deepgram_down_degrades_to_openai_transcript_with_warning(fakes):
    fakes.deepgram.state.fail = True
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        t0 = time.monotonic()
        msgs, _ = collect(ws, lambda m: m[-1]["type"] == "error")
        assert msgs[-1]["code"] == "deepgram_unavailable" and msgs[-1]["severity"] == "warning"
        assert time.monotonic() - t0 <= 2.5
        speak(ws)
        msgs, _ = collect(ws, lambda m: m[-1]["type"] == "metrics")
        final = next(m for m in msgs if m["type"] == "transcript.final")
        assert final["source"] == "openai" and final["degraded"] and final["speaker"] == "user"
        assert final["text"] == "¿Cuántas IPS hay en total?"


def test_deepgram_recovers_and_announces_it(fakes):
    fakes.deepgram.state.fail = True
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        collect(ws, lambda m: m[-1]["type"] == "error")
        fakes.deepgram.state.fail = False
        msgs, _ = collect(ws, lambda m: m[-1].get("detail") == "transcripción con hablantes restablecida")
        assert msgs[-1]["type"] == "session.state"


def test_openai_drop_reports_error_keeps_socket_and_allows_retry(fakes):
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        collect(ws, state_is("escuchando"))
        fakes.call(fakes.openai.drop_all())
        msgs, _ = collect(ws, state_is("error"))
        err = next(m for m in msgs if m["type"] == "error")
        assert err["code"] == "openai_unavailable" and err["severity"] == "fatal"
        time.sleep(0.2)
        ws.send_json({**START, "brief": "skip"})
        msgs, _ = collect(ws, state_is("escuchando"))
        assert msgs[0]["state"] == "conectando"


def test_abrupt_close_releases_openai_and_deepgram_within_5s(fakes):
    with Live(make_client(fakes)) as c:
        with c.websocket_connect("/ws") as ws:
            ws.send_json({**START, "brief": "skip"})
            collect(ws, state_is("escuchando"))
            time.sleep(0.3)
            assert fakes.openai.state.open_connections == 1 and fakes.deepgram.state.open_connections == 1
        t0 = time.monotonic()
        while time.monotonic() - t0 < 5:
            if fakes.openai.state.open_connections == 0 and fakes.deepgram.state.open_connections == 0:
                break
            time.sleep(0.05)
        assert fakes.openai.state.open_connections == 0 and fakes.deepgram.state.open_connections == 0


def test_truncate_text_cuts_on_word_boundary():
    assert truncate_text("En Antioquia hay unas 840 IPS", 0.5) == "En Antioquia"
    assert truncate_text("hola", 1.0) == "hola" and truncate_text("hola mundo", 0) == ""


def test_deepgram_failure_is_described_without_secrets():
    from types import SimpleNamespace
    from app.voice.deepgram import describe_failure

    class Rejected(Exception):
        def __init__(self, status, headers=None, body=b""):
            self.response = SimpleNamespace(status_code=status, headers=headers or {}, body=body)

    assert describe_failure(Rejected(401)).startswith("HTTP 401 (clave inválida")
    assert "sin saldo" in describe_failure(Rejected(402))
    assert describe_failure(Rejected(400, {"dg-error": "Bad language"})) == "HTTP 400 (parámetros rechazados): Bad language"
    assert describe_failure(TimeoutError()) == "TimeoutError"


def test_barge_in_while_client_still_plays_a_finished_response(fakes):
    """OpenAI genera más rápido que tiempo real: la respuesta termina en el servidor mientras el cliente
    sigue reproduciendo. Si el usuario habla entonces, el agente también debe callar."""
    fakes.openai.state.word_ms = 1000                     # 1 s de audio por palabra, generado casi al instante
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        collect(ws, state_is("escuchando"))
        ws.send_json({"type": "text.message", "v": 1, "text": "¿Cuántas IPS hay en total?"})
        msgs, _ = collect(ws, lambda m: m[-1]["type"] == "metrics")   # turno terminado en el servidor
        full = next(m for m in msgs if m["type"] == "agent.text" and m["final"])["text"]
        ws.send_json({"type": "playback.position", "v": 1, "turn_id": "t-0001", "played_ms": 1500})
        for _ in range(3):
            ws.send_bytes(LOUD)
        msgs, _ = collect(ws, lambda m: m[-1]["type"] == "audio.clear")
        assert msgs[-1]["turn_id"] == "t-0001"
        msgs, _ = collect(ws, lambda m: m[-1]["type"] == "agent.text")
        assert msgs[-1]["interrupted"] and msgs[-1]["final"] and len(msgs[-1]["text"]) < len(full)
        trunc = next(e for e in fakes.openai.state.received if e["type"] == "conversation.item.truncate")
        assert trunc["audio_end_ms"] == 1500


def test_no_clear_when_playback_already_finished(fakes):
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip", "audio_out": True})
        collect(ws, state_is("escuchando"))
        ws.send_json({"type": "text.message", "v": 1, "text": "¿Cuántas IPS hay en total?"})
        collect(ws, lambda m: m[-1]["type"] == "metrics")
        ws.send_json({"type": "playback.position", "v": 1, "turn_id": "t-0001", "played_ms": 100000})
        time.sleep(0.1)
        speak(ws)
        msgs, _ = collect(ws, lambda m: m[-1]["type"] == "metrics")
        assert not any(m["type"] == "audio.clear" and m["turn_id"] == "t-0001" for m in msgs)
