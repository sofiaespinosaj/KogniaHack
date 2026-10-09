"""Fixtures de la suite de QA.

- `store` / `tools`: el backend real (`backend/app`) cargado con `data/snapshot.parquet`, igual que en producción.
- `sql`: una conexión DuckDB **independiente** que lee el Parquet directamente. Es el oráculo: no usa el código del
  backend (ni su mapeo de distritos ni sus columnas derivadas), para que un error en el backend no se autovalide.
- `truth`: las cifras documentadas en `ground_truth.json` (y en `quality/02_golden_dataset_specs.md`).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
DATA = ROOT / "data"
SNAPSHOT = DATA / "snapshot.parquet"
GROUND_TRUTH = Path(__file__).with_name("ground_truth.json")
REPORTS = ROOT / "quality" / "reports"

if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.agent.tools import AgentTools  # noqa: E402
from app.config import load_settings  # noqa: E402
from app.datastore.loader import load_snapshot  # noqa: E402
from app.datastore.store import Store  # noqa: E402

# Mapeo de distritos escrito aquí a propósito (no se importa del backend): es parte del oráculo.
ORACLE_DISTRICTS = {
    "cali": "Valle del Cauca",
    "buenaventura": "Valle del Cauca",
    "valle del cauca": "Valle del Cauca",
    "barranquilla": "Atlántico",
    "cartagena": "Bolívar",
    "santa marta": "Magdalena",
}


@pytest.fixture(scope="session")
def truth() -> dict:
    return json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def store() -> Store:
    s = Store()
    assert load_snapshot(s, load_settings({"DATA_PATH": str(DATA)})), "no se pudo cargar data/snapshot.parquet"
    assert s.state == "ready", f"estado del store: {s.state} ({s.last_error})"
    return s


@pytest.fixture(scope="session")
def tools(store: Store) -> AgentTools:
    return AgentTools(store)


@pytest.fixture(scope="session")
def sql() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect(":memory:")
    cases = " ".join(f"WHEN lower(strip_accents(departamento)) = '{k}' THEN '{v}'"
                     for k, v in ORACLE_DISTRICTS.items())
    con.execute(f"""
        CREATE VIEW snap AS
        SELECT *,
               CASE {cases} ELSE departamento END AS depto_oraculo,
               codigo_sede || '-' || numero_sede AS sede_oraculo,
               lower(strip_accents(municipio)) AS muni_oraculo
        FROM read_parquet('{SNAPSHOT.as_posix()}')
    """)
    return con


def one(con: duckdb.DuckDBPyConnection, query: str, params: list | None = None):
    return con.execute(query, params or []).fetchone()[0]
