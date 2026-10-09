import array
import asyncio
import base64
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app.agent.gold import GOLD
from app.agent.tools import AgentTools
from app.config import load_settings
from app.datastore.loader import load_snapshot
from app.datastore.store import Store

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location("spike_realtime_audio", SCRIPTS / "spike_realtime_audio.py")
sa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sa)

G = {g.id: g for g in GOLD}


@pytest.fixture(scope="module")
def store():
    s = Store()
    assert load_snapshot(s, load_settings({"DATA_PATH": str(SCRIPTS.parents[1] / "data")}))
    return s


# --- audio ---------------------------------------------------------------------
def _pcm(samples):
    return array.array("h", samples).tobytes()


def test_trim_silence_and_frames():
    quiet, loud = [0] * 24000, [8000] * 4800            # 1 s de silencio, 200 ms de voz
    pcm = _pcm(quiet + loud + quiet)
    trimmed = sa.trim_silence(pcm)
    assert 4800 * 2 < len(trimmed) < 4800 * 2 + 2 * 2 * 24000 * 0.07
    frames = sa.frames_of(trimmed)
    assert all(len(f) == sa.FRAME_BYTES == 1920 for f in frames)


def test_wav_roundtrip(tmp_path):
    pcm = _pcm([100, -100] * 2400)
    sa.write_wav(tmp_path / "a.wav", pcm)
    assert sa.read_wav(tmp_path / "a.wav") == pcm


# --- clasificación de llamadas -------------------------------------------------
def test_classify_expected_call_is_clean():
    c = sa.classify_calls(G["4.5"], [{"name": "count_ips", "args": {"municipio": "medellín"}, "estado": "ok"}])
    assert c == {"invented_filters": [], "wrong_args": [], "unneeded_call": False}


def test_classify_invented_filter_wrong_value_and_unneeded_call():
    c = sa.classify_calls(G["4.6"], [{"name": "sum_capacidad", "args": {
        "grupo_capacidad": "CAMAS", "departamento": "Antioquia", "naturaleza": "Mixta"}, "estado": "ok"}])
    assert c["invented_filters"] == ["naturaleza=Mixta"] and not c["wrong_args"]
    c = sa.classify_calls(G["4.6"], [{"name": "sum_capacidad", "args": {"departamento": "Cauca"}, "estado": "ok"}])
    assert c["wrong_args"] == ["departamento=Cauca"]
    c = sa.classify_calls(G["4.9"], [{"name": "count_ips", "args": {"municipio": "Bogotá"}, "estado": "ok"}])
    assert c["unneeded_call"] and c["invented_filters"] == ["municipio=Bogotá"]
    c = sa.classify_calls(G["4.1"], [{"name": "count_ips", "args": {}, "estado": "error_validacion"}])
    assert c["wrong_args"] == ["count_ips:error_validacion"]


# --- resumen y regla de decisión -------------------------------------------------
def mk(model, vad, perceived, correct=True, invented=0, n=20, filler=False):
    runs = []
    for i in range(n):
        runs.append({"model": model, "vad": vad, "id": "4.1", "rep": i, "kind": "cifra",
                     "vad_silence_ms": 500, "first_audio_ms": perceived - 500, "perceived_ms": perceived + (i % 5) * 10,
                     "answer_ms": perceived, "tool_ms": 5, "filler": filler, "tools": ["count_ips"],
                     "invented_filters": ["naturaleza=Mixta"] * (1 if i < invented else 0), "wrong_args": [],
                     "unneeded_call": False, "correct": correct or i != 0})
    return runs


def summ(*groups):
    return sa.summarize([r for g in groups for r in g])


def test_rule_b_lowest_median_among_passing():
    s = summ(mk("A", "semantic_vad", 1500), mk("B", "semantic_vad", 1100), mk("C", "semantic_vad", 900, invented=2))
    d = sa.decide(s)
    assert (d["rule"], d["model"]) == ("b", "B")          # C tiene filtros inventados: descartado


