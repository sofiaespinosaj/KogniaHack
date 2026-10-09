"""Sentimiento y emoción por enunciado humano (sentiment-emotion)."""
import time

import jsonschema
import pytest

from app.sentiment.analyzer import EMOTIONS, SENTIMENTS, is_trivial, validate
from tests.test_cascade import CascadeFakes, make_client
from tests.test_relay import QUIET, SCHEMA, START, Live, collect, speak, state_is


def test_validate_normalizes_and_keeps_score_coherent():
    assert validate({"sentiment": "Neutral", "emotion": "curiosity", "score": 0.1}) == \
        {"sentiment": "neutro", "emotion": "curiosidad", "score": 0.1}
    assert validate({"sentiment": "positivo", "emotion": "alegria", "score": -0.5})["score"] > 0
    assert validate({"sentiment": "negativo", "emotion": "enojo", "score": 0.4})["score"] < 0
    assert validate({"sentiment": "neutro", "emotion": "interés", "score": 0.9})["score"] == 0.3
    assert validate({"sentiment": "negativo", "emotion": "frustración", "score": -7})["score"] == -1
    for bad in ({"sentiment": "feliz", "emotion": "alegría"}, {"sentiment": "positivo", "emotion": "amor"},
                {"sentiment": "neutro", "emotion": "interés", "score": "x"}, "texto"):
        with pytest.raises(ValueError):
            validate(bad)


def test_trivial_utterances():
    assert is_trivial("ajá") and is_trivial("ok") and is_trivial("eh, sí, bueno")
    for t in ("Gracias, Lumi", "Qué rabia", "No entiendo", "¿cuántas IPS hay en Manizales?"):
        assert not is_trivial(t), t


@pytest.fixture
def fakes():
    from app.sentiment.analyzer import SentimentAnalyzer
    SentimentAnalyzer._working = None
    f = CascadeFakes()
    yield f
    f.close()


def _turn(ws, text):
    ws.send_json({"type": "text.message", "v": 1, "text": text})
    return collect(ws, lambda m: m[-1]["type"] == "sentiment", limit=4000)[0]


def test_text_utterance_gets_sentiment_after_its_final(fakes):
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip", "audio_out": False})
        collect(ws, state_is("escuchando"))
        t0 = time.monotonic()
        msgs = _turn(ws, "Muchas gracias, eso me sirve muchísimo")
        final = next(m for m in msgs if m["type"] == "transcript.final")
        sent = msgs[-1]
        jsonschema.validate(sent, SCHEMA)
        assert msgs.index(final) < msgs.index(sent)                       # el final precede a su sentimiento
        assert (sent["turn_id"], sent["utt_id"], sent["speaker"]) == (final["turn_id"], final["utt_id"], "user")
        assert (sent["sentiment"], sent["emotion"]) == ("positivo", "alegría") and sent["score"] > 0
        assert time.monotonic() - t0 < 2.5
        call = fakes.http.sentiment_calls[0]
        assert call["model"] == "openai/gpt-oss-20b" and call["response_format"] == {"type": "json_object"}
        assert call["reasoning_effort"] == "low" and call["max_completion_tokens"] >= 300


def test_values_are_always_in_the_closed_lists_and_agent_is_not_analyzed(fakes):
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip", "audio_out": False})
        collect(ws, state_is("escuchando"))
        for q in ("¿Cuántas IPS hay en total?", "No entiendo nada, otra vez mal"):
            s = _turn(ws, q)[-1]
            assert s["sentiment"] in SENTIMENTS and s["emotion"] in EMOTIONS and -1 <= s["score"] <= 1
        assert s["sentiment"] == "negativo"
        assert len(fakes.http.sentiment_calls) == 2                       # solo los humanos
        assert "No entiendo nada" in fakes.http.sentiment_calls[1]["messages"][-1]["content"]
        assert "Cuántas IPS" in fakes.http.sentiment_calls[1]["messages"][-1]["content"]   # contexto previo


def test_short_utterance_is_neutral_without_calling_the_model(fakes):
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip", "audio_out": False})
        collect(ws, state_is("escuchando"))
        s = _turn(ws, "ok")[-1]
        assert (s["sentiment"], s["emotion"], s["score"]) == ("neutro", "neutralidad", 0.0)
        assert fakes.http.sentiment_calls == []


