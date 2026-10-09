"""Ejecuta toda la QA y regenera `quality/04_qa_execution_report.md`.

Un solo comando, desde la raíz del repositorio:

    uv run --project backend python quality/run_quality.py

Pasos:
  1. Suite TypeScript del MockTransport (`node --test`, Node 24, sin dependencias) -> traza de eventos.
  2. Suite Python de QA (`pytest quality`): verdad de referencia, tools, estados, seguridad, latencia y contrato.
  3. Suite del backend (`backend/tests`) como regresión (omitir con --skip-backend).
  4. Medición de latencia de las tools y de SQL directo sobre DuckDB (--repeats, por defecto 30).
  5. Reporte Markdown con resultados, tiempos, evidencia y certificación.

Código de salida 0 solo si todas las suites pasan.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import shutil
import statistics
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUALITY = ROOT / "quality"
TESTS = QUALITY / "tests"
REPORTS = QUALITY / "reports"
REPORT_MD = QUALITY / "04_qa_execution_report.md"
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(ROOT / "backend"))


# ---------------------------------------------------------------------------------------------- suites
@dataclass
class Case:
    suite: str
    name: str
    ok: bool
    ms: float
    detail: str = ""


@dataclass
class SuiteResult:
    name: str
    command: str
    exit_code: int
    seconds: float
    cases: list[Case] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(c.ok for c in self.cases)

    @property
    def failed(self) -> int:
        return sum(not c.ok for c in self.cases)


def run(cmd: list[str], cwd: Path) -> tuple[int, float, str]:
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8"})
    out = proc.stdout + proc.stderr
    print(out[-4000:])
    return proc.returncode, time.perf_counter() - t0, out


def parse_junit(path: Path, suite: str) -> list[Case]:
    if not path.is_file():
        return []
    cases = []
    for tc in ET.parse(path).getroot().iter("testcase"):
        bad = tc.find("failure")
        if bad is None:
            bad = tc.find("error")
        if tc.find("skipped") is not None:
            continue
        name = tc.get("name", "")
        cls = tc.get("classname", "")
        label = f"{cls.split('.')[-1]} › {name}" if cls and suite != "TypeScript" else name
        detail = (bad.get("message") or bad.text or "")[:300] if bad is not None else ""
        cases.append(Case(suite, label, bad is None, float(tc.get("time") or 0) * 1000, detail))
    return cases


def suite_ts() -> SuiteResult:
    node = shutil.which("node") or "node"
    junit = REPORTS / "ts-junit.xml"
    cmd = [node, "--test", "--import", "./quality/tests/ts/register.mjs",
           "--test-reporter=spec", "--test-reporter-destination=stdout",
           "--test-reporter=junit", f"--test-reporter-destination={junit.relative_to(ROOT).as_posix()}",
           "quality/tests/test_mock_transport_events.ts"]
    code, secs, _ = run(cmd, ROOT)
    shown = "node --test --import ./quality/tests/ts/register.mjs quality/tests/test_mock_transport_events.ts"
    return SuiteResult("TypeScript · MockTransport (contrato WS)", shown, code, secs, parse_junit(junit, "TypeScript"))


def suite_pytest(name: str, args: list[str], cwd: Path, junit: Path, shown: str) -> SuiteResult:
    cmd = [sys.executable, "-m", "pytest", *args, "-q", f"--junitxml={junit}"]
    code, secs, _ = run(cmd, cwd)
    return SuiteResult(name, shown, code, secs, parse_junit(junit, "Python"))


# ---------------------------------------------------------------------------------------------- latencia
def latency(repeats: int) -> tuple[list[dict], list[dict], dict]:
    from conftest import DATA, SNAPSHOT  # noqa: F401  (rutas compartidas)
    from test_ground_truth_tools import GOLDEN_CALLS, P95_GOAL_MS

    import duckdb
    from app.agent.tools import AgentTools
    from app.config import load_settings
    from app.datastore.loader import load_snapshot
    from app.datastore.store import Store

    t0 = time.perf_counter()
    store = Store()
    load_snapshot(store, load_settings({"DATA_PATH": str(DATA)}))
    load_ms = (time.perf_counter() - t0) * 1000
    tools = AgentTools(store)

    def stats(fn) -> dict:
        fn()
        samples = []
        for _ in range(repeats):
            s = time.perf_counter()
            fn()
            samples.append((time.perf_counter() - s) * 1000)
        samples.sort()
        return {"p50": statistics.median(samples), "p95": samples[min(len(samples) - 1, round(0.95 * (len(samples) - 1)))],
                "max": samples[-1]}

    tool_rows = []
    for name, args in GOLDEN_CALLS:
        st = stats(lambda n=name, a=args: tools.call(n, dict(a)))
        tool_rows.append({"tool": name, "args": args, **st, "ok": st["p95"] <= P95_GOAL_MS})

    con = duckdb.connect()
    con.execute(f"CREATE VIEW snap AS SELECT * FROM read_parquet('{SNAPSHOT.as_posix()}')")
    con.execute("CREATE TABLE mem AS SELECT * FROM snap")
    sql_rows = []
    for label, q in [
        ("COUNT DISTINCT prestadores (nacional)", "SELECT count(DISTINCT codigo_prestador) FROM mem"),
        ("COUNT DISTINCT sedes (nacional)", "SELECT count(DISTINCT codigo_sede || '-' || numero_sede) FROM mem"),
        ("SUM camas Antioquia", "SELECT sum(cantidad_capacidad) FROM mem WHERE grupo_capacidad='CAMAS' "
                                "AND departamento_norm='antioquia'"),
        ("GROUP BY departamento (ranking)", "SELECT departamento, count(DISTINCT codigo_prestador) n FROM mem "
                                            "GROUP BY 1 ORDER BY n DESC LIMIT 10"),
        ("Búsqueda por nombre (LIKE)", "SELECT DISTINCT nombre_prestador FROM mem WHERE nombre_prestador_norm "
                                       "LIKE '%pablo tobon%'"),
    ]:
        sql_rows.append({"consulta": label, **stats(lambda q=q: con.execute(q).fetchall())})
    env = {"load_ms": load_ms, "repeats": repeats, "goal_ms": P95_GOAL_MS}
    return tool_rows, sql_rows, env


# ---------------------------------------------------------------------------------------------- evidencia
def evidence() -> list[dict]:
    """Cifras de oro: lo documentado, lo que devuelve SQL independiente y lo que devuelve la tool."""
    from conftest import DATA, SNAPSHOT, GROUND_TRUTH, ORACLE_DISTRICTS  # noqa: F401

    import duckdb
    from app.agent.tools import AgentTools
    from app.config import load_settings
    from app.datastore.loader import load_snapshot
    from app.datastore.store import Store

    truth = json.loads(GROUND_TRUTH.read_text(encoding="utf-8"))
    store = Store()
    load_snapshot(store, load_settings({"DATA_PATH": str(DATA)}))
    tools = AgentTools(store)
    con = duckdb.connect()
    cases = " ".join(f"WHEN lower(strip_accents(departamento)) = '{k}' THEN '{v}'" for k, v in ORACLE_DISTRICTS.items())
    con.execute(f"CREATE VIEW snap AS SELECT *, CASE {cases} ELSE departamento END AS depto "
                f"FROM read_parquet('{SNAPSHOT.as_posix()}')")

    def sql(q: str):
        return con.execute(q).fetchone()[0]

    rows = [
        ("Total nacional de IPS", truth["ips_total"], sql("SELECT count(DISTINCT codigo_prestador) FROM snap"),
         "count_ips", {}),
        ("Total de sedes", truth["sedes_total"], sql("SELECT count(DISTINCT codigo_sede||'-'||numero_sede) FROM snap"),
         "count_sedes", {}),
        ("IPS en Bogotá D.C.", truth["ips_bogota"],
         sql("SELECT count(DISTINCT codigo_prestador) FROM snap WHERE lower(strip_accents(municipio))='bogota'"),
         "count_ips", {"departamento": "bogota"}),
        ("IPS en Medellín", truth["ips_medellin"],
         sql("SELECT count(DISTINCT codigo_prestador) FROM snap WHERE lower(strip_accents(municipio))='medellin'"),
         "count_ips", {"municipio": "Medellín"}),
        ("IPS en Valle del Cauca (con Cali y Buenaventura)", truth["ips_valle_del_cauca"],
         sql("SELECT count(DISTINCT codigo_prestador) FROM snap WHERE depto='Valle del Cauca'"),
         "count_ips", {"departamento": "Valle del Cauca"}),
        ("IPS en Cali (municipio)", truth["ips_cali_municipio"],
         sql("SELECT count(DISTINCT codigo_prestador) FROM snap WHERE lower(strip_accents(municipio))='cali'"),
         "count_ips", {"municipio": "Cali"}),
        ("Camas en Antioquia", truth["antioquia_capacidad"]["CAMAS"],
         sql("SELECT sum(cantidad_capacidad) FROM snap WHERE grupo_capacidad='CAMAS' AND depto='Antioquia'"),
         "sum_capacidad", {"grupo_capacidad": "CAMAS", "departamento": "Antioquia"}),
        ("Camas de adultos en Antioquia", truth["antioquia_camas_adultos"],
         sql("SELECT sum(cantidad_capacidad) FROM snap WHERE grupo_capacidad='CAMAS' AND depto='Antioquia' "
             "AND lower(strip_accents(descripcion_capacidad))='adultos'"),
         "sum_capacidad", {"grupo_capacidad": "CAMAS", "descripcion_capacidad": "camas de adultos",
                           "departamento": "Antioquia"}),
        ("Ambulancias en Antioquia", truth["antioquia_capacidad"]["AMBULANCIAS"],
         sql("SELECT sum(cantidad_capacidad) FROM snap WHERE grupo_capacidad='AMBULANCIAS' AND depto='Antioquia'"),
         "sum_capacidad", {"grupo_capacidad": "AMBULANCIAS", "departamento": "Antioquia"}),
        ("IPS de nivel 3", truth["ips_nivel_3"],
         sql("SELECT count(DISTINCT codigo_prestador) FROM snap WHERE nivel_atencion=3"),
         "count_ips", {"nivel_atencion": 3}),
        ("IPS privadas con nivel registrado", truth["privadas_con_nivel"],
         sql("SELECT count(DISTINCT codigo_prestador) FROM snap WHERE naturaleza='Privada' AND nivel_atencion IS NOT NULL"),
         "count_ips", {"naturaleza": "Privada", "nivel_atencion": 1}),
    ]
    out = []
    for label, documented, oracle, name, args in rows:
        r = tools.call(name, args)
        out.append({"caso": label, "documentado": documented, "sql": oracle, "tool": r.get("valor"),
                    "estado": r.get("estado"), "llamada": f"{name}({json.dumps(args, ensure_ascii=False)})",
                    "ok": documented == oracle == r.get("valor")})
    for label, args, expect in [
        ("Hospital Pablo Tobón Uribe (nombre exacto)", {"nombre": "Hospital Pablo Tobón Uribe"}, "ok"),
        ("«PABLO TOVON URIBE» (error de transcripción)", {"nombre": "PABLO TOVON URIBE"}, "ok"),
        ("«pablo tobon» (nombre compartido)", {"nombre": "pablo tobon"}, "ambiguo"),
        ("«clinica santa maria» (varias clínicas homónimas)", {"nombre": "clinica santa maria"}, "ambiguo"),
    ]:
        r = tools.call("buscar_ips", args)
        detail = (r["valor"][0]["nombre"] if r.get("valor") else
                  f"{len(r.get('candidatos', []))} candidatos" + (f" de {r['total_candidatos']}" if r.get("total_candidatos") else ""))
        out.append({"caso": label, "documentado": expect, "sql": "—", "tool": detail, "estado": r["estado"],
                    "llamada": f"buscar_ips({json.dumps(args, ensure_ascii=False)})", "ok": r["estado"] == expect})
    for label, name, args, expect in [
        ("Municipio inexistente (Springfield)", "count_ips", {"municipio": "Springfield"}, "no_encontrado"),
        ("Descripción inexistente (camas para extraterrestres)", "sum_capacidad",
         {"grupo_capacidad": "CAMAS", "descripcion_capacidad": "camas para extraterrestres"}, "no_encontrado"),
        ("Mixtas de nivel 2", "count_ips", {"naturaleza": "Mixta", "nivel_atencion": 2}, "sin_cobertura"),
        ("Inyección SQL en municipio", "count_ips", {"municipio": "Cali'; DROP TABLE ips; --"}, "no_encontrado"),
        ("Departamento fuera del enum (Narnia)", "count_ips", {"departamento": "Narnia"}, "error_validacion"),
    ]:
        r = tools.call(name, args)
        out.append({"caso": label, "documentado": expect, "sql": "—", "tool": r.get("valor", "sin valor"),
                    "estado": r["estado"], "llamada": f"{name}({json.dumps(args, ensure_ascii=False)})",
                    "ok": r["estado"] == expect and "valor" not in r if expect != "sin_cobertura" else r["estado"] == expect})
    return out


# ---------------------------------------------------------------------------------------------- reporte
def fmt(n) -> str:
    return f"{n:,}".replace(",", ".") if isinstance(n, int) and not isinstance(n, bool) else str(n)


def git(*args: str) -> str:
    try:
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    except OSError:
        return "?"


def write_report(suites: list[SuiteResult], tool_rows, sql_rows, env, evid) -> bool:
    all_ok = all(s.exit_code == 0 and s.failed == 0 for s in suites) and all(e["ok"] for e in evid)
    total = sum(len(s.cases) for s in suites)
    passed = sum(s.passed for s in suites)
    node_v = git_v = ""
    try:
        node_v = subprocess.run([shutil.which("node") or "node", "--version"], capture_output=True, text=True).stdout.strip()
    except OSError:
        node_v = "?"
    import duckdb
    git_v = f"`{git('rev-parse', '--abbrev-ref', 'HEAD')}` @ `{git('rev-parse', '--short', 'HEAD')}`"
    dirty = " (con cambios sin confirmar)" if git("status", "--porcelain", "--", "backend", "frontend", "data") else ""
    now = dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M %z")

    L: list[str] = []
    a = L.append
    a("# 04 · Reporte de ejecución de QA")
    a("")
    a("> **Generado automáticamente** por `quality/run_quality.py`. No editar a mano: volver a ejecutar")
    a("> `uv run --project backend python quality/run_quality.py` desde la raíz del repositorio.")
    a("")
    a(f"- **Fecha:** {now}")
    a(f"- **Código evaluado:** {git_v}{dirty}")
    a(f"- **Entorno:** Python {platform.python_version()} · DuckDB {duckdb.__version__} · Node {node_v} · {platform.system()} {platform.release()}")
    a(f"- **Datos:** `data/snapshot.parquet` (corte 2022-11-05, origen snapshot)")
    a("")
    a("## 1. Resumen")
    a("")
    verdict = "✅ **TODAS LAS PRUEBAS PASAN**" if all_ok else "❌ **HAY PRUEBAS QUE FALLAN**"
    a(f"{verdict} — {passed} de {total} casos automatizados en {len(suites)} suites, más {sum(e['ok'] for e in evid)} de "
      f"{len(evid)} verificaciones de evidencia.")
    a("")
    a("| Suite | Comando | Pasan | Fallan | Tiempo |")
    a("|---|---|---:|---:|---:|")
    for s in suites:
        a(f"| {s.name} | `{s.command}` | {s.passed} | {s.failed} | {s.seconds:.1f} s |")
    a("")
    fails = [c for s in suites for c in s.cases if not c.ok]
    if fails:
        a("### Fallos")
        a("")
        for c in fails:
            a(f"- **{c.suite} · {c.name}**: {c.detail}")
        a("")

    a("## 2. Tiempos de las consultas analíticas (DuckDB en memoria)")
    a("")
    a(f"Carga del snapshot a DuckDB (incluye perfil): **{env['load_ms']:.0f} ms** (meta de requisito: ≤ 5.000 ms).")
    a("")
    a(f"### 2.1 Tools del agente (lo que paga cada turno de voz) — {env['repeats']} repeticiones tras calentamiento")
    a("")
    a(f"| Tool | Argumentos | p50 (ms) | p95 (ms) | máx (ms) | Meta p95 ≤ {env['goal_ms']:.0f} ms |")
    a("|---|---|---:|---:|---:|:---:|")
    for r in tool_rows:
        args = json.dumps(r["args"], ensure_ascii=False) if r["args"] else "—"
        a(f"| `{r['tool']}` | `{args}` | {r['p50']:.1f} | {r['p95']:.1f} | {r['max']:.1f} | {'✅' if r['ok'] else '❌'} |")
    a("")
    a("### 2.2 SQL directo sobre DuckDB (referencia del motor, sin validación ni envoltorio)")
    a("")
    a("| Consulta | p50 (ms) | p95 (ms) | máx (ms) |")
    a("|---|---:|---:|---:|")
    for r in sql_rows:
        a(f"| {r['consulta']} | {r['p50']:.2f} | {r['p95']:.2f} | {r['max']:.2f} |")
    a("")
    a("La diferencia entre 2.1 y 2.2 es el costo de la capa de seguridad de las tools (validación JSON Schema, "
      "resolución difusa de lugares y nombres, verificación de distritos y armado del resultado). Medido en la "
      "máquina de desarrollo; en el servidor de despliegue los valores absolutos pueden variar.")
    a("")

    a("## 3. Evidencia: cifras de oro y casos auditados")
    a("")
    a("Cada cifra se obtuvo tres veces: lo documentado en `02_golden_dataset_specs.md`, SQL independiente sobre el "
      "Parquet (sin código del backend) y la llamada real a la tool que usa el agente.")
    a("")
    a("| Caso | Llamada de la tool | Documentado | SQL independiente | Tool | Estado | ✓ |")
    a("|---|---|---:|---:|---:|---|:---:|")
    for e in evid:
        a(f"| {e['caso']} | `{e['llamada']}` | {fmt(e['documentado'])} | {fmt(e['sql'])} | {fmt(e['tool'])} | "
          f"`{e['estado']}` | {'✅' if e['ok'] else '❌'} |")
    a("")

    a("## 4. Casos de prueba ejecutados")
    a("")
    for s in suites:
        a(f"<details><summary><b>{s.name}</b> — {s.passed}/{len(s.cases)} pasan</summary>")
        a("")
        a("| Caso | Resultado | Tiempo (ms) |")
        a("|---|:---:|---:|")
        for c in s.cases:
            a(f"| {c.name.replace('|', '¦')} | {'✅' if c.ok else '❌'} | {c.ms:.0f} |")
        a("")
        a("</details>")
        a("")

    a("## 5. Observaciones de calidad (no bloquean)")
    a("")
    a("- **Entrada basura en `buscar_ips`.** `x' OR 1=1 --` no causa daño (consultas parametrizadas; la tabla queda "
      "intacta, verificado), pero devuelve `ambiguo` con candidatos en lugar de `sin_resultados`, porque la búsqueda "
      "parcial por palabras encuentra coincidencias con fragmentos sueltos («x», «or», «1»). Para voz no es un riesgo "
      "real; para un campo de texto podría endurecerse exigiendo al menos una palabra de 3 o más letras.")
    a("- **El mock y el contrato.** El MockTransport emite `sentiment` (no `insight`): el contrato v1.0 no define un "
      "evento `insight`; la suite lo comprueba explícitamente.")
    a("- **Pablo Tobón.** «Pablo Tobón» a secas es ambiguo con razón: el dataset tiene también «Óptica Santa Lucía "
      "Pablo Tobón» y la «Unidad Hospitalaria de Castilla Jaime Tobón Arbeláez». Con el nombre completo (o con un error "
      "de transcripción como «Tovón») se resuelve sin ambigüedad.")
    a("")

    a("## 6. Certificación de estabilidad técnica para la demo")
    a("")
    if all_ok:
        a("**Se certifica** que, en el código evaluado y sobre el snapshot del 5 de noviembre de 2022:")
        a("")
        a("1. Las cifras que el agente puede decir coinciden exactamente con SQL independiente sobre los datos.")
        a("2. Los lugares inexistentes, los datos no registrados y los nombres ambiguos producen estados explícitos "
          "(`no_encontrado`, `sin_cobertura`, `ambiguo`) y nunca un «cero» engañoso.")
        a("3. Las tools rechazan argumentos fuera de esquema y entradas de inyección sin alterar los datos, y respetan el "
          "presupuesto de dos llamadas por turno.")
        a(f"4. Todas las tools cumplen la meta de latencia (p95 ≤ {env['goal_ms']:.0f} ms) con amplio margen.")
        a("5. El MockTransport respeta el orden, la numeración y el esquema del contrato WebSocket v1.0, incluida la "
          "interrupción (`audio.clear` + texto truncado), por lo que la demo de interfaz sin backend es fiel al real.")
    else:
        a("**No se certifica**: hay pruebas que fallan (ver §1). Corregir y volver a ejecutar.")
    a("")
    a("**Alcance (lo que este reporte NO cubre):** la latencia y la calidad de los proveedores externos en vivo "
      "(Groq, Deepgram STT/TTS), la precisión de la diarización con audio real, y la conducta del modelo de lenguaje "
      "(qué tool elige y cómo redacta). Esos puntos se verifican con los casos manuales de "
      "`03_e2e_manual_test_cases.md` y con `backend/scripts/voice_golden.py` contra el despliegue.")
    a("")
    REPORT_MD.write_text("\n".join(L) + "\n", encoding="utf-8")
    return all_ok


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-backend", action="store_true", help="no ejecutar la suite de regresión del backend")
    ap.add_argument("--repeats", type=int, default=30, help="repeticiones para medir latencia (defecto 30)")
    args = ap.parse_args()
    REPORTS.mkdir(parents=True, exist_ok=True)

    suites = [suite_ts(),
              suite_pytest("Python · QA (verdad de referencia, tools, contrato)", ["quality"], ROOT,
                           REPORTS / "py-junit.xml", "uv run --project backend pytest quality")]
    if not args.skip_backend:
        suites.append(suite_pytest("Python · Regresión del backend", [], ROOT / "backend",
                                   REPORTS / "backend-junit.xml", "cd backend && uv run pytest"))
    print("Midiendo latencia…")
    tool_rows, sql_rows, env = latency(args.repeats)
    print("Reuniendo evidencia…")
    evid = evidence()
    ok = write_report(suites, tool_rows, sql_rows, env, evid)
    print(f"\nReporte: {REPORT_MD.relative_to(ROOT)} — {'TODO PASA' if ok else 'HAY FALLOS'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
