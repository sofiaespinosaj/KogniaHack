"""Verdad de referencia del dataset de IPS frente a las tools del agente (`backend/app/agent/tools.py`).

Cada cifra se comprueba con tres fuentes que deben coincidir:
  1. `ground_truth.json` (lo documentado en quality/02_golden_dataset_specs.md),
  2. SQL independiente sobre `data/snapshot.parquet` (fixture `sql`, sin código del backend),
  3. la salida real de la tool, tal como la recibe el modelo de lenguaje.

Ejecutar (desde la raíz del repo):
    uv run --project backend pytest quality
o como script directo:
    uv run --project backend python quality/tests/test_ground_truth_tools.py
"""
from __future__ import annotations

import statistics
import sys
import time

import pytest

from conftest import one

pytestmark = []


# ============================================================================ integridad del snapshot
@pytest.mark.integridad
def test_snapshot_filas_y_corte(sql, truth):
    assert one(sql, "SELECT count(*) FROM snap") == truth["filas"]
    cortes = sql.execute("SELECT DISTINCT CAST(fecha_corte AS VARCHAR) FROM snap").fetchall()
    assert cortes == [(truth["fecha_corte"],)], "el snapshot debe tener una única fecha de corte"


@pytest.mark.integridad
def test_snapshot_ips_y_sedes_distintas(sql, truth):
    assert one(sql, "SELECT count(DISTINCT codigo_prestador) FROM snap") == truth["ips_total"]
    assert one(sql, "SELECT count(DISTINCT sede_oraculo) FROM snap") == truth["sedes_total"]


@pytest.mark.integridad
def test_snapshot_sede_id_no_mezcla_nombres(sql):
    """Una sede física (codigo_sede + numero_sede) nunca tiene dos nombres distintos."""
    assert one(sql, "SELECT count(*) FROM (SELECT sede_oraculo FROM snap GROUP BY 1 "
                    "HAVING count(DISTINCT nombre_sede) > 1)") == 0


@pytest.mark.integridad
def test_snapshot_departamentos_canonicos(sql, truth):
    assert one(sql, "SELECT count(DISTINCT depto_oraculo) FROM snap") == truth["departamentos_canonicos"]


@pytest.mark.integridad
def test_store_carga_igual_que_el_parquet(store, truth):
    assert store.provenance.rows == truth["filas"]
    assert store.provenance.fecha_corte == truth["fecha_corte"]
    assert store.profile["ips_distintas"] == truth["ips_total"]
    assert store.profile["sedes_distintas"] == truth["sedes_total"]


# ============================================================================ a) total nacional
@pytest.mark.cifras
def test_a_total_nacional_ips(tools, sql, truth):
    r = tools.call("count_ips", {})
    assert r["estado"] == "ok"
    assert r["valor"] == truth["ips_total"] == one(sql, "SELECT count(DISTINCT codigo_prestador) FROM snap")
    assert r["filas_usadas"] == truth["filas"], "cuenta prestadores distintos, no filas"


@pytest.mark.cifras
def test_a_total_nacional_sedes(tools, truth):
    r = tools.call("count_sedes", {})
    assert (r["estado"], r["valor"]) == ("ok", truth["sedes_total"])


@pytest.mark.cifras
def test_a_naturaleza(tools, sql, truth):
    r = tools.call("group_by", {"dimension": "naturaleza", "metrica": "ips"})
    got = {i["nombre"]: i["valor"] for i in r["valor"]}
    expected = dict(sql.execute("SELECT naturaleza, count(DISTINCT codigo_prestador) FROM snap GROUP BY 1").fetchall())
    assert got == expected == truth["naturaleza_ips"]


# ============================================================================ b) Bogotá D.C.
@pytest.mark.cifras
@pytest.mark.parametrize("args", [
    {"departamento": "Bogotá D.C"},
    {"departamento": "bogota"},          # el modelo escribe sin tilde: se canonicaliza
    {"municipio": "Bogotá"},
    {"municipio": "BOGOTA"},
], ids=["depto-exacto", "depto-sin-tilde", "municipio", "municipio-mayusculas"])
def test_b_ips_bogota(tools, sql, truth, args):
    r = tools.call("count_ips", args)
    assert r["estado"] == "ok", r
    assert r["valor"] == truth["ips_bogota"] == one(
        sql, "SELECT count(DISTINCT codigo_prestador) FROM snap WHERE muni_oraculo = 'bogota'")


