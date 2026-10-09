# 01 · Estrategia de QA y matriz de pruebas

> Componente formal de calidad del Agente Vocal Cognitivo (Ivy). Todo el material vive en `quality/` y **no modifica
> código de producción** (`backend/app/`, `frontend/src/`): lo prueba desde fuera.

## 1. Objetivo

Demostrar ante el jurado, con evidencia reproducible, tres cosas:

1. **Exactitud:** toda cifra que el agente puede decir coincide con los datos (`data/snapshot.parquet`, corte 5 de
   noviembre de 2022).
2. **Honestidad y robustez:** ante datos ausentes, lugares inexistentes, nombres ambiguos o entradas maliciosas, el
   sistema responde con un estado explícito y nunca con un «cero» engañoso ni con un error.
3. **Fidelidad del contrato:** la interfaz (y su modo demo sin backend) habla el mismo protocolo WebSocket v1.0 que el
   servidor real, incluidas las interrupciones (*barge-in*).

## 2. Principios

- **Oráculo independiente.** Las cifras se verifican con SQL escrito en la suite, leyendo el Parquet directamente y
  con su propio mapeo de distritos. No se reutiliza código del backend para calcular lo esperado: un error del backend
  no puede autovalidarse.
- **Triple verificación.** Cada cifra de oro se compara en tres fuentes: lo documentado
  (`02_golden_dataset_specs.md` / `tests/ground_truth.json`), el SQL independiente y la salida real de la tool.
- **Pruebas deterministas.** Sin red ni claves: el backend se carga con el snapshot y el `MockTransport` corre con
  relojes simulados (`node:test` `mock.timers`).
- **El contrato es la fuente de verdad.** Los eventos del mock se validan con `jsonschema` contra
  `backend/contract/ws-events.schema.json`, generado desde los modelos Pydantic del servidor.
- **Un solo comando** regenera todo y el reporte (`04_qa_execution_report.md`).

## 3. Taxonomía de pruebas

| Nivel | Tipo | Dónde | Automatizada |
|---|---|---|:---:|
| Datos | Integridad del snapshot (filas, corte, claves de sede, departamentos canónicos) | `tests/test_ground_truth_tools.py` · marca `integridad` | ✅ |
| Unidad / integración | Cifras de oro: tools contra SQL independiente | `test_ground_truth_tools.py` · `cifras` | ✅ |
| Unidad / integración | Búsqueda por nombre: tildes, mayúsculas, errores de transcripción, ambigüedad | `test_ground_truth_tools.py` · `busqueda` | ✅ |
| Unidad / integración | Estados del contrato de resultado (`ok`, `sin_resultados`, `no_encontrado`, `ambiguo`, `sin_cobertura`) | `test_ground_truth_tools.py` · `estados` | ✅ |
| Seguridad | Argumentos fuera de esquema, tool inexistente, inyección SQL, presupuesto de llamadas | `test_ground_truth_tools.py` · `seguridad` | ✅ |
| Rendimiento | p95 por tool frente a la meta de 200 ms; SQL directo como referencia | `test_ground_truth_tools.py` · `latencia` + `run_quality.py` | ✅ |
| Contrato | Secuencias y semántica del `MockTransport` (brief, turnos, barge-in, pausa, cierre) | `tests/test_mock_transport_events.ts` | ✅ |
| Contrato | Cada evento del mock valida contra el JSON Schema del backend | `tests/test_mock_trace_schema.py` · `contrato` | ✅ |
| Regresión | Suite completa del backend (contrato WS, relé, voz por etapas, límites, sentimiento) | `backend/tests` vía `run_quality.py` | ✅ |
| Sistema (E2E) | Experiencia en la interfaz: zen, manos libres, drawers, telemetría | `03_e2e_manual_test_cases.md` | Manual |
| Sistema (E2E) | Voz real con proveedores (Groq, Deepgram) y latencia en el despliegue | `backend/scripts/voice_golden.py`, `scripts/e2e_local.sh` | Fuera de esta suite |

## 4. Criterios de aceptación

| ID | Criterio | Umbral | Verificación |
|---|---|---|---|
| CA-01 | Exactitud numérica | **100 %** de coincidencia (sin tolerancia) entre documentado, SQL y tool | `cifras`, §3 del reporte |
| CA-02 | IPS = prestadores distintos | `count_ips` sin filtros = 9.320, nunca 41.427 filas | `test_a_total_nacional_ips` |
| CA-03 | Distritos especiales | Valle del Cauca = 813 con `incluye_distritos` = Buenaventura y Cali; Cali como municipio = 491 | `test_b_valle_*`, `test_b_cali_*` |
| CA-04 | Sin ceros engañosos | Lugar o descripción inexistente → `no_encontrado` **sin** `valor`; nivel de atención en privadas/mixtas → `sin_cobertura` | `estados` |
| CA-05 | Ambigüedad | Nombres compartidos → `ambiguo` con 2 a 10 candidatos y sin `valor` | `busqueda` |
| CA-06 | Búsqueda tolerante | Mayúsculas, sin tildes y errores de transcripción («Tovón») encuentran la IPS correcta | `test_d_pablo_tobon_unico` |
| CA-07 | Grounding del contacto | Dirección y teléfono devueltos existen en el dataset para ese prestador | `test_d_pablo_tobon_devuelve_contacto_real` |
| CA-08 | Seguridad | Todo argumento fuera de esquema → `error_validacion` sin consultar; la inyección no altera la tabla | `seguridad` |
| CA-09 | Presupuesto de llamadas | Máximo 2 tools por turno; la tercera → `limite_llamadas` | `test_s_presupuesto_*` |
| CA-10 | Latencia de datos | p95 de cada tool ≤ **200 ms** (requisito de `agent-tools`) | `latencia`, §2 del reporte |
| CA-11 | Arranque | Carga del snapshot ≤ **5 s** | §2 del reporte |
| CA-12 | Contrato WS | 100 % de los eventos del mock validan contra el esquema; `v = 1`; `seq` estrictamente creciente | `contrato`, suite TS |
| CA-13 | Barge-in | Al interrumpir mientras habla: `audio.clear` → `agent.text` final con `interrupted: true` y texto truncado → `escuchando`; ningún audio ni texto tardío de ese turno | suite TS «Interrupciones» |
| CA-14 | Latencia percibida | `metrics` permite calcular `vad_silence_ms + first_audio_ms` (1.620 ms en el ejemplo del contrato) | suite TS «metrics» |
| CA-15 | Experiencia | Casos manuales E2E-01 a E2E-12 aprobados | `03_e2e_manual_test_cases.md` |

