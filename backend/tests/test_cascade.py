"""Voz por etapas (VOICE_PROVIDER=groq): Deepgram STT + Groq + Deepgram TTS, todos simulados."""
import json
import time

import jsonschema
import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.main import create_app
from app.voice.cascade import chat_tools, is_echo, speakable, split_sentences
from scripts.fake_services import HttpState, serve_http
from tests.test_relay import (LOUD, QUIET, ROOT, SCHEMA, START, Fakes, Live, collect, free_port, speak,
                              state_is)


class CascadeFakes(Fakes):
    def __init__(self) -> None:
        super().__init__()
        self.http = HttpState()
        self.http_port = free_port()
        self.http_server, _ = self.call(serve_http(self.http, "127.0.0.1", self.http_port))

    def close(self) -> None:
        self.http_server.should_exit = True
        time.sleep(0.2)
        super().close()


@pytest.fixture
def fakes():
    f = CascadeFakes()
    yield f
    f.close()


def make_client(f: CascadeFakes, **extra) -> TestClient:
    env = {"DATA_PATH": str(ROOT / "data"), "VOICE_ENABLED": "true", "GROQ_API_KEY": "gsk-test-secret",
           "DEEPGRAM_API_KEY": "dg-test-secret", "DEEPGRAM_URL": f"ws://127.0.0.1:{f.dg_port}",
           "GROQ_BASE_URL": f"http://127.0.0.1:{f.http_port}/openai/v1",
           "DEEPGRAM_TTS_URL": f"http://127.0.0.1:{f.http_port}/v1/speak", **extra}
    return TestClient(create_app(load_settings(env)))


def test_helpers():
    sents, rest = split_sentences("Hola. ¿Cuántas IPS hay? Hay muchas")
    assert sents == ["Hola.", "¿Cuántas IPS hay?"] and rest == " Hay muchas" or rest == "Hay muchas"
    assert speakable("**Antioquia** tiene\n- 840 IPS") == "Antioquia tiene 840 IPS"
    assert is_echo("hay nueve mil IPS", "Según el dataset hay nueve mil IPS en total")
    assert not is_echo("espera, otra pregunta", "Según el dataset hay nueve mil IPS")
    t = chat_tools([{"type": "function", "name": "count_ips", "description": "d", "parameters": {"type": "object"}}])
    assert t == [{"type": "function", "function": {"name": "count_ips", "description": "d",
                                                    "parameters": {"type": "object"}}}]


def test_brief_is_spoken_with_aura_in_spanish(fakes):
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        assert c.get("/health").json()["voice_provider"] == "groq"
        ws.send_json(START)
        msgs, frames = collect(ws, state_is("escuchando"))
        brief = next(m for m in msgs if m["type"] == "session.brief")
        final = [m for m in msgs if m["type"] == "agent.text" and m["final"]][-1]
        assert final["turn_id"] == "t-0000" and final["text"] == brief["texto"]
        assert frames and all(len(f) == 1920 for f in frames)
        params = fakes.http.speak_params[0]
        assert params["model"] == "aura-2-celeste-es" and params["encoding"] == "linear16"
        assert params["sample_rate"] == "24000" and params["container"] == "none"
        for m in msgs:
            jsonschema.validate(m, SCHEMA)