@pytest.mark.cifras
def test_b_bogota_lidera_ranking(tools, sql, truth):
    r = tools.call("top_n", {"dimension": "departamento", "metrica": "ips", "n": 3})
    got = [[i["nombre"], i["valor"]] for i in r["valor"]]
    expected = [list(x) for x in sql.execute(
        "SELECT depto_oraculo, count(DISTINCT codigo_prestador) n FROM snap GROUP BY 1 ORDER BY n DESC LIMIT 3"
    ).fetchall()]
    assert got == expected == truth["top3_departamentos"]


@pytest.mark.cifras
def test_b_medellin(tools, sql, truth):
    r = tools.call("count_ips", {"municipio": "Medellín"})
    assert r["valor"] == truth["ips_medellin"] == one(
        sql, "SELECT count(DISTINCT codigo_prestador) FROM snap WHERE muni_oraculo = 'medellin'")


@pytest.mark.cifras
def test_b_valle_incluye_distritos(tools, sql, truth):
    r = tools.call("count_ips", {"departamento": "Valle del Cauca"})
    assert r["valor"] == truth["ips_valle_del_cauca"] == one(
        sql, "SELECT count(DISTINCT codigo_prestador) FROM snap WHERE depto_oraculo = 'Valle del Cauca'")
    assert sorted(r["incluye_distritos"]) == truth["ips_valle_distritos"]


@pytest.mark.cifras
def test_b_cali_como_municipio_no_cuenta_todo_el_valle(tools, truth):
    """Distrito especial: «IPS en Cali» con municipio no debe devolver las 813 del Valle."""
    r = tools.call("count_ips", {"municipio": "Cali"})
    assert r["valor"] == truth["ips_cali_municipio"]
    assert r["valor"] < truth["ips_valle_del_cauca"]
    assert "incluye_distritos" not in r


@pytest.mark.cifras
def test_b_antioquia_sin_distritos(tools):
    assert "incluye_distritos" not in tools.call("count_ips", {"departamento": "Antioquia"})


# ============================================================================ c) capacidad en Antioquia
@pytest.mark.cifras
def test_c_camas_antioquia(tools, sql, truth):
    r = tools.call("sum_capacidad", {"grupo_capacidad": "CAMAS", "departamento": "Antioquia"})
    assert r["estado"] == "ok"
    assert r["valor"] == truth["antioquia_capacidad"]["CAMAS"] == one(
        sql, "SELECT sum(cantidad_capacidad) FROM snap WHERE grupo_capacidad = 'CAMAS' AND depto_oraculo = 'Antioquia'")


@pytest.mark.cifras
@pytest.mark.parametrize("texto", ["Adultos", "adultos", "camas de adultos", "camas para adultos"])
def test_c_camas_adultos_antioquia(tools, truth, texto):
    """La descripción coloquial resuelve a «Adultos» y no suma «Intensiva Adultos»."""
    r = tools.call("sum_capacidad", {"grupo_capacidad": "CAMAS", "descripcion_capacidad": texto,
                                     "departamento": "Antioquia"})
    assert (r["estado"], r["valor"]) == ("ok", truth["antioquia_camas_adultos"]), r
    assert r["filtros"]["descripcion_capacidad"] == "Adultos"


@pytest.mark.cifras
def test_c_capacidad_antioquia_por_grupo(tools, sql, truth):
    expected = dict(sql.execute(
        "SELECT grupo_capacidad, sum(cantidad_capacidad) FROM snap WHERE depto_oraculo = 'Antioquia' GROUP BY 1"
    ).fetchall())
    assert expected == truth["antioquia_capacidad"]
    for grupo, total in expected.items():
        r = tools.call("sum_capacidad", {"grupo_capacidad": grupo, "departamento": "Antioquia"})
        assert r["valor"] == total, grupo


