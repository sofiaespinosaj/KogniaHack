"""DuckDB en memoria: tabla `ips`, carga desde snapshot o API y swap atómico.

Una conexión compartida; cada petición usa su propio cursor. El swap construye
`ips_new` y la renombra dentro de una transacción, así las consultas ven siempre
una tabla completa.
"""
from __future__ import annotations

import json
import logging
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from app.config import DATASET_ID
from app.profile.profile import compute_profile

log = logging.getLogger(__name__)

# Distritos que el dataset lista como "departamento" -> su departamento real.
DISTRICT_TO_DEPARTMENT = {
    "cali": "Valle del Cauca",
    "buenaventura": "Valle del Cauca",
    "barranquilla": "Atlántico",
    "cartagena": "Bolívar",
    "santa marta": "Magdalena",
}

RAW_COLUMNS = [
    "departamento", "municipio", "c_digo_prestador", "nombre_prestador", "nit_ips",
    "num_digito_verificion", "naturaleza", "num_nivel_atencion", "c_digo_sede",
    "n_mero_sede", "nom_sede_ips", "gerente", "direcci_n", "email", "tel_fono",
    "nom_grupo_capacidad", "nom_descripcion_capacidad",
    "num_cantidad_capacidad_instalada", "fecha_corte", "fuente",
]


def _norm(col: str) -> str:
    return f"lower(strip_accents({col}))"


def _canonical_sql() -> str:
    whens = " ".join(f"WHEN {_norm('departamento')} = '{k}' THEN '{v}'"
                     for k, v in DISTRICT_TO_DEPARTMENT.items())
    # La fuente escribe "Valle del cauca" en minúscula: se unifica con los distritos mapeados.
    return (f"CASE {whens} WHEN {_norm('departamento')} = 'valle del cauca' "
            "THEN 'Valle del Cauca' ELSE departamento END")


# SQL que convierte la tabla cruda `raw` (todo texto) en `ips`.
_DATE_EXPR = (
    "CAST(try_strptime(regexp_replace(trim(replace(fecha_corte, 'Fecha corte REPS:', '')), "
    "'\\s+', ' ', 'g'), '%b %d %Y %I:%M%p') AS DATE)"
)
_RAW_TO_IPS = f"""
SELECT
  row_id, departamento, municipio,
  c_digo_prestador AS codigo_prestador, nombre_prestador, nit_ips,
  num_digito_verificion AS digito_verificacion, naturaleza,
  TRY_CAST(num_nivel_atencion AS INTEGER) AS nivel_atencion,
  c_digo_sede AS codigo_sede, n_mero_sede AS numero_sede, nom_sede_ips AS nombre_sede,
  gerente, direcci_n AS direccion, email, tel_fono AS telefono,
  nom_grupo_capacidad AS grupo_capacidad,
  nom_descripcion_capacidad AS descripcion_capacidad,
  TRY_CAST(num_cantidad_capacidad_instalada AS INTEGER) AS cantidad_capacidad,
  fecha_corte AS fecha_corte_texto,
  {_DATE_EXPR} AS fecha_corte,
  fuente,
  {_norm('departamento')} AS departamento_norm,
  {_norm('municipio')} AS municipio_norm,
  {_norm('nombre_prestador')} AS nombre_prestador_norm,
  {_norm('nom_sede_ips')} AS nombre_sede_norm,
  {_norm('nom_grupo_capacidad')} AS grupo_capacidad_norm,
  {_norm('nom_descripcion_capacidad')} AS descripcion_capacidad_norm,
  {_canonical_sql()} AS departamento_canonico
FROM raw
"""

_FAILURES_SQL = {
    "nivel_atencion": "num_nivel_atencion IS NOT NULL AND TRY_CAST(num_nivel_atencion AS INTEGER) IS NULL",
    "cantidad_capacidad": ("num_cantidad_capacidad_instalada IS NOT NULL AND "
                           "TRY_CAST(num_cantidad_capacidad_instalada AS INTEGER) IS NULL"),
    "fecha_corte": f"fecha_corte IS NOT NULL AND {_DATE_EXPR} IS NULL",
}


@dataclass
class Provenance:
    dataset: str = DATASET_ID
    loaded_at: str | None = None
    source: str | None = None  # "snapshot" | "api"
    rows: int = 0
    fecha_corte: str | None = None
    refresh_skipped_reason: str | None = None
    conversion_failures: dict[str, int] = field(default_factory=dict)


