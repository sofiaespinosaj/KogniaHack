"""Descarga completa del dataset s2ru-bqt6 (SODA3) y genera un snapshot Parquet.

Uso:
    pip install duckdb
    set SODA_APP_TOKEN=...            (PowerShell: $env:SODA_APP_TOKEN="...")
    python scripts/snapshot.py

Salida:
    data/snapshot.parquet   tabla `ips` limpia (alias, tipos, columnas *_norm)
    data/snapshot.meta.json procedencia (dataset, fecha, filas, origen)

Solo usa la libreria estandar para la descarga; duckdb se usa para escribir el Parquet.
El token se lee SOLO de la variable de entorno y nunca se imprime.
"""
from __future__ import annotations

import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

DATASET = "s2ru-bqt6"
URL = os.getenv("SODA_URL", f"https://www.datos.gov.co/api/v3/views/{DATASET}/query.json")
TOKEN = os.getenv("SODA_APP_TOKEN", "")
PAGE_SIZE = int(os.getenv("SODA_PAGE_SIZE", "1000"))
CONCURRENCY = int(os.getenv("SODA_CONCURRENCY", "4"))
MAX_TRIES = int(os.getenv("SODA_MAX_TRIES", "5"))
TIMEOUT = float(os.getenv("SODA_TIMEOUT", "30"))
OUT_DIR = Path(os.getenv("SNAPSHOT_DIR", "data"))

EXPECTED_COLS = [
    "departamento", "municipio", "c_digo_prestador", "nombre_prestador", "nit_ips",
    "num_digito_verificion", "naturaleza", "num_nivel_atencion", "c_digo_sede",
    "n_mero_sede", "nom_sede_ips", "gerente", "direcci_n", "email", "tel_fono",
    "nom_grupo_capacidad", "nom_descripcion_capacidad",
    "num_cantidad_capacidad_instalada", "fecha_corte", "fuente",
]


class AuthError(RuntimeError):
    pass


