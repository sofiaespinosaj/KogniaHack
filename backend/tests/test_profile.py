import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import load_settings
from app.datastore.loader import load_snapshot
from app.datastore.store import Store
from app.main import create_app
from tests.conftest import raw_row

REAL_DATA = Path(__file__).resolve().parents[2] / "data"


@pytest.fixture(scope="module")
def store():
    s = Store()
    assert load_snapshot(s, load_settings({"DATA_PATH": str(REAL_DATA)}))
    return s


def test_profile_totals_match_table(store):
    p = store.profile
    assert p["rows"] == store._count() == 41427
    assert {c["name"] for c in p["columns"]} >= {"nivel_atencion", "naturaleza", "codigo_sede"}
    assert all({"name", "type", "nulls", "null_pct"} <= c.keys() for c in p["columns"])


def _col(store, name):
    return next(c for c in store.profile["columns"] if c["name"] == name)


def test_low_cardinality_columns_expose_all_values(store):
    nat = _col(store, "naturaleza")
    assert nat["values_complete"] and len(nat["values"]) == nat["distinct"] == 3
    for c in store.profile["columns"]:
        if "values" in c and c["distinct"] <= 50:
            assert c["values_complete"] and len(c["values"]) == c["distinct"]


def test_departamento_canonico_exposes_all_33_values(store):
    col = _col(store, "departamento_canonico")
    assert col["values_complete"] and col["distinct"] == 33 and len(col["values"]) == 33
    got = {v["value"]: v["count"] for v in col["values"]}
    assert len(got) == 33 and "Cali" not in got and "Valle del Cauca" in got
    assert sum(got.values()) == store.profile["rows"]  # los 33 conteos cubren todas las filas


def test_high_cardinality_columns_limited_to_top_10(store):
    col = _col(store, "nombre_prestador")
    assert col["distinct"] > 50 and not col["values_complete"] and len(col["values"]) == 10


def test_identifier_and_contact_columns_list_no_values(store):
    for name in ("row_id", "email", "telefono", "gerente"):
        assert "values" not in _col(store, name)


def test_grain_and_counts(store):
    p = store.profile
    assert "sede" in p["grain"] and "capacidad" in p["grain"]
    assert (p["ips_distintas"], p["sedes_distintas"]) == (9320, 15547)
    assert p["definitions"]["ips"] == "COUNT(DISTINCT codigo_prestador)"
    assert p["definitions"]["sedes"] == "COUNT(DISTINCT sede_id)"
    assert "nunca filas" in p["counting_guidance"]


def test_nivel_atencion_coverage(store):
    c = store.profile["coverage"]["nivel_atencion"]
    assert c["null_rows"] == 25266 and round(c["null_pct"]) == 61
    assert c["rows_with_level_publica"] == 16160 and c["rows_with_level_privada"] == 1
    assert "exclusivo de IPS públicas" in store.profile["coverage"]["notes"][0]


def test_naturaleza_distribution(store):
    assert list(store.profile["naturaleza"].values()) == [25067, 16174, 186]
    assert set(store.profile["naturaleza"]) == {"Privada", "Pública", "Mixta"}


def test_fecha_corte_and_source(store):
    assert store.profile["fecha_corte"] == "2022-11-05" and store.profile["source"] == "snapshot"


def test_serializable_and_deterministic(store):
    a = json.dumps(store.profile, sort_keys=True)
    s2 = Store()
    load_snapshot(s2, load_settings({"DATA_PATH": str(REAL_DATA)}))
    assert a == json.dumps(s2.profile, sort_keys=True)


def test_profile_recomputed_once_on_refresh(store, rows):
    s = Store()
    s.replace_from_rows(rows[:5], 5, "snapshot")
    first = s.profile
    assert first["rows"] == 5
    s.replace_from_rows(rows, len(rows), "api")
    assert s.profile is not first and s.profile["rows"] == 50 and s.profile["source"] == "api"


def test_profile_query_under_50ms_and_no_recompute(store):
    ref = store.profile
    times = []
    for _ in range(100):
        t0 = time.perf_counter()
        _ = store.profile
        times.append((time.perf_counter() - t0) * 1000)
    assert max(times) < 50 and store.profile is ref


def test_profile_endpoint_under_50ms():
    with TestClient(create_app(load_settings({"DATA_PATH": str(REAL_DATA)}))) as c:
        for _ in range(100):
            if c.get("/health").json()["status"] == "ready":
                break
            time.sleep(0.05)
        c.get("/profile")  # calentamiento
        t0 = time.perf_counter()
        r = c.get("/profile")
        ms = (time.perf_counter() - t0) * 1000
    assert r.status_code == 200 and r.json()["rows"] == 41427 and ms < 50, f"{ms:.1f} ms"


def test_profile_endpoint_503_before_data(tmp_path):
    app = create_app(load_settings({"DATA_PATH": str(tmp_path)}))
    with TestClient(app) as c:
        time.sleep(0.3)
        assert c.get("/profile").status_code == 503
