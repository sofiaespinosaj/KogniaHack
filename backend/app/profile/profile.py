"""Perfil del dataset: se calcula una vez por carga/refresco y se sirve desde memoria.

Es determinista y se deriva solo de la tabla `ips`; no contiene texto inventado
más allá de las definiciones de grano.
"""
from __future__ import annotations

import duckdb

TOP_N = 10                # valores principales en columnas con más de MAX_CATEGORICAL distintos
MAX_CATEGORICAL = 50      # hasta este número de distintos se exponen TODOS los valores (enums del agente)
# Identificadores y datos de contacto: no se listan valores.
NO_VALUES_COLUMNS = {"row_id", "gerente", "email", "telefono", "direccion", "nit_ips", "digito_verificacion"}

GRAIN = "Cada fila es una sede por ítem de capacidad instalada (sede × ítem de capacidad)."
DEFINITIONS = {
    "ips": "COUNT(DISTINCT codigo_prestador)",
    "sedes": "COUNT(DISTINCT sede_id)",
}
COUNTING_GUIDANCE = ("Para saber cuántas IPS hay se cuentan prestadores distintos "
                     "(COUNT(DISTINCT codigo_prestador)), nunca filas.")


def _q(cur: duckdb.DuckDBPyConnection, sql: str) -> list[tuple]:
    return cur.execute(sql).fetchall()


def compute_profile(cur: duckdb.DuckDBPyConnection, *, source: str | None,
                    fecha_corte: str | None) -> dict:
    rows = _q(cur, "SELECT count(*) FROM ips")[0][0]
    cols = _q(cur, "SELECT column_name, data_type FROM information_schema.columns "
                   "WHERE table_name = 'ips' ORDER BY ordinal_position")

    # Una sola pasada para nulos y cardinalidad de todas las columnas.
    agg = ", ".join(f'count(*) - count("{c}"), count(DISTINCT "{c}")' for c, _ in cols)
    flat = _q(cur, f"SELECT {agg} FROM ips")[0]
    columns = []
    for i, (name, dtype) in enumerate(cols):
        nulls, distinct = flat[2 * i], flat[2 * i + 1]
        col = {"name": name, "type": dtype, "nulls": nulls,
               "null_pct": round(100 * nulls / rows, 1) if rows else 0.0, "distinct": distinct}
        if distinct > 0 and not name.endswith("_norm") and name not in NO_VALUES_COLUMNS:
            complete = distinct <= MAX_CATEGORICAL
            limit = "" if complete else f" LIMIT {TOP_N}"
            col["values_complete"] = complete  # True: todos los valores; False: solo los TOP_N principales
            col["values"] = [
                {"value": v if isinstance(v, (str, int, float)) else str(v), "count": n}
                for v, n in _q(
                    cur, f'SELECT "{name}", count(*) AS n FROM ips WHERE "{name}" IS NOT NULL '
                         f'GROUP BY 1 ORDER BY n DESC, 1{limit}')
            ]
        columns.append(col)

    ips, sedes = _q(cur, "SELECT count(DISTINCT codigo_prestador), count(DISTINCT sede_id) FROM ips")[0]
    naturaleza = {k: n for k, n in _q(
        cur, "SELECT naturaleza, count(*) FROM ips WHERE naturaleza IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1")}

    nivel_null = next(c for c in columns if c["name"] == "nivel_atencion")
    nivel_by_nat = {k: n for k, n in _q(
        cur, "SELECT lower(strip_accents(naturaleza)), count(*) FROM ips "
             "WHERE nivel_atencion IS NOT NULL GROUP BY 1")}
    publica, privada = nivel_by_nat.get("publica", 0), nivel_by_nat.get("privada", 0)
    notes = [
        f"nivel_atencion es nulo en {nivel_null['nulls']} filas ({round(nivel_null['null_pct'])} %) y es "
        f"prácticamente exclusivo de IPS públicas: {publica} filas públicas con nivel y "
        f"{privada} privada(s) con nivel.",
    ]
    return {
        "grain": GRAIN,
        "definitions": DEFINITIONS,
        "counting_guidance": COUNTING_GUIDANCE,
        "rows": rows,
        "ips_distintas": ips,
        "sedes_distintas": sedes,
        "columns": columns,
        "coverage": {
            "nivel_atencion": {"null_rows": nivel_null["nulls"], "null_pct": nivel_null["null_pct"],
                               "rows_with_level_publica": publica, "rows_with_level_privada": privada},
            "notes": notes,
        },
        "naturaleza": naturaleza,
        "fecha_corte": fecha_corte,
        "source": source,
    }