def _post(body: dict) -> list[dict]:
    """POST con reintentos. 401/403 no se reintentan; 429 respeta Retry-After."""
    data = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["X-App-Token"] = TOKEN
    last = None
    for i in range(MAX_TRIES):
        wait = 2 ** i + random.random()
        try:
            req = urllib.request.Request(URL, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise AuthError(f"HTTP {e.code}: token invalido o sin permisos") from None
            last = f"HTTP {e.code}"
            if e.code == 429:
                try:
                    wait = float(e.headers.get("Retry-After", wait))
                except ValueError:
                    pass
            elif e.code < 500:
                raise RuntimeError(f"HTTP {e.code}: {e.read()[:300]!r}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError, json.JSONDecodeError) as e:
            last = type(e).__name__
        print(f"  reintento {i + 1}/{MAX_TRIES} ({last}); espero {wait:.1f}s", file=sys.stderr)
        time.sleep(wait)
    raise RuntimeError(f"API no disponible tras {MAX_TRIES} intentos ({last})")


def fetch_all() -> tuple[list[dict], int]:
    total = int(_post({"query": "SELECT count(*) AS n"})[0]["n"])
    pages = -(-total // PAGE_SIZE)
    print(f"Total reportado: {total} filas -> {pages} paginas (x{CONCURRENCY} en paralelo)")

    def one(p: int) -> list[dict]:
        return _post({"query": "SELECT * ORDER BY :id",
                      "page": {"pageNumber": p, "pageSize": PAGE_SIZE}})

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        chunks = list(ex.map(one, range(1, pages + 1)))
    rows = [r for c in chunks for r in c]
    return rows, total


def validate(rows: list[dict], total: int) -> None:
    ids = {r.get(":id") for r in rows}
    if len(rows) != total:
        raise RuntimeError(f"Descarga incompleta: {len(rows)} de {total}")
    if len(ids) != total or None in ids:
        raise RuntimeError(f"IDs duplicados o faltantes: {len(ids)} unicos de {total}")


def write_snapshot(rows: list[dict], total: int) -> None:
    import duckdb  # import tardio: la descarga no lo necesita

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    nd = OUT_DIR / "_raw.ndjson"
    keys = list(EXPECTED_COLS)
    for r in rows:  # SODA omite las claves con valor nulo: se unifican aqui
        for k in r:
            if k != ":id" and not k.startswith(":") and k not in keys:
                keys.append(k)
    with nd.open("w", encoding="utf-8") as f:
        for r in rows:
            o = {"row_id": r[":id"]}
            o.update({k: (None if r.get(k) in (None, "") else str(r.get(k))) for k in keys})
            f.write(json.dumps(o, ensure_ascii=False) + "\n")

    cols = {"row_id": "VARCHAR", **{k: "VARCHAR" for k in keys}}
    cols_sql = ", ".join(f"'{k}': '{v}'" for k, v in cols.items())
    con = duckdb.connect()
    con.execute(f"CREATE TABLE raw AS SELECT * FROM read_json('{nd.as_posix()}', "
                f"format='newline_delimited', columns={{{cols_sql}}})")

    def norm(c: str) -> str:
        return f"lower(strip_accents({c}))"

    con.execute(f"""
    CREATE TABLE ips AS SELECT
      row_id,
      departamento, municipio,
      c_digo_prestador AS codigo_prestador, nombre_prestador, nit_ips,
      num_digito_verificion AS digito_verificacion,
      naturaleza,
      TRY_CAST(num_nivel_atencion AS INTEGER) AS nivel_atencion,
      c_digo_sede AS codigo_sede, n_mero_sede AS numero_sede, nom_sede_ips AS nombre_sede,
      gerente, direcci_n AS direccion, email, tel_fono AS telefono,
      nom_grupo_capacidad AS grupo_capacidad,
      nom_descripcion_capacidad AS descripcion_capacidad,
      TRY_CAST(num_cantidad_capacidad_instalada AS INTEGER) AS cantidad_capacidad,
      fecha_corte AS fecha_corte_texto,
      CAST(try_strptime(
        regexp_replace(trim(replace(fecha_corte, 'Fecha corte REPS:', '')), '\\s+', ' ', 'g'),
        '%b %d %Y %I:%M%p') AS DATE) AS fecha_corte,
      fuente,
      {norm('departamento')} AS departamento_norm,
      {norm('municipio')} AS municipio_norm,
      {norm('nombre_prestador')} AS nombre_prestador_norm,
      {norm('nom_sede_ips')} AS nombre_sede_norm,
      {norm('nom_grupo_capacidad')} AS grupo_capacidad_norm,
      {norm('nom_descripcion_capacidad')} AS descripcion_capacidad_norm
    FROM raw
    """)

    n = con.execute("SELECT count(*) FROM ips").fetchone()[0]
    if n != total:
        raise RuntimeError(f"La tabla ips tiene {n} filas, se esperaban {total}")

    pq = OUT_DIR / "snapshot.parquet"
    con.execute(f"COPY ips TO '{pq.as_posix()}' (FORMAT PARQUET, COMPRESSION ZSTD)")
    nd.unlink(missing_ok=True)

    q = lambda s: con.execute(s).fetchall()  # noqa: E731
    cast_fail = q("SELECT count(*) FROM raw WHERE num_cantidad_capacidad_instalada IS NOT NULL "
                  "AND TRY_CAST(num_cantidad_capacidad_instalada AS INTEGER) IS NULL")[0][0]
    date_fail = q("SELECT count(*) FROM ips WHERE fecha_corte_texto IS NOT NULL "
                  "AND fecha_corte IS NULL")[0][0]
    stats = {
        "filas": n,
        "ips_distintas": q("SELECT count(DISTINCT codigo_prestador) FROM ips")[0][0],
        "sedes_distintas": q("SELECT count(DISTINCT codigo_sede) FROM ips")[0][0],
        "naturaleza": dict(q("SELECT coalesce(naturaleza,'(nulo)'), count(*) FROM ips GROUP BY 1")),
        "nivel_atencion": dict(q("SELECT coalesce(CAST(nivel_atencion AS VARCHAR),'(nulo)'), count(*) "
                                 "FROM ips GROUP BY 1")),
        "cantidad_no_convertible": cast_fail,
        "fecha_corte_no_parseada": date_fail,
        "fecha_corte_min_max": [str(x) for x in q("SELECT min(fecha_corte), max(fecha_corte) FROM ips")[0]],
    }
    meta = {
        "dataset": DATASET,
        "source": "api",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rows": n,
        "expected_total": total,
        "columns": [c[0] for c in con.execute("DESCRIBE ips").fetchall()],
        "stats": stats,
    }
    (OUT_DIR / "snapshot.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    print(f"OK -> {pq} ({pq.stat().st_size / 1e6:.1f} MB)")


def main() -> int:
    if not TOKEN:
        print("Falta la variable de entorno SODA_APP_TOKEN", file=sys.stderr)
        return 2
    t0 = time.time()
    try:
        rows, total = fetch_all()
        validate(rows, total)
        print(f"Descarga validada en {time.time() - t0:.1f}s")
        write_snapshot(rows, total)
    except AuthError as e:
        print(f"ERROR de autenticacion: {e}", file=sys.stderr)
        return 3
    except Exception as e:  # noqa: BLE001
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
