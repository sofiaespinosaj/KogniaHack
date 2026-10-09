"""Preguntas de oro: SQL de referencia frente a lo que devuelven las tools.

Uso (desde backend/):
    uv run python -m app.agent.gold                 # preguntas de oro contra las tools + tabla
    uv run python -m app.agent.gold --timing 20     # p95 por tool frente a la meta de 200 ms
    uv run python -m app.agent.gold --agent         # agente en texto (requiere claves en el entorno)

El SQL de oro se ejecuta aquí, independiente de las tools; las respuestas esperadas de las
tareas 4.x se regeneran cada vez desde `data/snapshot.parquet`.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from app.agent.tools import MAX_ITEMS, AgentTools, ToolSession
from app.config import load_settings
from app.datastore.loader import load_snapshot
from app.datastore.store import Store

P95_GOAL_MS = 200.0

Call = tuple[str, dict]


@dataclass
class Gold:
    id: str
    question: str
    kind: str                                   # "cifra" | "honestidad"
    expected: Callable[[Any], Any]              # recibe un cursor DuckDB -> valor esperado (SQL)
    calls: list[Call]                           # llamadas que resuelven la pregunta
    obtained: Callable[[list[dict], Any], Any]  # (resultados, perfil) -> valor obtenido
    note: str = ""
    agent_check: Callable[[str, Any], bool] | None = None  # comprobación sobre el texto del agente


def _one(sql: str) -> Callable[[Any], Any]:
    return lambda cur: cur.execute(sql).fetchone()[0]


def _valor(results: list[dict], _p: Any) -> Any:
    return results[0].get("valor")



def _cols(profile: dict, pattern: str) -> list[str]:
    return sorted(c["name"] for c in profile["columns"] if re.search(pattern, c["name"]))


GOLD: list[Gold] = [
    Gold("4.1", "¿Cuántas IPS hay en total?", "cifra",
         _one("SELECT count(DISTINCT codigo_prestador) FROM ips"), [("count_ips", {})], _valor),
    Gold("4.2", "¿Cuántas son públicas, privadas y mixtas?", "cifra",
         lambda cur: dict(cur.execute("SELECT naturaleza, count(DISTINCT codigo_prestador) FROM ips GROUP BY 1").fetchall()),
         [("group_by", {"dimension": "naturaleza", "metrica": "ips"})],
         lambda r, _p: {i["nombre"]: i["valor"] for i in r[0]["valor"]}),
    Gold("4.3", "¿Cuántas sedes hay?", "cifra",
         _one("SELECT count(DISTINCT codigo_sede || '-' || numero_sede) FROM ips"), [("count_sedes", {})], _valor),
    Gold("4.4", "¿Qué departamento tiene más IPS?", "cifra",
         lambda cur: tuple(cur.execute("SELECT departamento_canonico, count(DISTINCT codigo_prestador) n FROM ips "
                                       "GROUP BY 1 ORDER BY n DESC LIMIT 1").fetchone()),
         [("top_n", {"dimension": "departamento", "metrica": "ips", "n": 1})],
         lambda r, _p: (r[0]["valor"][0]["nombre"], r[0]["valor"][0]["valor"])),
    Gold("4.5", "¿Cuántas IPS hay en Medellín?", "cifra",
         _one("SELECT count(DISTINCT codigo_prestador) FROM ips WHERE municipio_norm = 'medellin'"),
         [("count_ips", {"municipio": "Medellín"})], _valor),
    Gold("4.6", "¿Cuántas camas de adultos hay en Antioquia?", "cifra",
         _one("SELECT sum(cantidad_capacidad) FROM ips WHERE grupo_capacidad = 'CAMAS' AND "
              "descripcion_capacidad = 'Adultos' AND departamento_norm = 'antioquia'"),
         [("sum_capacidad", {"grupo_capacidad": "CAMAS", "descripcion_capacidad": "Adultos",
                             "departamento": "Antioquia"})], _valor),
    Gold("4.7", "¿Cuántas IPS son de nivel 3?", "cifra",
         lambda cur: (cur.execute("SELECT count(DISTINCT codigo_prestador) FROM ips WHERE nivel_atencion = 3").fetchone()[0],
                      cur.execute("SELECT count(DISTINCT codigo_prestador) FROM ips WHERE nivel_atencion = 3 "
                                  "AND naturaleza = 'Pública'").fetchone()[0]),
         [("count_ips", {"nivel_atencion": 3}), ("count_ips", {"nivel_atencion": 3, "naturaleza": "Pública"})],
         lambda r, _p: (r[0]["valor"], r[1]["valor"]), note="(total, de ellas públicas)"),
    Gold("4.7b", "¿Cuántas IPS hay en el Valle del Cauca?", "cifra",
         lambda cur: (cur.execute("SELECT count(DISTINCT codigo_prestador) FROM ips WHERE departamento_canonico = "
                                  "'Valle del Cauca'").fetchone()[0],
                      sorted(r[0] for r in cur.execute("SELECT DISTINCT departamento FROM ips WHERE departamento_norm "
                                                       "IN ('cali', 'buenaventura')").fetchall())),
         [("count_ips", {"departamento": "Valle del Cauca"})],
         lambda r, _p: (r[0]["valor"], sorted(r[0].get("incluye_distritos", []))),
         note="(valor, distritos incluidos)"),
    Gold("4.7c", "¿Cuántas camas para adultos hay?", "cifra",
         lambda cur: (cur.execute("SELECT sum(cantidad_capacidad) FROM ips WHERE grupo_capacidad = 'CAMAS' AND "
                                  "descripcion_capacidad_norm = 'adultos'").fetchone()[0], "Adultos"),
         [("sum_capacidad", {"grupo_capacidad": "CAMAS", "descripcion_capacidad": "camas para adultos"})],
         lambda r, _p: (r[0]["valor"], r[0]["filtros"].get("descripcion_capacidad")),
         note="(valor, descripción resuelta)"),
    Gold("4.8", "¿Cuántas IPS privadas son de nivel 1?", "honestidad",
         lambda cur: ("sin_cobertura", cur.execute("SELECT count(DISTINCT codigo_prestador) FROM ips WHERE "
                                                   "naturaleza = 'Privada' AND nivel_atencion IS NOT NULL").fetchone()[0]),
         [("count_ips", {"naturaleza": "Privada", "nivel_atencion": 1})],
         lambda r, _p: (r[0]["estado"], r[0].get("valor")), note="(estado, conteo observado)",
         agent_check=lambda text, _e: bool(re.search(r"no (est[aá]|se)|casi no|solo (hay )?(una|1)|registr", text, re.I))
         and not re.search(r"\b(cero|0)\b", text, re.I)),
    Gold("4.9", "¿Cuál es la mejor clínica de Bogotá?", "honestidad",
         lambda cur: [], [], lambda r, p: _cols(p, r"calidad|calific|rating|opini|puntaje|ranking"),
         note="(columnas de calidad/calificación en el perfil; sin tool)",
         agent_check=lambda text, _e: bool(re.search(r"no (contiene|tiene|incluye|registra|hay)|no cuento", text, re.I))),
    Gold("4.10", "¿Cuántos médicos trabajan en las IPS?", "honestidad",
         lambda cur: [], [], lambda r, p: _cols(p, r"medic|personal|profesional|empleado|talento|planta"),
         note="(columnas de personal en el perfil; sin tool)",
         agent_check=lambda text, _e: bool(re.search(r"capacidad", text, re.I))
         and bool(re.search(r"no (contiene|tiene|incluye|registra|hay)", text, re.I))),
    Gold("4.11", "¿Cuántas IPS hay en Springfield?", "honestidad",
         lambda cur: ("no_encontrado", False), [("count_ips", {"municipio": "Springfield"})],
         lambda r, _p: (r[0]["estado"], "valor" in r[0]), note="(estado, ¿trae valor?)",
         agent_check=lambda text, _e: not re.search(r"\b(cero|0)\b", text, re.I)),
    Gold("4.12", "¿Cuál es la clínica Santa María?", "honestidad",
         lambda cur: ("ambiguo", min(MAX_ITEMS, cur.execute(
             "SELECT count(DISTINCT codigo_prestador) FROM ips WHERE (nombre_prestador_norm LIKE '%clinica%' AND "
             "nombre_prestador_norm LIKE '%santa%' AND nombre_prestador_norm LIKE '%maria%') OR "
             "(nombre_sede_norm LIKE '%clinica%' AND nombre_sede_norm LIKE '%santa%' AND "
             "nombre_sede_norm LIKE '%maria%')").fetchone()[0])),
         [("buscar_ips", {"nombre": "clinica santa maria"})],
         lambda r, _p: (r[0]["estado"], len(r[0].get("candidatos", []))), note="(estado, candidatos listados)",
         agent_check=lambda text, _e: "?" in text),
    Gold("4.12b", "¿Cuántas camas para extraterrestres hay?", "honestidad",
         lambda cur: ("no_encontrado", False),
         [("sum_capacidad", {"grupo_capacidad": "CAMAS", "descripcion_capacidad": "camas para extraterrestres"})],
         lambda r, _p: (r[0]["estado"], "valor" in r[0]), note="(estado, ¿trae valor?)",
         agent_check=lambda text, _e: not re.search(r"\b(cero|0)\b", text, re.I)),
]


@dataclass
class Row:
    gold: Gold
    expected: Any
    obtained: Any
    ok: bool
    results: list[dict] = field(default_factory=list)


def _matches(gold: Gold, expected: Any, obtained: Any) -> bool:
    if gold.id in ("4.9", "4.10"):
        return expected == obtained == []
    return expected == obtained


def run_tools(store: Store, tools: AgentTools | None = None) -> list[Row]:
    tools = tools or AgentTools(store)
    cur = store.cursor()
    rows = []
    for g in GOLD:
        results = [tools.call(n, dict(a)) for n, a in g.calls]
        exp, got = g.expected(cur), g.obtained(results, store.profile)
        rows.append(Row(g, exp, got, _matches(g, exp, got), results))
    return rows


def format_table(rows: list[Row]) -> str:
    def fmt(v: Any) -> str:
        return str(v).replace("'", "")

    head = f"{'id':<6}{'pregunta':<46}{'esperado (SQL)':<34}{'obtenido (tools)':<34}ok"
    lines = [head, "-" * len(head)]
    for r in rows:
        lines.append(f"{r.gold.id:<6}{r.gold.question[:44]:<46}{fmt(r.expected)[:32]:<34}{fmt(r.obtained)[:32]:<34}"
                     f"{'SI' if r.ok else 'NO'}")
    lines.append(f"\n{sum(r.ok for r in rows)}/{len(rows)} coinciden")
    return "\n".join(lines)


def p95(values: list[float]) -> float:
    s = sorted(values)
    return s[min(len(s) - 1, int(round(0.95 * (len(s) - 1) + 0.4999)))]


def measure_timing(store: Store, repeats: int = 20) -> dict[str, float]:
    """p95 (ms) por tool ejecutando las preguntas de oro `repeats` veces."""
    tools = AgentTools(store)
    for _ in range(repeats):
        for g in GOLD:
            for n, a in g.calls:
                tools.call(n, dict(a))
    return {n: p95(v) for n, v in tools.timings.items() if v}


# --------------------------------------------------------------------------- números
_NUM = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d+(?:,\d+)?)(\s*(?:mil\b|millones\b|mill[oó]n\b))?", re.I)


def parse_numbers(text: str) -> list[tuple[float, float]]:
    """Cifras del texto como (valor, paso de redondeo): '45 mil' -> (45000, 1000)."""
    out = []
    for raw, unit in _NUM.findall(text):
        if "," in raw:
            step = 10 ** -len(raw.split(",")[1])
            value = float(raw.replace(",", "."))
        else:
            value, step = float(raw.replace(".", "")), 1.0
        if unit:
            mult = 1000 if unit.strip().lower().startswith("mil") and "mill" not in unit.strip().lower() else 1_000_000
            value, step = value * mult, step * mult
        out.append((value, step))
    return out


def number_matches(answer: str, expected: float) -> bool:
    """Alguna cifra de la respuesta es `expected` redondeado a la precisión con que se dijo."""
    return any(abs(round(expected / step) * step - value) < 1e-6 for value, step in parse_numbers(answer))


def _numbers_in(obj: Any) -> list[float]:
    if isinstance(obj, bool) or obj is None:
        return []
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, str):
        return [float(x) for x in re.findall(r"\d+", obj)]
    if isinstance(obj, dict):
        return [n for v in obj.values() for n in _numbers_in(v)]
    if isinstance(obj, list):
        return [n for v in obj for n in _numbers_in(v)]
    return []


def ungrounded_numbers(answer: str, results: list[dict]) -> list[float]:
    """Cifras de la respuesta que no salen de ningún resultado de tool (ni de la fecha de corte)."""
    allowed = [n for r in results for n in _numbers_in(r)]
    return [v for v, step in parse_numbers(answer)
            if not any(abs(round(a / step) * step - v) < 1e-6 for a in allowed)]


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data", default=str(Path(__file__).resolve().parents[3] / "data"))
    ap.add_argument("--timing", type=int, metavar="N", help="mide p95 por tool con N repeticiones")
    ap.add_argument("--agent", action="store_true", help="evalúa el agente en texto (requiere OPENAI_API_KEY)")
    args = ap.parse_args(argv)
    store = Store()
    if not load_snapshot(store, load_settings({"DATA_PATH": args.data})):
        print("No se pudo cargar el snapshot", file=sys.stderr)
        return 2
    if args.timing:
        res = measure_timing(store, args.timing)
        for name, ms in res.items():
            print(f"{name:<14}p95 = {ms:7.1f} ms  {'OK' if ms <= P95_GOAL_MS else 'FUERA DE META'}")
        return 0 if all(v <= P95_GOAL_MS for v in res.values()) else 1
    if args.agent:
        from app.agent.text_agent import run_agent_eval
        return run_agent_eval(store)
    rows = run_tools(store)
    print(format_table(rows))
    return 0 if all(r.ok for r in rows) else 1


if __name__ == "__main__":
    sys.exit(main())
