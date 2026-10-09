# quality/ — QA del Agente Vocal Cognitivo

Pruebas y documentación de calidad. No modifica código de producción: prueba `backend/app` y `frontend/src` desde fuera.

## Un solo comando (desde la raíz del repo)

```bash
uv run --project backend python quality/run_quality.py
```

Ejecuta la suite TypeScript del `MockTransport`, la suite Python de QA, la regresión del backend, mide la latencia y
regenera [`04_qa_execution_report.md`](04_qa_execution_report.md). Sale con código 0 solo si todo pasa.
Opciones: `--skip-backend` (sin la regresión del backend, ~2 min menos) y `--repeats N`.

Requisitos: [uv](https://docs.astral.sh/uv/) (instala Python y dependencias con `cd backend && uv sync`) y Node 24.

## Suites por separado

```bash
uv run --project backend pytest quality                    # verdad de referencia, tools, estados, seguridad, latencia, contrato
uv run --project backend pytest quality -m cifras          # solo las cifras de oro (marcas: integridad, cifras, busqueda, estados, seguridad, latencia, contrato)
node --test --import ./quality/tests/ts/register.mjs quality/tests/test_mock_transport_events.ts   # contrato del MockTransport
```

## Contenido

| Archivo | Qué es |
|---|---|
| [`01_qa_strategy_and_matrix.md`](01_qa_strategy_and_matrix.md) | Estrategia, taxonomía, criterios de aceptación y trazabilidad requisito → prueba |
| [`02_golden_dataset_specs.md`](02_golden_dataset_specs.md) | Verdad de referencia: preguntas de oro, tools esperadas y cifras exactas del snapshot |
| [`03_e2e_manual_test_cases.md`](03_e2e_manual_test_cases.md) | Casos manuales en la interfaz (zen, manos libres, drawers, telemetría, voz real) |
| [`04_qa_execution_report.md`](04_qa_execution_report.md) | Reporte generado: resultados, tiempos, evidencia y certificación |
| `tests/ground_truth.json` | Cifras de oro (las mismas del documento 02) |
| `tests/test_ground_truth_tools.py` | Tools frente a SQL independiente sobre `data/snapshot.parquet` |
| `tests/test_mock_transport_events.ts` | Secuencias del `MockTransport` frente al contrato WS v1.0 (Node, relojes simulados) |
| `tests/test_mock_trace_schema.py` | Cada evento del mock validado contra `backend/contract/ws-events.schema.json` |
| `tests/ts/` | Resolución del alias `@/` para ejecutar el TypeScript del frontend con Node sin dependencias |
| `reports/mock_events_trace.json` | Traza de eventos del mock (evidencia; la regenera la suite TS) |
