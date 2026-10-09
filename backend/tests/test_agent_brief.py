import re
from pathlib import Path

import pytest

from app.agent.brief import (BriefCache, SPOKEN_MAX_SECONDS, build_brief, estimate_spoken_seconds,
                             format_date, format_int, validate_suggested)
from app.agent.instructions import INSTRUCTIONS, INSTRUCTIONS_MAX_CHARS
from app.agent.tools import AgentTools
from app.config import load_settings
from app.datastore.loader import load_snapshot
from app.datastore.store import Store
from tests.conftest import raw_row

REAL_DATA = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(scope="module")
def store():
    s = Store()
    assert load_snapshot(s, load_settings({"DATA_PATH": str(REAL_DATA)}))
    return s


@pytest.fixture(scope="module")
def tools(store):
    return AgentTools(store)


# 2.3 instrucciones -----------------------------------------------------------
def test_instructions_have_no_dataset_figures():
    # la única cifra permitida es la línea de emergencias 123
    assert not re.search(r"\d", INSTRUCTIONS.replace("123", ""))
    for fig in ("9320", "9.320", "15547", "41427", "2022"):
        assert fig not in INSTRUCTIONS


def test_instructions_within_budget_and_cover_rules():
    assert len(INSTRUCTIONS) <= INSTRUCTIONS_MAX_CHARS
    text = INSTRUCTIONS.lower()
    for needle in ("solo con resultados de tus herramientas", "no_encontrado", "sin_cobertura",
                   "count_ips", "count_sedes", "fecha de corte", "dos o tres oraciones", "correo",
                   "incluye_distritos", "fuera de la fuente", "lumi", "listar_ips", "123",
                   "de dos en dos o de tres en tres", "vía principal y el barrio", "usa siempre municipio",
                   "antes de cualquier dato", "buscar_ips"):
        assert needle in text.replace("de una a tres", "una a tres"), needle


# 3.1 -------------------------------------------------------------------------
def test_brief_content(store, tools):
    b = build_brief(store, tools)
    t = b["texto"]
    assert "9.320 IPS" in t and "15.547 sedes" in t
    assert "5 de noviembre de 2022" in t
    assert "públicas y privadas" in t
    assert "prestadores distintos" in t
    assert "nivel de atención casi solo existe para las públicas" in t
    assert b["origen"] == "snapshot" and b["fecha_corte"] == "2022-11-05"


def test_brief_does_not_claim_data_is_current(store, tools):
    t = build_brief(store, tools)["texto"].lower()
    assert "actual" not in t and "tiempo real" not in t and "corte al" in t


def test_brief_declares_coverage_only_if_profile_supports_it():
    s = Store()
    s.replace_from_rows([raw_row(0), raw_row(1, naturaleza="Privada")], 2, "snapshot")
    t = build_brief(s, AgentTools(s))["texto"]
    assert "casi solo existe" not in t  # aquí hay 1 pública y 1 privada con nivel


# 3.2 -------------------------------------------------------------------------
def test_between_3_and_5_questions_all_resolvable(store, tools):
    b = build_brief(store, tools)
    assert 3 <= len(b["preguntas"]) <= 5
    for pregunta, calls, estado in validate_suggested(tools):
        assert 1 <= calls <= 2 and estado == "ok", pregunta


def test_questions_avoid_out_of_source_and_private_levels(store, tools):
    for q in build_brief(store, tools)["preguntas"]:
        low = q.lower()
        assert not ("privad" in low and "nivel" in low)
        for bad in ("calidad", "tarifa", "médicos", "calificaci", "mejor"):
            assert bad not in low


def test_unresolvable_candidates_are_dropped():
    s = Store()
    s.replace_from_rows([raw_row(i, departamento="Cauca", municipio="Popayán") for i in range(3)], 3, "api")
    b = build_brief(s, AgentTools(s))
    assert "¿Cuántas IPS hay en Medellín?" not in b["preguntas"]
    assert "¿Cuántas camas de adultos hay en Antioquia?" not in b["preguntas"]
    assert len(b["preguntas"]) >= 2


# 3.4 -------------------------------------------------------------------------
def test_same_profile_same_brief(store, tools):
    assert build_brief(store, tools) == build_brief(store, tools)


def test_brief_rebuilt_after_refresh(rows):
    s = Store()
    s.replace_from_rows(rows[:5], 5, "snapshot")
    cache = BriefCache(s, AgentTools(s))
    first = cache.get()
    assert cache.get() is first                      # servido desde memoria
    s.replace_from_rows(rows, len(rows), "api")
    second = cache.get()
    assert second is not first and second["origen"] == "api"


# 3.5 -------------------------------------------------------------------------
def test_spoken_brief_is_20s_or_less(store, tools):
    t = build_brief(store, tools)["texto"]
    assert estimate_spoken_seconds(t) <= SPOKEN_MAX_SECONDS, estimate_spoken_seconds(t)


def test_formatters():
    assert format_int(15547) == "15.547" and format_date("2022-11-05") == "5 de noviembre de 2022"
