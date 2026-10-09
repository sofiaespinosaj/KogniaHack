import asyncio
import base64
import importlib.util
import json
from pathlib import Path

import pytest

from app.agent.gold import GOLD, number_matches
from app.agent.tools import AgentTools, ToolSession
from app.config import load_settings
from app.datastore.loader import load_snapshot
from app.datastore.store import Store

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("spike_realtime", ROOT / "scripts" / "spike_realtime.py")
spike = importlib.util.module_from_spec(spec)
spec.loader.exec_module(spike)


@pytest.fixture(scope="module")
def store():
    s = Store()
    assert load_snapshot(s, load_settings({"DATA_PATH": str(ROOT.parent / "data")}))
    return s


@pytest.mark.parametrize("spoken,expected", [
    ("Hay nueve mil trescientos veinte IPS", "Hay 9.320 IPS"),
    ("unas cuarenta y cinco mil camas", "unas 45 mil camas"),
    ("seis mil cuatrocientos treinta y ocho camas", "6.438 camas"),
    ("ochocientas trece IPS", "813 IPS"),
    ("el cinco de noviembre de dos mil veintidós", "el cinco de noviembre de 2.022"),
    ("un departamento y tres niveles", "un departamento y tres niveles"),
    ("dos millones de camas", "2 millones de camas"),
    ("mil doscientas setenta", "1.270"),
])
def test_words_to_digits(spoken, expected):
    assert spike.words_to_digits(spoken) == expected


def test_spoken_rounding_matches_expected():
    assert number_matches(spike.words_to_digits("unas cuarenta y cinco mil camas"), 45262)
    assert not number_matches(spike.words_to_digits("unas cuarenta y seis mil camas"), 45262)


def test_session_config_has_flat_tools_and_no_secrets(store):
    tools = AgentTools(store).schemas()
    cfg = spike.session_config(tools, vad=spike.VAD_CANDIDATES["semantic_vad"], transcription="x")
    s = cfg["session"]
    assert s["type"] == "realtime" and s["output_modalities"] == ["audio"]
    assert s["audio"]["input"]["turn_detection"] == {"type": "semantic_vad"}
    assert s["audio"]["input"]["transcription"] == {"model": "x"} and s["audio"]["output"]["voice"] == "marin"
    assert [t["name"] for t in s["tools"]][:2] == ["count_ips", "count_sedes"] and "sk-" not in json.dumps(cfg)


class FakeWS:
    def __init__(self, script):
        self.sent, self._script = [], list(script)

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def recv(self):
        await asyncio.sleep(0.001)
        return json.dumps(self._script.pop(0))


def _audio(n=4800):
    return {"type": "response.output_audio.delta", "delta": base64.b64encode(b"\0" * n).decode()}


async def test_ask_runs_tool_round_trip_and_measures(store):
    call = {"type": "response.done", "response": {"status": "completed", "output": [
        {"type": "function_call", "name": "count_ips", "call_id": "c1", "arguments": "{}"}]}}
    final = [_audio(), _audio(), {"type": "response.output_audio_transcript.done",
                                   "transcript": "Hay nueve mil trescientos veinte IPS."},
             {"type": "response.done", "response": {"status": "completed", "output": [{"type": "message"}]}}]
    ws = FakeWS([call, *final])
    run = await spike.ask(ws, ToolSession(AgentTools(store)), "¿Cuántas IPS hay en total?")
    assert run["tools"] == ["count_ips"] and run["results"][0]["valor"] == 9320
    assert run["first_audio_ms"] is not None and run["audio_s"] == pytest.approx(0.2)
    kinds = [m["type"] for m in ws.sent]
    assert kinds == ["conversation.item.create", "response.create", "conversation.item.create", "response.create"]
    assert ws.sent[2]["item"]["type"] == "function_call_output" and ws.sent[2]["item"]["call_id"] == "c1"
    g = next(x for x in GOLD if x.id == "4.1")
    assert spike.judge(g, 9320, run) == (True, "ok")


async def test_ask_no_tool_honesty_and_error_paths(store):
    ws = FakeWS([_audio(), {"type": "response.output_audio_transcript.done",
                            "transcript": "El dataset no contiene calidad ni calificaciones; puedo contar IPS por zona."},
                 {"type": "response.done", "response": {"status": "completed", "output": []}}])
    run = await spike.ask(ws, ToolSession(AgentTools(store)), "¿Cuál es la mejor clínica de Bogotá?")
    g = next(x for x in GOLD if x.id == "4.9")
    assert run["tools"] == [] and spike.judge(g, [], run)[0] is True
    bad = FakeWS([{"type": "error", "error": {"message": "boom"}}])
    run = await spike.ask(bad, ToolSession(AgentTools(store)), "x")
    assert spike.judge(g, [], run) == (None, "boom")


def test_env_loader_does_not_override_or_print(tmp_path, monkeypatch, capsys):
    f = tmp_path / ".env"
    f.write_text("OPENAI_API_KEY=sk-from-file\nEMPTY=\n# c\n", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    spike.load_env_file(f)
    import os
    assert os.environ["OPENAI_API_KEY"] == "sk-from-file" and capsys.readouterr().out == ""
    monkeypatch.delenv("OPENAI_API_KEY")


def test_redact_hides_key_like_fragments():
    assert "sk-proj-abc123" not in spike.redact("Incorrect API key provided: sk-proj-abc123****xyz")


@pytest.mark.parametrize("spoken,expected", [
    ("unas 9 mil 320 IPS", "unas 9.320 IPS"),
    ("cerca de 6 mil 438 camas", "cerca de 6.438 camas"),
    ("unas 45 mil camas", "unas 45 mil camas"),
])
def test_mixed_digits_and_mil(spoken, expected):
    assert spike.words_to_digits(spoken) == expected


def test_honesty_patterns_accept_natural_refusals():
    from app.agent.text_agent import check_answer
    q49, q410 = (next(g for g in GOLD if g.id == i) for i in ("4.9", "4.10"))
    assert check_answer(q49, [], "No puedo determinar cuál es la mejor clínica, ya que no manejo evaluaciones de calidad.", [])[0]
    assert check_answer(q410, [], "No cuento con datos de médicos, pero sí de capacidad instalada.", [])[0]
    assert not check_answer(q49, [], "La mejor clínica es la Clínica del Country.", [])[0]
