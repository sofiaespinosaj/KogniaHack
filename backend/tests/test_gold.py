import json
from pathlib import Path

import httpx
import pytest

from app.agent import gold
from app.agent.gold import (GOLD, P95_GOAL_MS, format_table, measure_timing, number_matches,
                            parse_numbers, run_tools, ungrounded_numbers)
from app.agent.text_agent import TextAgent, check_answer
from app.config import load_settings
from app.datastore.loader import load_snapshot
from app.datastore.store import Store

REAL_DATA = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(scope="module")
def store():
    s = Store()
    assert load_snapshot(s, load_settings({"DATA_PATH": str(REAL_DATA)}))
    return s


@pytest.fixture(scope="module")
def rows(store):
    return run_tools(store)


def test_all_gold_questions_match_sql(rows):
    failed = [(r.gold.id, r.expected, r.obtained) for r in rows if not r.ok]
    assert not failed, failed
    assert len(rows) >= 12


def test_sql_matches_values_written_in_tasks(rows):
    exp = {r.gold.id: r.expected for r in rows}
    assert exp["4.1"] == 9320 and exp["4.3"] == 15547 and exp["4.5"] == 517 and exp["4.6"] == 6438
    assert exp["4.2"] == {"Pública": 998, "Privada": 8308, "Mixta": 14}
    assert exp["4.4"] == ("Bogotá D.C", 1270)
    assert exp["4.7"] == (29, 29)
    assert exp["4.7b"] == (813, ["Buenaventura", "Cali"])
    assert exp["4.7c"][0] == 45262
    assert exp["4.8"] == ("sin_cobertura", 1)


def test_honesty_cases_never_return_a_number(rows):
    by_id = {r.gold.id: r for r in rows}
    for gid in ("4.11", "4.12b"):
        assert by_id[gid].results[0]["estado"] == "no_encontrado" and "valor" not in by_id[gid].results[0]
    assert by_id["4.8"].results[0]["valor"] == 1   # observado, no cero
    assert by_id["4.12"].results[0]["estado"] == "ambiguo"


def test_table_lists_every_question(rows):
    table = format_table(rows)
    for g in GOLD:
        assert g.id in table
    assert f"{len(rows)}/{len(rows)} coinciden" in table


# 2.4 -------------------------------------------------------------------------
def test_tool_p95_within_200ms(store):
    res = measure_timing(store, 20)
    assert set(res) == {"count_ips", "count_sedes", "sum_capacidad", "top_n", "group_by", "buscar_ips"}
    assert all(ms <= P95_GOAL_MS for ms in res.values()), res


# números ---------------------------------------------------------------------
@pytest.mark.parametrize("text,expected,ok", [
    ("Hay unas 45 mil camas", 45262, True),
    ("Hay 45.262 camas", 45262, True),
    ("Hay 45262 camas", 45262, True),
    ("Hay 9.320 IPS", 9320, True),
    ("Hay 9.400 IPS", 9320, False),
    ("Hay 1,3 mil IPS", 1270, True),
    ("Hay 1,4 mil IPS", 1270, False),
    ("Son 813", 813, True),
    ("Son 814", 813, False),
])
def test_number_matching_respects_spoken_rounding(text, expected, ok):
    assert number_matches(text, expected) is ok


def test_parse_numbers_units():
    assert parse_numbers("2,5 millones") == [(2_500_000.0, 100_000.0)]


def test_ungrounded_numbers_detected():
    results = [{"estado": "ok", "valor": 9320, "fecha_corte": "2022-11-05"}]
    assert ungrounded_numbers("Hay 9.320 IPS, corte al 5 de noviembre de 2022.", results) == []
    assert ungrounded_numbers("Hay 9.999 IPS.", results) == [9999.0]
    assert ungrounded_numbers("Unas 9 mil IPS.", results) == []


# 4.13 agente en texto (transporte simulado, sin red ni claves reales) ------------
def _agent(store, replies):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": replies[len(seen) - 1]}]})

    return TextAgent(store, api_key="sk-test-secret", model="m", transport=httpx.MockTransport(handler)), seen


def test_text_agent_runs_tool_loop_and_grounds_answer(store):
    call = {"role": "assistant", "content": None, "tool_calls": [
        {"id": "c1", "type": "function", "function": {"name": "count_ips", "arguments": "{}"}}]}
    final = {"role": "assistant", "content": "Según el dataset hay 9.320 IPS, con corte al 5 de noviembre de 2022."}
    agent, seen = _agent(store, [call, final])
    text, results = agent.ask("¿Cuántas IPS hay en total?")
    assert results[0]["valor"] == 9320 and "9.320" in text
    second = json.loads(seen[1].content)["messages"]
    assert second[-1]["role"] == "tool" and json.loads(second[-1]["content"])["valor"] == 9320
    assert second[0]["role"] == "system" and "sk-test-secret" not in json.dumps(second)
    g = GOLD[0]
    assert check_answer(g, 9320, text, results) == (True, "ok")


def test_check_answer_flags_invented_figures_and_zero_answers(store):
    results = [{"estado": "no_encontrado"}]
    ok, why = check_answer(GOLD[0], 9320, "Hay 9.999 IPS", [{"valor": 9320}])
    assert not ok and "sin respaldo" in why
    springfield = next(g for g in GOLD if g.id == "4.11")
    assert check_answer(springfield, None, "No encuentro ese lugar; ¿te refieres a otro?", results)[0]
    assert not check_answer(springfield, None, "No hay ninguna, son 0 IPS.", results)[0]


def test_agent_mode_requires_env_vars(store, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("GOLD_AGENT_MODEL", raising=False)
    from app.agent.text_agent import run_agent_eval

    assert run_agent_eval(store) == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err


@pytest.mark.parametrize("text,expected,ok", [
    ("hay alrededor de 9,320 IPS", 9320, True),          # miles con coma (estilo inglés)
    ("hay alrededor de 6,440 camas", 6438, True),        # ceros finales = redondeo
    ("hay alrededor de 6,400 camas", 6438, True),
    ("hay alrededor de 6,500 camas", 6438, False),
    ("aproximadamente 500 camas", 6438, False),
    ("Hay 9.400 IPS", 9320, False),
    ("Son 814", 813, False),
])
def test_number_formats_and_trailing_zero_rounding(text, expected, ok):
    assert number_matches(text, expected) is ok