def test_text_turn_with_tool_on_groq(fakes):
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        collect(ws, state_is("escuchando"))
        ws.send_json({"type": "text.message", "v": 1, "text": "¿Cuántas IPS hay en Antioquia?"})
        msgs, frames = collect(ws, lambda m: m[-1]["type"] == "metrics")
        for m in msgs:
            jsonschema.validate(m, SCHEMA)
        tools = [m for m in msgs if m["type"] == "agent.tool"]
        assert [t["status"] for t in tools] == ["running", "done"]
        assert tools[1]["args"] == {"departamento": "Antioquia"}
        valor = tools[1]["summary"]["valor"]
        final = next(m for m in msgs if m["type"] == "agent.text" and m["final"])
        assert str(valor) in final["text"]
        assert frames and msgs[-1]["first_audio_ms"] is not None and msgs[-1]["tool_ms"] is not None
        states = [m["state"] for m in msgs if m["type"] == "session.state"]
        assert states[:2] == ["pensando", "hablando"]
        chat = fakes.http.chats[0]
        assert chat["model"] == "openai/gpt-oss-120b" and chat["stream"] and chat["reasoning_effort"] == "low"
        assert chat["messages"][0]["role"] == "system" and "IPS" in chat["messages"][0]["content"]
        assert {t["function"]["name"] for t in chat["tools"]} >= {"count_ips", "sum_capacidad"}
        second = fakes.http.chats[1]["messages"]
        assert second[-1]["role"] == "tool" and json.loads(second[-1]["content"])["valor"] == valor
        assert "gsk-test-secret" not in json.dumps(msgs) and "SELECT" not in json.dumps(msgs)


def test_voice_turn_ends_on_deepgram_speech_final(fakes):
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        collect(ws, state_is("escuchando"))
        time.sleep(0.3)
        speak(ws)
        msgs, _ = collect(ws, lambda m: m[-1]["type"] == "metrics")
        final = next(m for m in msgs if m["type"] == "transcript.final")
        assert final["speaker"] == "speaker_1" and final["source"] == "deepgram" and final["turn_id"] == "t-0001"
        assert msgs[-1]["turn_id"] == "t-0001" and msgs[-1]["vad_silence_ms"] == 400
        assert fakes.http.chats[0]["messages"][-1] == {"role": "user", "content": final["text"]}
        assert "utterance_end_ms=1000" in fakes.deepgram.state.paths[0]


def test_user_speech_interrupts_agent_while_speaking(fakes):
    fakes.http.chunk_delay = 0.15                          # voz lenta: el agente sigue hablando
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        collect(ws, state_is("escuchando"))
        time.sleep(0.3)
        ws.send_json({"type": "text.message", "v": 1, "text": "¿Cuántas IPS hay en total?"})
        collect(ws, lambda m: m[-1]["type"] == "audio.start")
        speak(ws, loud_frames=8, quiet_frames=0)          # el usuario empieza a hablar encima
        msgs, _ = collect(ws, lambda m: m[-1]["type"] == "audio.clear")
        rest, _ = collect(ws, lambda m: m[-1]["type"] == "metrics")
        allm = msgs + rest
        stop = next(m for m in allm if m["type"] == "agent.text" and m["final"])
        assert stop["interrupted"] and stop["turn_id"] == "t-0001"
        assert next(m for m in allm if m["type"] == "metrics")["interrupted"]
        # el turno nuevo del usuario se responde normalmente
        for _ in range(10):
            ws.send_bytes(QUIET)
        msgs, _ = collect(ws, lambda m: m[-1]["type"] == "metrics" and not m[-1].get("interrupted"))
        assert msgs[-1]["turn_id"] == "t-0002"


def test_user_speech_interrupts_finished_turn_still_playing(fakes):
    fakes.http.ms_per_char = 400                           # mucho audio generado al instante
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        collect(ws, state_is("escuchando"))
        time.sleep(0.3)
        ws.send_json({"type": "text.message", "v": 1, "text": "¿Cuántas IPS hay en total?"})
        collect(ws, lambda m: m[-1]["type"] == "metrics", limit=5000)
        ws.send_json({"type": "playback.position", "v": 1, "turn_id": "t-0001", "played_ms": 800})
        speak(ws, loud_frames=8, quiet_frames=0)
        msgs, _ = collect(ws, lambda m: m[-1]["type"] == "audio.clear")
        assert msgs[-1]["turn_id"] == "t-0001"
        msgs, _ = collect(ws, lambda m: m[-1]["type"] == "agent.text")
        assert msgs[-1]["interrupted"] and msgs[-1]["final"]


def test_audio_out_false_answers_with_text(fakes):
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip", "audio_out": False})
        collect(ws, state_is("escuchando"))
        ws.send_json({"type": "text.message", "v": 1, "text": "¿Cuántas IPS hay en total?"})
        msgs, frames = collect(ws, lambda m: m[-1]["type"] == "metrics")
        assert frames == [] and fakes.http.speak_texts == []
        assert next(m for m in msgs if m["type"] == "agent.text" and m["final"])["text"]