def test_rule_a_discards_below_98_percent():
    s = summ(mk("A", "x", 800, correct=False), mk("B", "x", 1400))
    assert sa.decide(s)["model"] == "B"


def test_p95_over_limit_is_excluded():
    slow = mk("A", "x", 900)
    slow[0]["perceived_ms"] = 6000
    slow[1]["perceived_ms"] = 6000
    assert sa.decide(summ(slow, mk("B", "x", 1300)))["model"] == "B"


def test_rule_c_tie_under_150ms_picks_most_precise():
    a, b = mk("A", "x", 1000), mk("B", "x", 1100)
    for r in a:
        r["wrong_args"] = ["departamento=Cauca"]      # A es menos preciso (mismo % de cifras)
    d = sa.decide(summ(a, b))
    assert (d["rule"], d["model"]) == ("c", "B")


def test_rule_d_when_none_passes_needs_filter_guard():
    s = summ(mk("A", "x", 900, invented=3), mk("B", "x", 1000, invented=1))
    d = sa.decide(s)
    assert d["rule"] == "d" and d["needs_filter_guard"] and d["model"] == "B"


def test_table_mentions_every_group():
    s = summ(mk("A", "semantic_vad", 1000), mk("A", "server_vad", 1500, filler=True))
    t = sa.format_table(s)
    assert "semantic_vad" in t and "server_vad" in t and "20 (100.0%)" in t


# --- corrida con WebSocket falso ----------------------------------------------------
class FakeRealtime:
    """Simula: tras recibir el audio de la pregunta emite speech_stopped, llama a una tool y responde."""

    def __init__(self, answer):
        self.q, self.frames, self.stage, self.answer = asyncio.Queue(), 0, "listen", answer

    async def send(self, raw):
        m = json.loads(raw)
        if m["type"] == "input_audio_buffer.append":
            self.frames += 1
            if self.stage == "listen" and self.frames == 20:      # 300 ms de silencio inicial + 12 frames de voz
                self.stage = "called"
                await self.q.put({"type": "input_audio_buffer.speech_stopped"})
                await self.q.put({"type": "response.done", "response": {"status": "completed", "output": [
                    {"type": "function_call", "name": "count_ips", "call_id": "c1", "arguments": "{}"}]}})
        elif m["type"] == "response.create" and self.stage == "called":
            self.stage = "done"
            await self.q.put({"type": "response.output_audio.delta", "delta": base64.b64encode(b"\0" * 4800).decode()})
            await self.q.put({"type": "response.output_audio_transcript.done", "transcript": self.answer})
            await self.q.put({"type": "response.done", "response": {"status": "completed", "output": []}})

    async def recv(self):
        return json.dumps(await self.q.get())

    async def close(self):
        pass


async def test_run_one_measures_tool_flow(store, monkeypatch):
    fake = FakeRealtime("Hay nueve mil trescientos veinte IPS en total.")

    async def fake_open(model, key, cfg):
        assert cfg["session"]["audio"]["input"]["transcription"] == {"model": "gpt-live-transcribe"}
        return fake, None

    monkeypatch.setattr(sa, "open_session", fake_open)
    pcm = _pcm([8000] * (24000 * 12 * 40 // 1000))                     # 12 frames de voz
    tools = AgentTools(store)
    run = await sa.run_one("m", "server_vad", G["4.1"], 0, pcm, "sk-fake", tools, store.cursor())
    assert "error" not in run, run
    assert run["tools"] == ["count_ips"] and run["correct"] is True and run["filler"] is False
    assert run["perceived_ms"] == run["vad_silence_ms"] + run["first_audio_ms"]
    assert run["answer_ms"] is not None and run["invented_filters"] == [] and not run["unneeded_call"]
    assert "sk-fake" not in json.dumps(run)


async def test_run_one_reports_connection_errors(store, monkeypatch):
    async def boom(*a):
        raise OSError("sin red")

    monkeypatch.setattr(sa, "open_session", boom)
    run = await sa.run_one("m", "server_vad", G["4.1"], 0, b"\0" * 1920, "sk-fake", AgentTools(store), store.cursor())
    assert run["error"].startswith("conexión")