@pytest.mark.cifras
def test_c_camas_adultos_nacional(tools, sql, truth):
    r = tools.call("sum_capacidad", {"grupo_capacidad": "CAMAS", "descripcion_capacidad": "camas para adultos"})
    assert r["valor"] == truth["camas_adultos_nacional"] == one(
        sql, "SELECT sum(cantidad_capacidad) FROM snap WHERE grupo_capacidad = 'CAMAS' "
             "AND lower(strip_accents(descripcion_capacidad)) = 'adultos'")


@pytest.mark.cifras
def test_c_nivel_3_lleva_nota_de_cobertura(tools, sql, truth):
    r = tools.call("count_ips", {"nivel_atencion": 3})
    assert r["valor"] == truth["ips_nivel_3"] == one(
        sql, "SELECT count(DISTINCT codigo_prestador) FROM snap WHERE nivel_atencion = 3")
    assert "nota" in r, "sin naturaleza, el resultado debe aclarar que el nivel casi solo existe en públicas"


# ============================================================================ d) búsqueda por nombre
@pytest.mark.busqueda
@pytest.mark.parametrize("nombre", [
    "Hospital Pablo Tobón Uribe",
    "HOSPITAL PABLO TOBON URIBE",
    "hospital pablo tobon uribe",
    "Pablo Tobón Uribe",
    "PABLO TOVON URIBE",                 # error típico de transcripción de voz
], ids=["exacto", "mayusculas", "minusculas-sin-tilde", "sin-generico", "error-asr"])
def test_d_pablo_tobon_unico(tools, sql, truth, nombre):
    pt = truth["pablo_tobon"]
    r = tools.call("buscar_ips", {"nombre": nombre})
    assert r["estado"] == "ok", r
    (ips,) = r["valor"]
    assert ips["nombre"] == pt["nombre"]
    assert (ips["naturaleza"], ips["departamento"], ips["municipio"]) == (pt["naturaleza"], pt["departamento"], pt["municipio"])
    assert ips["sedes"] == pt["sedes"] == one(
        sql, "SELECT count(DISTINCT sede_oraculo) FROM snap WHERE codigo_prestador = ?", [pt["codigo_prestador"]])


@pytest.mark.busqueda
def test_d_pablo_tobon_devuelve_contacto_real(tools, sql, truth):
    """La dirección y el teléfono dichos salen del dataset (no del modelo)."""
    r = tools.call("buscar_ips", {"nombre": "Hospital Pablo Tobón Uribe"})
    ips = r["valor"][0]
    assert ips.get("direccion"), "con un único candidato, buscar_ips debe traer la dirección"
    reales = sql.execute("SELECT DISTINCT direccion, telefono FROM snap WHERE codigo_prestador = ?",
                         [truth["pablo_tobon"]["codigo_prestador"]]).fetchall()
    assert ips["direccion"] in {d for d, _ in reales}
    for sede in ips.get("sedes_principales", []):
        assert sede.get("direccion") in {d for d, _ in reales}
        if sede.get("telefono"):
            assert sede["telefono"] in {t for _, t in reales}


@pytest.mark.busqueda
@pytest.mark.parametrize("nombre", ["pablo tobon", "tobon"])
def test_d_nombre_compartido_es_ambiguo(tools, nombre):
    """«Pablo Tobón» también es una óptica y una unidad hospitalaria: hay que preguntar cuál."""
    r = tools.call("buscar_ips", {"nombre": nombre})
    assert r["estado"] == "ambiguo", r
    nombres = [c["nombre"] for c in r["candidatos"]]
    assert "HOSPITAL PABLO TOBON URIBE" in nombres
    assert len(nombres) >= 2 and len(nombres) <= 10
    assert "valor" not in r, "un resultado ambiguo no trae valor"


@pytest.mark.busqueda
def test_d_clinica_santa_maria_ambigua_y_acotada(tools, sql):
    r = tools.call("buscar_ips", {"nombre": "clinica santa maria"})
    assert r["estado"] == "ambiguo"
    assert 2 <= len(r["candidatos"]) <= 10
    total = one(sql, "SELECT count(DISTINCT codigo_prestador) FROM snap WHERE "
                     "lower(strip_accents(nombre_prestador)) LIKE '%santa maria%' "
                     "OR lower(strip_accents(nombre_sede)) LIKE '%santa maria%'")
    assert total > 10, "precondición: hay más homónimos que el tope de 10"
    assert r.get("total_candidatos", len(r["candidatos"])) >= len(r["candidatos"])


