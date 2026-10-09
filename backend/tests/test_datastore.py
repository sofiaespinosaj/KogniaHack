import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.datastore import loader
from app.datastore.loader import load_snapshot, startup_load
from app.datastore.store import Store
from app.main import create_app
from tests.conftest import raw_row

REAL_DATA = Path(__file__).resolve().parents[2] / "data"


def settings_for(path, **env):
    return load_settings({"DATA_PATH": str(path), **env})


@pytest.fixture(scope="module")
def real_store():
    s = Store()
    assert load_snapshot(s, settings_for(REAL_DATA))
    return s


def q(store, sql):
    return store.cursor().execute(sql).fetchall()


# 3.2 / 3.7 -------------------------------------------------------------------
def test_snapshot_loads_ready_within_5s():
    s = Store()
    t0 = time.monotonic()
    assert load_snapshot(s, settings_for(REAL_DATA))
    elapsed = time.monotonic() - t0
    assert s.state == "ready" and elapsed <= 5, f"{elapsed:.2f}s"


def test_snapshot_counts(real_store):
    assert q(real_store, "SELECT count(*) FROM ips")[0][0] == 41427
    assert q(real_store, "SELECT count(DISTINCT sede_id) FROM ips")[0][0] == 15547
    assert q(real_store, "SELECT count(DISTINCT codigo_prestador) FROM ips")[0][0] == 9320
    assert real_store.provenance.source == "snapshot"


def test_inconsistent_snapshot_is_degraded(tmp_path):
    shutil.copy(REAL_DATA / "snapshot.parquet", tmp_path / "snapshot.parquet")
    meta = json.loads((REAL_DATA / "snapshot.meta.json").read_text(encoding="utf-8"))
    meta["rows"] = 41000
    (tmp_path / "snapshot.meta.json").write_text(json.dumps(meta), encoding="utf-8")
    s = Store()
    assert load_snapshot(s, settings_for(tmp_path))
    assert s.state == "degraded" and "41000" in s.last_error


# 3.3 -------------------------------------------------------------------------
def test_types_and_aliases(real_store):
    types = dict(q(real_store, "SELECT column_name, data_type FROM information_schema.columns "
                               "WHERE table_name='ips'"))
    assert types["nivel_atencion"] == "INTEGER" and types["cantidad_capacidad"] == "INTEGER"
    assert types["fecha_corte"] == "DATE" and types["fecha_corte_texto"] == "VARCHAR"
    for c in ("codigo_prestador", "nombre_prestador", "direccion", "telefono", "grupo_capacidad",
              "descripcion_capacidad", "departamento_canonico", "departamento_norm"):
        assert c in types


def test_normalization_lowercase_without_accents(real_store):
    row = q(real_store, "SELECT departamento_norm FROM ips WHERE departamento LIKE 'Bogot%' LIMIT 1")
    assert row[0][0] == "bogota d.c"


def test_rows_path_types_normalization_and_conversion_failures():
    s = Store()
    rows = [raw_row(1), raw_row(2, num_nivel_atencion="abc"),
            raw_row(3, num_cantidad_capacidad_instalada="x", fecha_corte="basura")]
    s.replace_from_rows(rows, 3, "api")
    r = q(s, "SELECT nivel_atencion, cantidad_capacidad, CAST(fecha_corte AS VARCHAR), "
             "nombre_prestador_norm FROM ips ORDER BY row_id")
    assert r[0] == (1, 10, "2022-11-05", "clinica nandu")
    assert r[1][0] is None and r[2][1] is None and r[2][2] is None
    assert s.provenance.conversion_failures == {"nivel_atencion": 1, "cantidad_capacidad": 1,
                                                "fecha_corte": 1}


# 3.8 -------------------------------------------------------------------------
def test_departamento_canonico(real_store):
    assert q(real_store, "SELECT DISTINCT departamento_canonico FROM ips WHERE departamento='Cali'") \
        == [("Valle del Cauca",)]
    assert q(real_store, "SELECT count(*) FROM ips WHERE departamento_canonico IS NULL")[0][0] == 0
    assert q(real_store, "SELECT count(DISTINCT departamento_canonico) FROM ips")[0][0] == 33
    assert q(real_store, "SELECT count(DISTINCT codigo_prestador) FROM ips "
                         "WHERE departamento_canonico='Valle del Cauca'")[0][0] == 813


