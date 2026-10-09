import json
from pathlib import Path

import pytest

from app.agent.tools import MAX_ITEMS, AgentTools, ToolSession
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


def no_empty(obj):
    """Ningún campo vacío (salvo valor/filas_usadas)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in ("valor", "filas_usadas"):
                assert v not in (None, "", [], {}), f"campo vacío: {k}"
            no_empty(v)
    elif isinstance(obj, list):
        for v in obj:
            no_empty(v)


# 1.1 / 1.2 -----------------------------------------------------------------
def test_exactly_seven_tools(tools):
    assert [t["name"] for t in tools.schemas()] == \
        ["count_ips", "count_sedes", "sum_capacidad", "top_n", "group_by", "listar_ips", "buscar_ips"]


def test_listar_ips_in_manizales(tools):
    r = tools.call("listar_ips", {"municipio": "Manizales"})
    sedes = tools.call("count_sedes", {"municipio": "Manizales"})["valor"]
    assert r["estado"] == "ok" and r["total_sedes"] == sedes and len(r["valor"]) == 5
    first = r["valor"][0]
    assert first["camas"] >= r["valor"][1]["camas"] and first["direccion"] and first["telefono"]
    assert first["municipio"].lower() == "manizales"


def test_listar_ips_by_capacity_group_and_limit(tools):
    r = tools.call("listar_ips", {"municipio": "manizales", "grupo_capacidad": "AMBULANCIAS", "n": 3})
    assert r["estado"] == "ok" and len(r["valor"]) == 3 and all(x["ambulancias"] > 0 for x in r["valor"])
    assert r["filtros"]["grupo_capacidad"] == "AMBULANCIAS"


def test_listar_ips_unknown_place_and_limits(tools):
    r = tools.call("listar_ips", {"municipio": "Manisales"})
    assert r["estado"] == "no_encontrado" and "manizales" in [x.lower() for x in r["sugerencias"]]
    assert tools.call("listar_ips", {"municipio": "Manizales", "n": 50})["estado"] == "error_validacion"
    r = tools.call("listar_ips", {"departamento": "Caldas", "grupo_capacidad": "CAMAS", "n": 10})
    assert len(r["valor"]) == 10 and "SELECT" not in str(r)


def test_enums_come_from_profile(tools):
    props = {t["name"]: t["parameters"]["properties"] for t in tools.schemas()}["count_ips"]
    assert len(props["departamento"]["enum"]) == 33 and "Valle del Cauca" in props["departamento"]["enum"]
    assert "Cali" not in props["departamento"]["enum"]
    assert set(props["naturaleza"]["enum"]) == {"Pública", "Privada", "Mixta"}
    assert props["nivel_atencion"]["enum"] == [1, 2, 3]
    grupos = next(t for t in tools.schemas() if t["name"] == "sum_capacidad")["parameters"]["properties"]
    assert len(grupos["grupo_capacidad"]["enum"]) == 7


def test_enums_change_when_profile_changes():
    s = Store()
    s.replace_from_rows([raw_row(i) for i in range(3)], 3, "snapshot")
    t = AgentTools(s)
    enum1 = t.schemas()[0]["parameters"]["properties"]["departamento"]["enum"]
    s.replace_from_rows([raw_row(0, departamento="Cauca"), raw_row(1, departamento="Huila")], 2, "api")
    enum2 = t.schemas()[0]["parameters"]["properties"]["departamento"]["enum"]
    assert enum1 == ["Antioquia"] and enum2 == ["Cauca", "Huila"]


# 1.3 -----------------------------------------------------------------------
def test_count_ips_counts_providers_not_rows(tools):
    r = tools.call("count_ips", {})
    assert r["valor"] == 9320 and r["filas_usadas"] == 41427 and r["estado"] == "ok"
    assert r["fecha_corte"] == "2022-11-05" and r["origen"] == "snapshot"


def test_count_sedes(tools):
    assert tools.call("count_sedes", {})["valor"] == 15547


def test_sum_capacidad_adultos_antioquia(tools):
    r = tools.call("sum_capacidad", {"grupo_capacidad": "CAMAS", "descripcion_capacidad": "Adultos",
                                     "departamento": "Antioquia"})
    assert r["valor"] == 6438 and r["estado"] == "ok"


def test_filters_combine(tools):
    r = tools.call("count_ips", {"naturaleza": "Pública", "nivel_atencion": 3})
    assert r["valor"] == 29 and r["estado"] == "ok"


# 1.4 -----------------------------------------------------------------------
def test_top_n_departamentos(tools):
    r = tools.call("top_n", {"dimension": "departamento", "metrica": "ips", "n": 3})
    assert [(i["nombre"], i["valor"]) for i in r["valor"]] == \
        [("Bogotá D.C", 1270), ("Antioquia", 837), ("Valle del Cauca", 813)]
    assert "acotado" not in r


def test_top_n_caps_at_10_and_flags(tools):
    r = tools.call("top_n", {"dimension": "municipio", "metrica": "ips", "n": 50})
    assert len(r["valor"]) == MAX_ITEMS and r["acotado"] is True
    vals = [i["valor"] for i in r["valor"]]
    assert vals == sorted(vals, reverse=True)


def test_group_by_naturaleza_and_capacidad(tools):
    r = tools.call("group_by", {"dimension": "naturaleza", "metrica": "ips"})
    assert {i["nombre"]: i["valor"] for i in r["valor"]} == {"Privada": 8308, "Pública": 998, "Mixta": 14}
    r = tools.call("group_by", {"dimension": "departamento", "metrica": "capacidad", "grupo_capacidad": "CAMAS"})
    assert len(r["valor"]) == MAX_ITEMS and r["acotado"] is True


def test_group_by_nivel_excludes_unregistered(tools):
    r = tools.call("group_by", {"dimension": "nivel_atencion", "metrica": "ips"})
    assert {i["nombre"]: i["valor"] for i in r["valor"]} == {"nivel 1": 853, "nivel 2": 113, "nivel 3": 29}
    assert "nota" in r


def test_capacidad_requires_group(tools):
    r = tools.call("top_n", {"dimension": "departamento", "metrica": "capacidad"})
    assert r["estado"] == "error_validacion"


# 1.5 -----------------------------------------------------------------------
def test_buscar_case_and_accent_insensitive(tools):
    r = tools.call("buscar_ips", {"nombre": "CLINICA SANTA MARIA SAS"})
    assert r["estado"] == "ok" and r["valor"][0]["nombre"] == "CLINICA SANTA MARIA SAS"
    assert {"naturaleza", "departamento", "municipio"} <= r["valor"][0].keys()
    r2 = tools.call("buscar_ips", {"nombre": "clínica santa maría sas"})
    assert r2["valor"] == r["valor"]


def test_buscar_ambiguous_lists_candidates(tools):
    r = tools.call("buscar_ips", {"nombre": "CLINICA SANTA MARIA"})
    assert r["estado"] == "ambiguo" and 1 < len(r["candidatos"]) <= MAX_ITEMS
    assert "CLINICA SANTA MARIA SAS" in [c["nombre"] for c in r["candidatos"]]
    assert "valor" not in r


def test_buscar_no_match_no_invention(tools):
    r = tools.call("buscar_ips", {"nombre": "zzqxv inexistente"})
    assert r["estado"] == "sin_resultados" and r["valor"] == []


# 1.6 -----------------------------------------------------------------------
def test_results_are_compact_without_contacts(tools):
    calls = [("count_ips", {"departamento": "Antioquia"}), ("buscar_ips", {"nombre": "CLINICA SANTA MARIA"}),
             ("top_n", {"dimension": "naturaleza", "metrica": "sedes"}),
             ("count_ips", {"municipio": "Springfield"})]
    for name, args in calls:
        r = tools.call(name, args)
        no_empty(r)
        text = json.dumps(r, ensure_ascii=False)
        for bad in ("@", "telefono", "gerente", "email", "direccion"):
            assert bad not in text


# 1.7a ----------------------------------------------------------------------
def test_valle_incluye_distritos(tools):
    r = tools.call("count_ips", {"departamento": "Valle del Cauca"})
    assert r["valor"] == 813 and r["incluye_distritos"] == ["Buenaventura", "Cali"]


def test_antioquia_sin_distritos(tools):
    assert "incluye_distritos" not in tools.call("count_ips", {"departamento": "Antioquia"})


def test_bogota_sin_mapeo(tools):
    r = tools.call("count_ips", {"departamento": "Bogotá D.C"})
    assert r["valor"] == 1270 and "incluye_distritos" not in r


# 1.7b ----------------------------------------------------------------------
def test_descripcion_exacta_no_incluye_intensiva(tools):
    r = tools.call("sum_capacidad", {"grupo_capacidad": "CAMAS", "descripcion_capacidad": "adultos"})
    assert r["valor"] == 45262 and r["filtros"]["descripcion_capacidad"] == "Adultos"


def test_descripcion_coloquial_resuelve(tools):
    r = tools.call("sum_capacidad", {"grupo_capacidad": "CAMAS", "descripcion_capacidad": "camas para adultos"})
    assert r["valor"] == 45262


def test_descripcion_cuidado_intensivo_adulto_exacta(tools):
    r = tools.call("sum_capacidad", {"grupo_capacidad": "CAMAS", "descripcion_capacidad": "cuidado intensivo adulto"})
    assert r["estado"] == "ok" and r["valor"] == 1001


def test_descripcion_ambigua_lista_candidatos(tools):
    r = tools.call("sum_capacidad", {"grupo_capacidad": "CAMAS", "descripcion_capacidad": "cuidado intensivo"})
    assert r["estado"] == "ambiguo" and "valor" not in r
    assert {"Cuidado Intensivo Adulto", "Cuidado Intensivo Neonatal"} <= set(r["candidatos"])


def test_descripcion_inexistente(tools):
    r = tools.call("sum_capacidad", {"grupo_capacidad": "CAMAS",
                                     "descripcion_capacidad": "camas para extraterrestres"})
    assert r["estado"] == "no_encontrado" and "valor" not in r and 1 <= len(r["sugerencias"]) <= 3


# 1.7 -----------------------------------------------------------------------
def test_municipio_inexistente_no_cero(tools):
    r = tools.call("count_ips", {"municipio": "Springfield"})
    assert r["estado"] == "no_encontrado" and "valor" not in r and len(r.get("sugerencias", [])) <= 3


def test_municipio_con_typo_sugiere(tools):
    r = tools.call("count_ips", {"municipio": "Medelin"})
    assert r["estado"] == "no_encontrado" and "valor" not in r
    assert any("medell" in s.lower() or "medell" in s.lower().replace("í", "i") for s in r["sugerencias"])


def test_municipio_sin_tildes(tools):
    assert tools.call("count_ips", {"municipio": "medellin"})["valor"] == 517
    assert tools.call("count_ips", {"municipio": "MEDELLÍN"})["valor"] == 517


def test_lugar_existente_sin_resultados_es_cero(tools):
    r = tools.call("count_ips", {"municipio": "Medellín", "departamento": "Cauca"})
    assert r["estado"] == "sin_resultados" and r["valor"] == 0 and "filtros" in r


# 1.8 -----------------------------------------------------------------------
def test_sin_cobertura_privada_nivel_1(tools):
    r = tools.call("count_ips", {"naturaleza": "Privada", "nivel_atencion": 1})
    assert r["estado"] == "sin_cobertura" and r["valor"] == 1 and "casi solo" in r["nota"]


def test_sin_cobertura_aunque_sea_cero(tools):
    r = tools.call("count_ips", {"naturaleza": "Privada", "nivel_atencion": 2})
    assert r["estado"] == "sin_cobertura" and r["valor"] == 0


def test_mixta_sin_cobertura(tools):
    assert tools.call("count_ips", {"naturaleza": "Mixta", "nivel_atencion": 2})["estado"] == "sin_cobertura"


# 1.9 -----------------------------------------------------------------------
@pytest.mark.parametrize("name,args", [
    ("count_ips", {"naturaleza": "Inventada"}),
    ("count_ips", {"departamento": "Cali"}),
    ("count_ips", {"nivel_atencion": 9}),
    ("count_ips", {"sql": "DROP TABLE ips"}),
    ("sum_capacidad", {}),
    ("sum_capacidad", {"grupo_capacidad": "CAMAS", "extra": 1}),
    ("top_n", {"dimension": "email", "metrica": "ips"}),
    ("buscar_ips", {"nombre": "x"}),
    ("no_existe", {}),
])
def test_invalid_arguments_rejected_compactly(tools, name, args):
    r = tools.call(name, args)
    assert r["estado"] == "error_validacion" and "valor" not in r and len(json.dumps(r)) < 400


def test_null_args_are_ignored(tools):
    assert tools.call("count_ips", {"departamento": None, "municipio": None})["valor"] == 9320


def test_two_calls_per_turn_limit(tools):
    s = ToolSession(tools)
    s.begin_turn()
    assert s.call("count_ips", {})["estado"] == "ok"
    assert s.call("count_sedes", {})["estado"] == "ok"
    third = s.call("count_ips", {})
    assert third["estado"] == "limite_llamadas" and "valor" not in third
    s.begin_turn()
    assert s.call("count_ips", {})["estado"] == "ok"


def test_closed_values_are_canonicalized(tools):
    assert tools.call("count_ips", {"departamento": "bogota"})["filtros"]["departamento"] == "Bogotá D.C"
    assert tools.call("count_ips", {"departamento": "Departamento de Caldas"})["filtros"]["departamento"] == "Caldas"
    assert tools.call("count_ips", {"departamento": "valle"})["filtros"]["departamento"] == "Valle del Cauca"
    r = tools.call("sum_capacidad", {"grupo_capacidad": "camas", "departamento": "antioquia"})
    assert r["estado"] == "ok" and r["filtros"]["grupo_capacidad"] == "CAMAS"
    assert tools.call("count_ips", {"naturaleza": "publica"})["filtros"]["naturaleza"] == "Pública"
    assert tools.call("count_ips", {"departamento": "Narnia"})["estado"] == "error_validacion"