@pytest.mark.busqueda
def test_d_nombre_inexistente_sin_resultados(tools):
    r = tools.call("buscar_ips", {"nombre": "zzqx clinica inexistente"})
    assert r["estado"] == "sin_resultados" and r["valor"] == []


# ============================================================================ e) estados del contrato
@pytest.mark.estados
def test_e_privada_nivel_1_sin_cobertura(tools, sql, truth):
    r = tools.call("count_ips", {"naturaleza": "Privada", "nivel_atencion": 1})
    assert r["estado"] == "sin_cobertura"
    assert r["valor"] == truth["privadas_con_nivel"] == one(
        sql, "SELECT count(DISTINCT codigo_prestador) FROM snap WHERE naturaleza = 'Privada' AND nivel_atencion IS NOT NULL")
    assert r.get("nota"), "sin_cobertura explica que no es un cero real"


@pytest.mark.estados
def test_e_mixta_nivel_2_sin_cobertura_no_cero(tools):
    r = tools.call("count_ips", {"naturaleza": "Mixta", "nivel_atencion": 2})
    assert r["estado"] == "sin_cobertura", "un 0 por ausencia de dato no puede presentarse como ok"


@pytest.mark.estados
def test_e_publicas_nivel_3_ok(tools):
    r = tools.call("count_ips", {"naturaleza": "Pública", "nivel_atencion": 3})
    assert r["estado"] == "ok" and r["valor"] > 0


@pytest.mark.estados
def test_e_lugar_inexistente_no_devuelve_cero(tools):
    r = tools.call("count_ips", {"municipio": "Springfield"})
    assert r["estado"] == "no_encontrado" and "valor" not in r
    assert len(r.get("sugerencias", [])) <= 3


@pytest.mark.estados
def test_e_lugar_con_error_tipografico_sugiere(tools):
    r = tools.call("count_ips", {"municipio": "Manisales"})
    assert r["estado"] == "no_encontrado"
    assert any("MANIZALES" in s.upper() for s in r["sugerencias"])


@pytest.mark.estados
def test_e_descripcion_inexistente(tools):
    r = tools.call("sum_capacidad", {"grupo_capacidad": "CAMAS", "descripcion_capacidad": "camas para extraterrestres"})
    assert r["estado"] == "no_encontrado" and "valor" not in r
    assert 1 <= len(r["sugerencias"]) <= 3


@pytest.mark.estados
def test_e_descripcion_ambigua(tools):
    r = tools.call("sum_capacidad", {"grupo_capacidad": "CAMAS", "descripcion_capacidad": "cuidado intensivo"})
    assert r["estado"] == "ambiguo"
    assert {"Cuidado Intensivo Adulto", "Cuidado Intensivo Neonatal"} <= set(r["candidatos"])


@pytest.mark.estados
def test_e_envoltorio_comun(tools, truth):
    for name, args in [("count_ips", {}), ("count_sedes", {"departamento": "Caldas"}),
                       ("sum_capacidad", {"grupo_capacidad": "AMBULANCIAS"}),
                       ("top_n", {"dimension": "municipio", "metrica": "ips", "n": 3}),
                       ("listar_ips", {"municipio": "Manizales", "n": 3})]:
        r = tools.call(name, args)
        assert r["estado"] == "ok", (name, r)
        assert r["fecha_corte"] == truth["fecha_corte"] and r["origen"] == truth["origen"], name
        assert "valor" in r and "filas_usadas" in r, name
        assert "email" not in str(r) and "gerente" not in str(r), name


@pytest.mark.estados
def test_e_listas_acotadas_a_10(tools):
    r = tools.call("top_n", {"dimension": "departamento", "metrica": "ips", "n": 50})
    assert len(r["valor"]) == 10 and r.get("acotado") is True
    r = tools.call("group_by", {"dimension": "departamento", "metrica": "ips"})
    assert len(r["valor"]) == 10 and r.get("acotado") is True