def test_invalid_groq_key_fails_start_with_clear_log(fakes, caplog):
    fakes.http.groq_status = 401
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json(START)
        msgs, _ = collect(ws, state_is("error"))
        assert any(m.get("code") == "openai_unavailable" for m in msgs)
    assert "clave de Groq inválida" in caplog.text and "gsk-test-secret" not in caplog.text


def test_echo_of_agent_does_not_interrupt():
    from app.voice.cascade import is_echo as echo
    assert echo("según el dataset hay", "Según el dataset hay 9320 IPS con esos filtros.")


def test_filler_is_spoken_while_tools_run(fakes):
    from app.voice.cascade import FILLERS
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        collect(ws, state_is("escuchando"))
        ws.send_json({"type": "text.message", "v": 1, "text": "¿Cuántas IPS hay en total?"})
        msgs, _ = collect(ws, lambda m: m[-1]["type"] == "metrics")
        assert fakes.http.speak_texts[0] in FILLERS
        texts = [m["text"] for m in msgs if m["type"] == "agent.text"]
        assert texts[0] in FILLERS and texts[-1].startswith(texts[0])


def test_first_chunk_is_cut_early_at_a_comma():
    sents, rest = split_sentences("En Manizales hay varias opciones con camas y ambulancias, por ejemplo el Hospital",
                                  first=True)
    assert sents == ["En Manizales hay varias opciones con camas y ambulancias,"] and rest.strip().startswith("por")
    assert split_sentences("corta, sin punto", first=True) == ([], "corta, sin punto")


def _ask(fakes, text="¿Cuántas IPS hay en total?"):
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip"})
        collect(ws, state_is("escuchando"))
        ws.send_json({"type": "text.message", "v": 1, "text": text})
        msgs, _ = collect(ws, lambda m: m[-1]["type"] == "metrics", limit=3000)
        return next(m for m in msgs if m["type"] == "agent.text" and m["final"])["text"], msgs


def test_rate_limit_with_short_retry_after_waits_and_retries(fakes):
    fakes.http.chat_failures = [(429, 0.2, None)]
    text, msgs = _ask(fakes)
    assert "9320" in text and [c["model"] for c in fakes.http.chats][:2] == ["openai/gpt-oss-120b"] * 2


def test_rate_limit_without_quota_uses_fallback_model(fakes):
    fakes.http.chat_failures = [(429, 30, "openai/gpt-oss-120b"), (429, 30, "openai/gpt-oss-120b")]
    text, msgs = _ask(fakes)
    assert "9320" in text
    models = [c["model"] for c in fakes.http.chats]
    assert models[0] == "openai/gpt-oss-120b" and "llama-3.3-70b-versatile" in models
    assert "reasoning_effort" not in next(c for c in fakes.http.chats if c["model"].startswith("llama"))


def test_rejected_tool_call_is_retried(fakes):
    fakes.http.chat_failures = [(400, None, None)]
    text, _ = _ask(fakes)
    assert "9320" in text


def test_no_quota_anywhere_says_so_honestly(fakes):
    from app.voice.cascade import BUSY_TEXT
    fakes.http.chat_failures = [(429, 30, None)] * 4
    text, _ = _ask(fakes)
    assert text == BUSY_TEXT


def test_llm_tools_are_compact():
    from app.voice.cascade import chat_tools
    schemas = [{"type": "function", "name": "count_ips", "description": "d", "parameters": {
        "type": "object", "properties": {"departamento": {"type": "string", "enum": ["Antioquia"] * 33}}}},
        {"type": "function", "name": "group_by", "description": "d", "parameters": {"type": "object"}}]
    t = chat_tools(schemas)
    assert [x["function"]["name"] for x in t] == ["count_ips"]
    assert "enum" not in t[0]["function"]["parameters"]["properties"]["departamento"]