def test_district_mapping(real_store):
    got = dict(q(real_store, "SELECT DISTINCT departamento, departamento_canonico FROM ips "
                             "WHERE departamento IN ('Barranquilla','Cartagena','Santa Marta',"
                             "'Buenaventura') OR departamento LIKE 'Bogot%'"))
    assert got["Barranquilla"] == "Atlántico" and got["Cartagena"] == "Bolívar"
    assert got["Santa Marta"] == "Magdalena" and got["Buenaventura"] == "Valle del Cauca"
    assert got["Bogotá D.C"] == "Bogotá D.C"


# 3.4 -------------------------------------------------------------------------
async def test_missing_snapshot_without_token_is_unavailable(tmp_path):
    s = Store()
    await startup_load(s, settings_for(tmp_path))
    assert s.state == "unavailable" and s.last_error


async def test_unreadable_snapshot_without_token_is_unavailable(tmp_path):
    (tmp_path / "snapshot.parquet").write_bytes(b"no es parquet")
    s = Store()
    await startup_load(s, settings_for(tmp_path))
    assert s.state == "unavailable"
    assert "ips_new" not in {t[0] for t in s.cursor().execute("SHOW TABLES").fetchall()}


async def test_missing_snapshot_falls_back_to_full_download(tmp_path, monkeypatch, rows):
    async def fake_refresh(store, client):
        store.replace_from_rows(rows, len(rows), "api")
        return True

    monkeypatch.setattr(loader, "refresh_once", fake_refresh)
    s = Store()
    await startup_load(s, settings_for(tmp_path, SODA_APP_TOKEN="tok"))
    assert s.state == "ready" and s.provenance.source == "api"


async def test_missing_snapshot_and_failed_download_is_unavailable(tmp_path, monkeypatch):
    async def fake_refresh(store, client):
        return False

    monkeypatch.setattr(loader, "refresh_once", fake_refresh)
    s = Store()
    await startup_load(s, settings_for(tmp_path, SODA_APP_TOKEN="tok"))
    assert s.state == "unavailable"


# 3.5 -------------------------------------------------------------------------
def test_provenance_and_health_without_token_skips_refresh():
    settings = settings_for(REAL_DATA)
    with TestClient(create_app(settings)) as c:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            body = c.get("/health").json()
            if body["status"] == "ready":
                break
            time.sleep(0.05)
    d = body["data"]
    assert body["status"] == "ready"
    assert (d["dataset"], d["source"], d["rows"], d["fecha_corte"]) == \
        ("s2ru-bqt6", "snapshot", 41427, "2022-11-05")
    assert d["loaded_at"] and d["refresh_skipped_reason"]


# 3.3a ------------------------------------------------------------------------
def test_sede_id_distinct_and_no_name_conflicts(real_store):
    assert q(real_store, "SELECT count(DISTINCT sede_id) FROM ips")[0][0] == 15547
    assert q(real_store, "SELECT count(*) FROM (SELECT sede_id FROM ips GROUP BY 1 "
                         "HAVING count(DISTINCT nombre_sede) > 1)")[0][0] == 0
    assert q(real_store, "SELECT count(*) FROM ips WHERE sede_id IS NULL")[0][0] == 0
    assert q(real_store, "SELECT count(*) FROM ips WHERE sede_id <> codigo_sede || '-' || numero_sede")[0][0] == 0


def test_sede_id_built_on_api_path_too():
    s = Store()
    s.replace_from_rows([raw_row(1, c_digo_sede="S9", n_mero_sede="2")], 1, "api")
    assert q(s, "SELECT sede_id FROM ips") == [("S9-2",)]


def test_sede_id_defined_in_single_place():
    import re

    src = Path(__file__).resolve().parents[1].joinpath("app")
    hits = [p.name for p in src.rglob("*.py")
            if re.search(r"codigo_sede\s*\|\|", p.read_text(encoding="utf-8"))]
    # gold.py repite la clave a propósito: es el SQL de referencia independiente de las tools (tarea 4.3)
    assert sorted(hits) == ["gold.py", "store.py"]