# ============================================================================ seguridad
@pytest.mark.seguridad
def test_s_inyeccion_sql_en_lugar(tools, store, truth):
    r = tools.call("count_ips", {"municipio": "Cali'; DROP TABLE ips; --"})
    assert r["estado"] == "no_encontrado"
    assert store.cursor().execute("SELECT count(*) FROM ips").fetchone()[0] == truth["filas"]


@pytest.mark.seguridad
def test_s_inyeccion_sql_en_nombre_no_rompe(tools, store, truth):
    r = tools.call("buscar_ips", {"nombre": "x' OR 1=1 --"})
    assert r["estado"] in {"sin_resultados", "ambiguo", "ok"}
    assert store.cursor().execute("SELECT count(*) FROM ips").fetchone()[0] == truth["filas"]


@pytest.mark.seguridad
@pytest.mark.parametrize("name,args", [
    ("count_ips", {"foo": 1}),
    ("count_ips", {"departamento": "Narnia"}),
    ("count_ips", {"nivel_atencion": 7}),
    ("top_n", {"dimension": "color", "metrica": "ips"}),
    ("sum_capacidad", {}),
    ("run_sql", {"sql": "SELECT 1"}),
], ids=["campo-desconocido", "enum-departamento", "enum-nivel", "enum-dimension", "requerido", "tool-inexistente"])
def test_s_argumentos_fuera_de_esquema(tools, name, args):
    r = tools.call(name, args)
    assert r["estado"] == "error_validacion", r
    assert "valor" not in r


@pytest.mark.seguridad
def test_s_presupuesto_de_dos_llamadas_por_turno(tools):
    from app.agent.tools import ToolSession
    s = ToolSession(tools)
    s.begin_turn()
    assert s.call("count_ips", {})["estado"] == "ok"
    assert s.call("count_sedes", {})["estado"] == "ok"
    assert s.call("count_ips", {})["estado"] == "limite_llamadas"
    s.begin_turn()
    assert s.call("count_ips", {})["estado"] == "ok", "el presupuesto se reinicia en cada turno"


# ============================================================================ latencia
GOLDEN_CALLS = [
    ("count_ips", {}),
    ("count_ips", {"municipio": "Medellín"}),
    ("count_sedes", {}),
    ("sum_capacidad", {"grupo_capacidad": "CAMAS", "descripcion_capacidad": "adultos", "departamento": "Antioquia"}),
    ("top_n", {"dimension": "departamento", "metrica": "ips", "n": 3}),
    ("group_by", {"dimension": "naturaleza", "metrica": "ips"}),
    ("listar_ips", {"municipio": "Manizales", "n": 3}),
    ("buscar_ips", {"nombre": "Hospital Pablo Tobón Uribe"}),
    ("buscar_ips", {"nombre": "clinica santa maria"}),
]
P95_GOAL_MS = 200.0


def measure(tools, repeats: int = 20) -> dict[str, dict[str, float]]:
    """p50, p95 y máximo en ms por llamada de oro (después de un calentamiento)."""
    out = {}
    for name, args in GOLDEN_CALLS:
        tools.call(name, dict(args))
        samples = []
        for _ in range(repeats):
            t0 = time.perf_counter()
            tools.call(name, dict(args))
            samples.append((time.perf_counter() - t0) * 1000)
        samples.sort()
        label = f"{name} {args}" if args else name
        out[label] = {"p50": statistics.median(samples),
                      "p95": samples[min(len(samples) - 1, round(0.95 * (len(samples) - 1)))],
                      "max": samples[-1]}
    return out


@pytest.mark.latencia
def test_l_p95_por_tool_bajo_la_meta(tools):
    lentos = {k: round(v["p95"], 1) for k, v in measure(tools).items() if v["p95"] > P95_GOAL_MS}
    assert not lentos, f"p95 por encima de {P95_GOAL_MS} ms: {lentos}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v", "-c", str(__import__("pathlib").Path(__file__).parents[1] / "pytest.ini")]))