class Store:
    def __init__(self) -> None:
        self._con = duckdb.connect(":memory:")
        self._ddl_lock = threading.Lock()  # serializa solo el DDL del swap
        self.state = "loading"  # loading | ready | degraded | unavailable
        self.provenance = Provenance()
        self.last_error: str | None = None
        self._pending_failures: dict[str, int] = {}
        self.profile: dict | None = None  # calculado una vez por carga o refresco

    def cursor(self) -> duckdb.DuckDBPyConnection:
        """Cursor propio para una petición (comparte la base, no el estado de consulta)."""
        return self._con.cursor()

    # -- construcción de tablas -------------------------------------------------
    def _build_from_rows(self, rows: list[dict], table: str) -> None:
        keys = list(RAW_COLUMNS)
        for r in rows:  # SODA omite las claves nulas: se unifica el conjunto de columnas
            for k in r:
                if not k.startswith(":") and k not in keys:
                    keys.append(k)
        with tempfile.TemporaryDirectory() as td:
            nd = Path(td) / "raw.ndjson"
            with nd.open("w", encoding="utf-8") as f:
                for r in rows:
                    o = {"row_id": r[":id"]}
                    o.update({k: (None if r.get(k) in (None, "") else str(r[k])) for k in keys})
                    f.write(json.dumps(o, ensure_ascii=False) + "\n")
            cols = ", ".join(f"'{k}': 'VARCHAR'" for k in ["row_id", *keys])
            cur = self.cursor()
            cur.execute("DROP TABLE IF EXISTS raw")
            cur.execute(f"CREATE TEMP TABLE raw AS SELECT * FROM read_json('{nd.as_posix()}', "
                        f"format='newline_delimited', columns={{{cols}}})")
            cur.execute(f"CREATE TABLE {table} AS {_RAW_TO_IPS}")
            self._pending_failures = {
                name: cur.execute(f"SELECT count(*) FROM raw WHERE {cond}").fetchone()[0]
                for name, cond in _FAILURES_SQL.items()
            }
            cur.execute("DROP TABLE raw")

    def _build_from_parquet(self, path: Path, table: str, failures: dict[str, int]) -> None:
        cur = self.cursor()
        src = f"read_parquet('{path.as_posix()}')"
        has_canon = any(c[0] == "departamento_canonico"
                        for c in cur.execute(f"DESCRIBE SELECT * FROM {src}").fetchall())
        base = f"SELECT * EXCLUDE (departamento_canonico) FROM {src}" if has_canon \
            else f"SELECT * FROM {src}"
        cur.execute(f"CREATE TABLE {table} AS SELECT *, {_canonical_sql()} AS departamento_canonico "
                    f"FROM ({base})")
        self._pending_failures = failures

    # -- swap atómico -----------------------------------------------------------
    def _swap(self, new_table: str) -> None:
        with self._ddl_lock:
            cur = self.cursor()
            cur.execute("BEGIN")
            try:
                cur.execute("DROP TABLE IF EXISTS ips_old")
                cur.execute("ALTER TABLE IF EXISTS ips RENAME TO ips_old")
                cur.execute(f"ALTER TABLE {new_table} RENAME TO ips")
                cur.execute("DROP TABLE IF EXISTS ips_old")
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise

    def _count(self, table: str = "ips") -> int:
        return self.cursor().execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def _drop(self, table: str) -> None:
        self.cursor().execute(f"DROP TABLE IF EXISTS {table}")

    def replace_from_rows(self, rows: list[dict], expected_total: int, source: str = "api") -> None:
        """Construye `ips_new` y la intercambia solo si el conteo coincide con el total.

        Si no coincide lanza ValueError y deja `ips` intacta.
        """
        self._drop("ips_new")
        self._build_from_rows(rows, "ips_new")
        n = self._count("ips_new")
        if n != expected_total:
            self._drop("ips_new")
            raise ValueError(f"Conteo {n} distinto del total reportado {expected_total}")
        self._swap("ips_new")
        self._finish(source)

    def load_parquet(self, path: Path, failures: dict[str, int] | None = None,
                     source: str = "snapshot") -> None:
        self._drop("ips_new")
        self._build_from_parquet(path, "ips_new", failures or {})
        self._swap("ips_new")
        self._finish(source)

    def _finish(self, source: str) -> None:
        fc = self.cursor().execute("SELECT max(fecha_corte) FROM ips").fetchone()[0]
        self.provenance = Provenance(
            loaded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            source=source, rows=self._count(),
            fecha_corte=str(fc) if fc else None,
            refresh_skipped_reason=self.provenance.refresh_skipped_reason,
            conversion_failures=self._pending_failures,
        )
        self.profile = compute_profile(self.cursor(), source=source,
                                       fecha_corte=self.provenance.fecha_corte)
        self.state = "ready"
        self.last_error = None