## 5. Matriz de trazabilidad (requisito → prueba)

| Requisito (OpenSpec) | Escenario | Prueba |
|---|---|---|
| `agent-tools` · Tools de conteo y suma | Conteo de IPS = 9.320; sedes = 15.547 | `test_a_total_nacional_ips`, `test_a_total_nacional_sedes` |
| `agent-tools` · Departamento canónico | Valle con distritos; Antioquia sin distritos | `test_b_valle_incluye_distritos`, `test_b_antioquia_sin_distritos` |
| `agent-tools` · Resolución de la descripción | «adultos» exacta; «cuidado intensivo» ambigua; inexistente | `test_c_camas_adultos_antioquia`, `test_e_descripcion_ambigua`, `test_e_descripcion_inexistente` |
| `agent-tools` · Búsqueda por nombre | Tildes/mayúsculas; varios candidatos; sin coincidencias | `test_d_*` |
| `agent-tools` · Lugares inexistentes | Municipio inexistente sin valor | `test_e_lugar_inexistente_no_devuelve_cero` |
| `agent-tools` · Cobertura de nivel | Privada nivel 1 → `sin_cobertura` (1 observada) | `test_e_privada_nivel_1_sin_cobertura` |
| `agent-tools` · Formato común / tope de 10 | Envoltorio y listas acotadas | `test_e_envoltorio_comun`, `test_e_listas_acotadas_a_10` |
| `agent-tools` · Argumentos validados | Enum inválido, campo desconocido | `test_s_argumentos_fuera_de_esquema` |
| `agent-tools` · Presupuesto y latencia | 3.ª llamada rechazada; p95 ≤ 200 ms | `test_s_presupuesto_*`, `test_l_p95_*` |
| `soda-dataset-ingestion` · Snapshot | 41.427 filas, 15.547 sedes, sin conflictos de nombre | `test_snapshot_*`, `test_store_carga_igual_que_el_parquet` |
| `ws-event-contract` · Versión y estructura | `v`, `seq`, protocolo 1.0 | suite TS «Estructura», «protocolo» |
| `ws-event-contract` · Brief por evento | `session.brief` en `t-0000` con 3 a 5 preguntas | suite TS «session.brief» |
| `ws-event-contract` · Transcripción | parcial y final con mismo `utt_id`; `ts_end ≥ ts` | suite TS «parcial y final» |
| `ws-event-contract` · Evidencia de tools | `agent.tool` running/done con `summary` | suite TS «agent.tool» |
| `ws-event-contract` · Audio y barge-in | `audio.clear`, descarte, texto interrumpido | suite TS «Interrupciones» |
| `ws-event-contract` · Sentimiento | tras el final del enunciado, `score` en [-1, 1] | suite TS «sentiment», `test_sentimiento_del_mock_usa_etiquetas_reales` |
| `ws-event-contract` · Reglas de orden | final → tool → audio.start → texto final → metrics | suite TS «orden» |
| `ws-event-contract` · Esquema publicado | Todo evento valida contra el esquema | `test_cada_evento_del_mock_valida_contra_el_esquema` |

## 6. Cómo se ejecuta

Desde la raíz del repositorio (requisitos: `uv`, Node 24; las dependencias del backend se instalan con `uv sync`):

```bash
# Todo + reporte (recomendado): TypeScript, QA Python, regresión del backend, latencia y reporte 04
uv run --project backend python quality/run_quality.py

# Solo la suite Python de QA
uv run --project backend pytest quality

# Solo el contrato del MockTransport (genera la traza que valida la suite Python)
node --test --import ./quality/tests/ts/register.mjs quality/tests/test_mock_transport_events.ts
```

Opciones del runner: `--skip-backend` (omite la regresión del backend, ~2 min) y `--repeats N` (muestras de latencia).

## 7. Fuera de alcance de la automatización

- Conducta del modelo de lenguaje (qué tool elige, cómo redacta): depende de Groq en vivo; ver
  `backend/app/agent/gold.py --agent` y `docs/AGENT_DIAGNOSTIC_REPORT.md`.
- Latencia real de voz y diarización con audio real: `backend/scripts/voice_golden.py` contra el despliegue.
- Percepción visual y de experiencia: casos manuales de `03_e2e_manual_test_cases.md`.