def test_voice_utterance_gets_sentiment_with_speaker_label(fakes):
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip", "audio_out": False})
        collect(ws, state_is("escuchando"))
        time.sleep(0.3)
        speak(ws)
        msgs, _ = collect(ws, lambda m: m[-1]["type"] == "sentiment", limit=4000)
        assert msgs[-1]["speaker"] == "speaker_1"


@pytest.mark.parametrize("setup", ["invalid_json", "slow"])
def test_failures_are_silent_and_voice_goes_on(fakes, setup):
    if setup == "invalid_json":
        fakes.http.sentiment_reply = "esto no es JSON"
    else:
        fakes.http.sentiment_delay = 3.5                                   # más que el tiempo máximo de 3 s
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip", "audio_out": False})
        collect(ws, state_is("escuchando"))
        ws.send_json({"type": "text.message", "v": 1, "text": "¿Cuántas IPS hay en Caldas?"})
        msgs, _ = collect(ws, lambda m: m[-1]["type"] == "metrics", limit=4000)
        assert not any(m["type"] in ("sentiment", "error") for m in msgs)
        time.sleep(3.2 if setup == "slow" else 0.3)
        ws.send_json({"type": "text.message", "v": 1, "text": "ok"})          # la sesión sigue viva
        late = collect(ws, lambda m: m[-1]["type"] == "sentiment", limit=4000)[0]
        assert [m for m in late if m["type"] == "sentiment"][0]["utt_id"] != msgs[0]["utt_id"]
        assert not any(m["type"] == "error" for m in late)


def test_disabled_by_env(fakes):
    with Live(make_client(fakes, SENTIMENT_ENABLED="false")) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip", "audio_out": False})
        collect(ws, state_is("escuchando"))
        ws.send_json({"type": "text.message", "v": 1, "text": "Muchas gracias por la ayuda de hoy"})
        msgs, _ = collect(ws, lambda m: m[-1]["type"] == "metrics", limit=4000)
        time.sleep(0.3)
        assert fakes.http.sentiment_calls == [] and not any(m["type"] == "sentiment" for m in msgs)


def test_hand_labeled_phrases_are_valid():
    import json
    from pathlib import Path
    items = json.loads((Path(__file__).parent / "sentiment" / "frases.json").read_text(encoding="utf-8"))
    assert len(items) == 10
    for it in items:
        assert it["sentiment"] in SENTIMENTS and it["emotion"] in EMOTIONS and it["texto"]


def test_sentiment_follows_the_conversation(fakes):
    """El ánimo cambia a lo largo de la conversación y cada frase recibe el suyo, con el contexto anterior."""
    with Live(make_client(fakes)) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip", "audio_out": False})
        collect(ws, state_is("escuchando"))
        seq = []
        for q in ("¿Cuántas IPS hay en Manizales?", "No entiendo, otra vez mal", "Gracias, Lumi"):
            seq.append(_turn(ws, q)[-1])
        assert [s["sentiment"] for s in seq] == ["neutro", "negativo", "positivo"]
        assert seq[1]["score"] < seq[0]["score"] < seq[2]["score"]
        assert len({s["utt_id"] for s in seq}) == 3
        last = fakes.http.sentiment_calls[-1]["messages"][-1]["content"]
        assert "No entiendo" in last and "Manizales" in last          # contexto de las dos frases anteriores


def test_retired_sentiment_model_falls_back(fakes):
    """Un .env antiguo con GROQ_SENTIMENT_MODEL=llama-3.1-8b-instant (retirado) sigue funcionando."""
    from app.sentiment.analyzer import SentimentAnalyzer
    SentimentAnalyzer._working = None
    fakes.http.retired_models = {"llama-3.1-8b-instant"}
    with Live(make_client(fakes, GROQ_SENTIMENT_MODEL="llama-3.1-8b-instant")) as c, c.websocket_connect("/ws") as ws:
        ws.send_json({**START, "brief": "skip", "audio_out": False})
        collect(ws, state_is("escuchando"))
        s = _turn(ws, "Muchas gracias, me ayudaste mucho")[-1]
        assert s["sentiment"] == "positivo"
        assert [c["model"] for c in fakes.http.sentiment_calls] == ["openai/gpt-oss-20b"]
    SentimentAnalyzer._working = None
