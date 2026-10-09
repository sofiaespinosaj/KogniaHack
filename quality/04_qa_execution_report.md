# 04 · Reporte de ejecución de QA

> **Generado automáticamente** por `quality/run_quality.py`. No editar a mano: volver a ejecutar
> `uv run --project backend python quality/run_quality.py` desde la raíz del repositorio.

- **Fecha:** 2026-10-09 15:38 -0500
- **Código evaluado:** `QA` @ `a358e0c`
- **Entorno:** Python 3.12.13 · DuckDB 1.5.6 · Node v24.14.0 · Windows 11
- **Datos:** `data/snapshot.parquet` (corte 2022-11-05, origen snapshot)

## 1. Resumen

✅ **TODAS LAS PRUEBAS PASAN** — 446 de 446 casos automatizados en 3 suites, más 20 de 20 verificaciones de evidencia.

| Suite | Comando | Pasan | Fallan | Tiempo |
|---|---|---:|---:|---:|
| TypeScript · MockTransport (contrato WS) | `node --test --import ./quality/tests/ts/register.mjs quality/tests/test_mock_transport_events.ts` | 20 | 0 | 0.5 s |
| Python · QA (verdad de referencia, tools, contrato) | `uv run --project backend pytest quality` | 58 | 0 | 5.2 s |
| Python · Regresión del backend | `cd backend && uv run pytest` | 368 | 0 | 109.2 s |

## 2. Tiempos de las consultas analíticas (DuckDB en memoria)

Carga del snapshot a DuckDB (incluye perfil): **294 ms** (meta de requisito: ≤ 5.000 ms).

### 2.1 Tools del agente (lo que paga cada turno de voz) — 30 repeticiones tras calentamiento

| Tool | Argumentos | p50 (ms) | p95 (ms) | máx (ms) | Meta p95 ≤ 200 ms |
|---|---|---:|---:|---:|:---:|
| `count_ips` | `—` | 3.2 | 3.5 | 3.6 | ✅ |
| `count_ips` | `{"municipio": "Medellín"}` | 3.1 | 3.4 | 4.1 | ✅ |
| `count_sedes` | `—` | 3.3 | 3.7 | 3.8 | ✅ |
| `sum_capacidad` | `{"grupo_capacidad": "CAMAS", "descripcion_capacidad": "adultos", "departamento": "Antioquia"}` | 9.8 | 11.1 | 11.2 | ✅ |
| `top_n` | `{"dimension": "departamento", "metrica": "ips", "n": 3}` | 6.5 | 10.4 | 10.8 | ✅ |
| `group_by` | `{"dimension": "naturaleza", "metrica": "ips"}` | 4.8 | 6.3 | 8.2 | ✅ |
| `listar_ips` | `{"municipio": "Manizales", "n": 3}` | 9.1 | 12.1 | 13.8 | ✅ |
| `buscar_ips` | `{"nombre": "Hospital Pablo Tobón Uribe"}` | 11.9 | 16.8 | 17.0 | ✅ |
| `buscar_ips` | `{"nombre": "clinica santa maria"}` | 27.4 | 28.9 | 30.7 | ✅ |

### 2.2 SQL directo sobre DuckDB (referencia del motor, sin validación ni envoltorio)

| Consulta | p50 (ms) | p95 (ms) | máx (ms) |
|---|---:|---:|---:|
| COUNT DISTINCT prestadores (nacional) | 2.43 | 2.65 | 2.87 |
| COUNT DISTINCT sedes (nacional) | 3.93 | 4.05 | 4.07 |
| SUM camas Antioquia | 1.00 | 1.08 | 1.19 |
| GROUP BY departamento (ranking) | 6.65 | 7.79 | 10.85 |
| Búsqueda por nombre (LIKE) | 2.00 | 2.28 | 2.32 |

La diferencia entre 2.1 y 2.2 es el costo de la capa de seguridad de las tools (validación JSON Schema, resolución difusa de lugares y nombres, verificación de distritos y armado del resultado). Medido en la máquina de desarrollo; en el servidor de despliegue los valores absolutos pueden variar.

## 3. Evidencia: cifras de oro y casos auditados

Cada cifra se obtuvo tres veces: lo documentado en `02_golden_dataset_specs.md`, SQL independiente sobre el Parquet (sin código del backend) y la llamada real a la tool que usa el agente.

| Caso | Llamada de la tool | Documentado | SQL independiente | Tool | Estado | ✓ |
|---|---|---:|---:|---:|---|:---:|
| Total nacional de IPS | `count_ips({})` | 9.320 | 9.320 | 9.320 | `ok` | ✅ |
| Total de sedes | `count_sedes({})` | 15.547 | 15.547 | 15.547 | `ok` | ✅ |
| IPS en Bogotá D.C. | `count_ips({"departamento": "bogota"})` | 1.270 | 1.270 | 1.270 | `ok` | ✅ |
| IPS en Medellín | `count_ips({"municipio": "Medellín"})` | 517 | 517 | 517 | `ok` | ✅ |
| IPS en Valle del Cauca (con Cali y Buenaventura) | `count_ips({"departamento": "Valle del Cauca"})` | 813 | 813 | 813 | `ok` | ✅ |
| IPS en Cali (municipio) | `count_ips({"municipio": "Cali"})` | 491 | 491 | 491 | `ok` | ✅ |
| Camas en Antioquia | `sum_capacidad({"grupo_capacidad": "CAMAS", "departamento": "Antioquia"})` | 11.427 | 11.427 | 11.427 | `ok` | ✅ |
| Camas de adultos en Antioquia | `sum_capacidad({"grupo_capacidad": "CAMAS", "descripcion_capacidad": "camas de adultos", "departamento": "Antioquia"})` | 6.438 | 6.438 | 6.438 | `ok` | ✅ |
| Ambulancias en Antioquia | `sum_capacidad({"grupo_capacidad": "AMBULANCIAS", "departamento": "Antioquia"})` | 496 | 496 | 496 | `ok` | ✅ |
| IPS de nivel 3 | `count_ips({"nivel_atencion": 3})` | 29 | 29 | 29 | `ok` | ✅ |
| IPS privadas con nivel registrado | `count_ips({"naturaleza": "Privada", "nivel_atencion": 1})` | 1 | 1 | 1 | `sin_cobertura` | ✅ |
| Hospital Pablo Tobón Uribe (nombre exacto) | `buscar_ips({"nombre": "Hospital Pablo Tobón Uribe"})` | ok | — | HOSPITAL PABLO TOBON URIBE | `ok` | ✅ |
| «PABLO TOVON URIBE» (error de transcripción) | `buscar_ips({"nombre": "PABLO TOVON URIBE"})` | ok | — | HOSPITAL PABLO TOBON URIBE | `ok` | ✅ |
| «pablo tobon» (nombre compartido) | `buscar_ips({"nombre": "pablo tobon"})` | ambiguo | — | 2 candidatos | `ambiguo` | ✅ |
| «clinica santa maria» (varias clínicas homónimas) | `buscar_ips({"nombre": "clinica santa maria"})` | ambiguo | — | 5 candidatos | `ambiguo` | ✅ |
| Municipio inexistente (Springfield) | `count_ips({"municipio": "Springfield"})` | no_encontrado | — | sin valor | `no_encontrado` | ✅ |
| Descripción inexistente (camas para extraterrestres) | `sum_capacidad({"grupo_capacidad": "CAMAS", "descripcion_capacidad": "camas para extraterrestres"})` | no_encontrado | — | sin valor | `no_encontrado` | ✅ |
| Mixtas de nivel 2 | `count_ips({"naturaleza": "Mixta", "nivel_atencion": 2})` | sin_cobertura | — | 0 | `sin_cobertura` | ✅ |
| Inyección SQL en municipio | `count_ips({"municipio": "Cali'; DROP TABLE ips; --"})` | no_encontrado | — | sin valor | `no_encontrado` | ✅ |
| Departamento fuera del enum (Narnia) | `count_ips({"departamento": "Narnia"})` | error_validacion | — | sin valor | `error_validacion` | ✅ |

## 4. Casos de prueba ejecutados

<details><summary><b>TypeScript · MockTransport (contrato WS)</b> — 20/20 pasan</summary>

| Caso | Resultado | Tiempo (ms) |
|---|:---:|---:|
| secuencia: conectando → listo → session.brief → audio del brief → escuchando | ✅ | 12 |
| session.state «listo» anuncia el protocolo 1.0 | ✅ | 4 |
| session.brief: turno t-0000, 3 a 5 preguntas, fecha de corte y origen | ✅ | 2 |
| cada mensaje lleva v = 1 y seq estrictamente creciente desde 1 | ✅ | 7 |
| no existe un evento «insight»: el contrato v1.0 lo llama «sentiment» | ✅ | 8 |
| orden: partial → final → pensando → tool running/done → audio.start → hablando → texto final → audio.end → metrics → escuchando | ✅ | 8 |
| parcial y final comparten turn_id y utt_id; ts_end ≥ ts; hablante diarizado | ✅ | 6 |
| agent.tool «done» trae la evidencia: valor, filtros, filas_usadas, fecha_corte, origen y estado | ✅ | 5 |
| agent.text es acumulado y solo el último es final | ✅ | 5 |
| metrics: latencia percibida = vad_silence_ms + first_audio_ms | ✅ | 4 |
| sentiment llega después del transcript.final del mismo enunciado, con score en [-1, 1] | ✅ | 4 |
| text.message: sin parciales, transcript.final con source «text» y hablante «user» | ✅ | 6 |
| los turnos se numeran t-0001, t-0002… y los enunciados u-0001, u-0002… | ✅ | 5 |
| mientras habla: audio.clear → agent.text final interrumpido (prefijo de lo dicho) → escuchando | ✅ | 4 |
| después de audio.clear no llega más texto ni audio de ese turno | ✅ | 5 |
| antes del primer audio: metrics con interrupted y sin first_audio_ms; sin audio.clear | ✅ | 4 |
| hablar encima del agente interrumpe y abre un turno nuevo | ✅ | 5 |
| interrumpir el brief corta su audio con audio.clear de t-0000 | ✅ | 2 |
| en pausa no se aceptan turnos; al reanudar sí | ✅ | 6 |
| después de close no se emite nada | ✅ | 5 |

</details>

<details><summary><b>Python · QA (verdad de referencia, tools, contrato)</b> — 58/58 pasan</summary>

| Caso | Resultado | Tiempo (ms) |
|---|:---:|---:|
| test_ground_truth_tools › test_snapshot_filas_y_corte | ✅ | 28 |
| test_ground_truth_tools › test_snapshot_ips_y_sedes_distintas | ✅ | 18 |
| test_ground_truth_tools › test_snapshot_sede_id_no_mezcla_nombres | ✅ | 26 |
| test_ground_truth_tools › test_snapshot_departamentos_canonicos | ✅ | 6 |
| test_ground_truth_tools › test_store_carga_igual_que_el_parquet | ✅ | 356 |
| test_ground_truth_tools › test_a_total_nacional_ips | ✅ | 13 |
| test_ground_truth_tools › test_a_total_nacional_sedes | ✅ | 4 |
| test_ground_truth_tools › test_a_naturaleza | ✅ | 20 |
| test_ground_truth_tools › test_b_ips_bogota[depto-exacto] | ✅ | 17 |
| test_ground_truth_tools › test_b_ips_bogota[depto-sin-tilde] | ✅ | 15 |
| test_ground_truth_tools › test_b_ips_bogota[municipio] | ✅ | 11 |
| test_ground_truth_tools › test_b_ips_bogota[municipio-mayusculas] | ✅ | 9 |
| test_ground_truth_tools › test_b_bogota_lidera_ranking | ✅ | 31 |
| test_ground_truth_tools › test_b_medellin | ✅ | 12 |
| test_ground_truth_tools › test_b_valle_incluye_distritos | ✅ | 17 |
| test_ground_truth_tools › test_b_cali_como_municipio_no_cuenta_todo_el_valle | ✅ | 7 |
| test_ground_truth_tools › test_b_antioquia_sin_distritos | ✅ | 12 |
| test_ground_truth_tools › test_c_camas_antioquia | ✅ | 15 |
| test_ground_truth_tools › test_c_camas_adultos_antioquia[Adultos] | ✅ | 18 |
| test_ground_truth_tools › test_c_camas_adultos_antioquia[adultos] | ✅ | 18 |
| test_ground_truth_tools › test_c_camas_adultos_antioquia[camas de adultos] | ✅ | 19 |
| test_ground_truth_tools › test_c_camas_adultos_antioquia[camas para adultos] | ✅ | 18 |
| test_ground_truth_tools › test_c_capacidad_antioquia_por_grupo | ✅ | 72 |
| test_ground_truth_tools › test_c_camas_adultos_nacional | ✅ | 14 |
| test_ground_truth_tools › test_c_nivel_3_lleva_nota_de_cobertura | ✅ | 10 |
| test_ground_truth_tools › test_d_pablo_tobon_unico[exacto] | ✅ | 28 |
| test_ground_truth_tools › test_d_pablo_tobon_unico[mayusculas] | ✅ | 27 |
| test_ground_truth_tools › test_d_pablo_tobon_unico[minusculas-sin-tilde] | ✅ | 28 |
| test_ground_truth_tools › test_d_pablo_tobon_unico[sin-generico] | ✅ | 46 |
| test_ground_truth_tools › test_d_pablo_tobon_unico[error-asr] | ✅ | 188 |
| test_ground_truth_tools › test_d_pablo_tobon_devuelve_contacto_real | ✅ | 25 |
| test_ground_truth_tools › test_d_nombre_compartido_es_ambiguo[pablo tobon] | ✅ | 30 |
| test_ground_truth_tools › test_d_nombre_compartido_es_ambiguo[tobon] | ✅ | 33 |
| test_ground_truth_tools › test_d_clinica_santa_maria_ambigua_y_acotada | ✅ | 66 |
| test_ground_truth_tools › test_d_nombre_inexistente_sin_resultados | ✅ | 95 |
| test_ground_truth_tools › test_e_privada_nivel_1_sin_cobertura | ✅ | 8 |
| test_ground_truth_tools › test_e_mixta_nivel_2_sin_cobertura_no_cero | ✅ | 5 |
| test_ground_truth_tools › test_e_publicas_nivel_3_ok | ✅ | 5 |
| test_ground_truth_tools › test_e_lugar_inexistente_no_devuelve_cero | ✅ | 8 |
| test_ground_truth_tools › test_e_lugar_con_error_tipografico_sugiere | ✅ | 10 |
| test_ground_truth_tools › test_e_descripcion_inexistente | ✅ | 7 |
| test_ground_truth_tools › test_e_descripcion_ambigua | ✅ | 5 |
| test_ground_truth_tools › test_e_envoltorio_comun | ✅ | 51 |
| test_ground_truth_tools › test_e_listas_acotadas_a_10 | ✅ | 19 |
| test_ground_truth_tools › test_s_inyeccion_sql_en_lugar | ✅ | 9 |
| test_ground_truth_tools › test_s_inyeccion_sql_en_nombre_no_rompe | ✅ | 155 |
| test_ground_truth_tools › test_s_argumentos_fuera_de_esquema[campo-desconocido] | ✅ | 1 |
| test_ground_truth_tools › test_s_argumentos_fuera_de_esquema[enum-departamento] | ✅ | 1 |
| test_ground_truth_tools › test_s_argumentos_fuera_de_esquema[enum-nivel] | ✅ | 1 |
| test_ground_truth_tools › test_s_argumentos_fuera_de_esquema[enum-dimension] | ✅ | 1 |
| test_ground_truth_tools › test_s_argumentos_fuera_de_esquema[requerido] | ✅ | 1 |
| test_ground_truth_tools › test_s_argumentos_fuera_de_esquema[tool-inexistente] | ✅ | 1 |
| test_ground_truth_tools › test_s_presupuesto_de_dos_llamadas_por_turno | ✅ | 12 |
| test_ground_truth_tools › test_l_p95_por_tool_bajo_la_meta | ✅ | 2221 |
| test_mock_trace_schema › test_traza_no_vacia | ✅ | 13 |
| test_mock_trace_schema › test_cada_evento_del_mock_valida_contra_el_esquema | ✅ | 208 |
| test_mock_trace_schema › test_tipos_cubiertos | ✅ | 1 |
| test_mock_trace_schema › test_sentimiento_del_mock_usa_etiquetas_reales | ✅ | 173 |

</details>

<details><summary><b>Python · Regresión del backend</b> — 368/368 pasan</summary>

| Caso | Resultado | Tiempo (ms) |
|---|:---:|---:|
| test_agent_brief › test_instructions_have_no_dataset_figures | ✅ | 1 |
| test_agent_brief › test_instructions_within_budget_and_cover_rules | ✅ | 1 |
| test_agent_brief › test_brief_is_a_friendly_invitation | ✅ | 428 |
| test_agent_brief › test_brief_does_not_claim_data_is_current | ✅ | 62 |
| test_agent_brief › test_between_3_and_5_questions_all_resolvable | ✅ | 120 |
| test_agent_brief › test_questions_avoid_out_of_source_and_private_levels | ✅ | 61 |
| test_agent_brief › test_unresolvable_candidates_are_dropped | ✅ | 88 |
| test_agent_brief › test_same_profile_same_brief | ✅ | 116 |
| test_agent_brief › test_brief_rebuilt_after_refresh | ✅ | 164 |
| test_agent_brief › test_spoken_brief_is_20s_or_less | ✅ | 62 |
| test_agent_brief › test_formatters | ✅ | 13 |
| test_agent_no_secrets › test_openai_key_not_in_logs_results_or_errors | ✅ | 439 |
| test_agent_no_secrets › test_http_error_does_not_leak_key | ✅ | 446 |
| test_agent_tools › test_exactly_seven_tools | ✅ | 395 |
| test_agent_tools › test_listar_ips_in_manizales | ✅ | 21 |
| test_agent_tools › test_listar_ips_by_capacity_group_and_limit | ✅ | 17 |
| test_agent_tools › test_listar_ips_unknown_place_and_limits | ✅ | 28 |
| test_agent_tools › test_enums_come_from_profile | ✅ | 1 |
| test_agent_tools › test_enums_change_when_profile_changes | ✅ | 156 |
| test_agent_tools › test_count_ips_counts_providers_not_rows | ✅ | 5 |
| test_agent_tools › test_count_sedes | ✅ | 6 |
| test_agent_tools › test_sum_capacidad_adultos_antioquia | ✅ | 19 |
| test_agent_tools › test_filters_combine | ✅ | 6 |
| test_agent_tools › test_top_n_departamentos | ✅ | 13 |
| test_agent_tools › test_top_n_caps_at_10_and_flags | ✅ | 24 |
| test_agent_tools › test_group_by_naturaleza_and_capacidad | ✅ | 18 |
| test_agent_tools › test_group_by_nivel_excludes_unregistered | ✅ | 6 |
| test_agent_tools › test_capacidad_requires_group | ✅ | 1 |
| test_agent_tools › test_buscar_case_and_accent_insensitive | ✅ | 39 |
| test_agent_tools › test_buscar_ambiguous_lists_candidates | ✅ | 38 |
| test_agent_tools › test_buscar_no_match_no_invention | ✅ | 183 |
| test_agent_tools › test_results_are_compact_without_contacts | ✅ | 73 |
| test_agent_tools › test_valle_incluye_distritos | ✅ | 13 |
| test_agent_tools › test_antioquia_sin_distritos | ✅ | 12 |
| test_agent_tools › test_bogota_sin_mapeo | ✅ | 14 |
| test_agent_tools › test_descripcion_exacta_no_incluye_intensiva | ✅ | 12 |
| test_agent_tools › test_descripcion_coloquial_resuelve | ✅ | 12 |
| test_agent_tools › test_descripcion_cuidado_intensivo_adulto_exacta | ✅ | 11 |
| test_agent_tools › test_descripcion_ambigua_lista_candidatos | ✅ | 7 |
| test_agent_tools › test_descripcion_inexistente | ✅ | 8 |
| test_agent_tools › test_municipio_inexistente_no_cero | ✅ | 10 |
| test_agent_tools › test_municipio_con_typo_sugiere | ✅ | 10 |
| test_agent_tools › test_municipio_sin_tildes | ✅ | 13 |
| test_agent_tools › test_lugar_existente_sin_resultados_es_cero | ✅ | 15 |
| test_agent_tools › test_sin_cobertura_privada_nivel_1 | ✅ | 7 |
| test_agent_tools › test_sin_cobertura_aunque_sea_cero | ✅ | 5 |
| test_agent_tools › test_mixta_sin_cobertura | ✅ | 5 |
| test_agent_tools › test_invalid_arguments_rejected_compactly[count_ips-args0] | ✅ | 1 |
| test_agent_tools › test_invalid_arguments_rejected_compactly[count_ips-args1] | ✅ | 1 |
| test_agent_tools › test_invalid_arguments_rejected_compactly[count_ips-args2] | ✅ | 1 |
| test_agent_tools › test_invalid_arguments_rejected_compactly[count_ips-args3] | ✅ | 1 |
| test_agent_tools › test_invalid_arguments_rejected_compactly[sum_capacidad-args4] | ✅ | 1 |
| test_agent_tools › test_invalid_arguments_rejected_compactly[sum_capacidad-args5] | ✅ | 1 |
| test_agent_tools › test_invalid_arguments_rejected_compactly[top_n-args6] | ✅ | 1 |
| test_agent_tools › test_invalid_arguments_rejected_compactly[buscar_ips-args7] | ✅ | 1 |
| test_agent_tools › test_invalid_arguments_rejected_compactly[no_existe-args8] | ✅ | 1 |
| test_agent_tools › test_null_args_are_ignored | ✅ | 6 |
| test_agent_tools › test_two_calls_per_turn_limit | ✅ | 12 |
| test_agent_tools › test_closed_values_are_canonicalized | ✅ | 51 |
| test_agent_tools › test_buscar_single_match_includes_contact_and_main_sedes | ✅ | 61 |
| test_agent_tools › test_buscar_ignores_generic_words | ✅ | 174 |
| test_agent_tools › test_buscar_tolerates_transcription_errors | ✅ | 104 |
| test_agent_tools › test_buscar_matches_words_not_substrings | ✅ | 45 |
| test_agent_tools › test_buscar_partial_match_on_keywords | ✅ | 153 |
| test_agent_tools › test_buscar_ambiguous_ranked_by_relevance | ✅ | 41 |
| test_agent_tools › test_level_without_naturaleza_adds_note | ✅ | 25 |
| test_agent_tools › test_place_descriptions_prefer_municipio_for_cities | ✅ | 20 |
| test_api › test_brief_endpoint_returns_text_and_3_to_5_questions | ✅ | 529 |
| test_api › test_brief_endpoint_is_deterministic | ✅ | 465 |
| test_api › test_brief_endpoint_503_without_data | ✅ | 335 |
| test_api › test_cors_allows_dev_front_origin | ✅ | 458 |
| test_api › test_cors_rejects_other_origins | ✅ | 384 |
| test_api › test_env_example_lists_dev_front_origin | ✅ | 2 |
| test_cascade › test_helpers | ✅ | 1 |
| test_cascade › test_brief_is_spoken_with_aura_in_spanish | ✅ | 1723 |
| test_cascade › test_text_turn_with_tool_on_groq | ✅ | 1765 |
| test_cascade › test_voice_turn_ends_on_deepgram_speech_final | ✅ | 1567 |
| test_cascade › test_user_speech_interrupts_agent_while_speaking | ✅ | 7611 |
| test_cascade › test_user_speech_interrupts_finished_turn_still_playing | ✅ | 1776 |
| test_cascade › test_audio_out_false_answers_with_text | ✅ | 1205 |
| test_cascade › test_invalid_groq_key_fails_start_with_clear_log | ✅ | 719 |
| test_cascade › test_echo_of_agent_does_not_interrupt | ✅ | 2 |
| test_cascade › test_filler_is_spoken_while_tools_run | ✅ | 1093 |
| test_cascade › test_first_chunk_is_cut_early_at_a_comma | ✅ | 1 |
| test_cascade › test_rate_limit_with_short_retry_after_waits_and_retries | ✅ | 1519 |
| test_cascade › test_rate_limit_without_quota_uses_fallback_chain | ✅ | 887 |
| test_cascade › test_retired_model_in_the_chain_is_skipped | ✅ | 899 |
| test_cascade › test_rejected_tool_call_is_retried | ✅ | 1356 |
| test_cascade › test_no_quota_anywhere_small_talk_says_so_honestly | ✅ | 664 |
| test_cascade › test_no_quota_anywhere_still_answers_with_real_data | ✅ | 927 |
| test_cascade › test_failure_after_tool_answers_from_the_data_already_fetched | ✅ | 1418 |
| test_cascade › test_empty_model_reply_is_rescued | ✅ | 784 |
| test_cascade › test_llm_tools_are_compact | ✅ | 0 |
| test_cascade › test_common_question_is_answered_with_a_single_llm_call | ✅ | 1079 |
| test_cascade › test_numbers_are_spoken_in_words_but_shown_in_digits | ✅ | 1069 |
| test_cascade › test_speed_is_sent_and_dropped_if_rejected | ✅ | 1096 |
| test_cascade › test_rejected_speed_retries_without_it | ✅ | 1083 |
| test_cascade › test_silence_is_trimmed_between_sentences | ✅ | 5 |
| test_cascade › test_echo_is_recognized_when_numbers_are_spoken_in_words | ✅ | 0 |
| test_cascade › test_abbreviations_do_not_split_sentences | ✅ | 0 |
| test_cascade › test_only_real_speech_interrupts | ✅ | 0 |
| test_cascade › test_follow_up_questions_are_left_to_the_model | ✅ | 446 |
| test_cascade › test_question_sharing_words_with_the_answer_is_not_echo | ✅ | 1 |
| test_cascade › test_rescue_does_not_answer_nuanced_questions_wrongly | ✅ | 746 |
| test_client › test_pagination_count_and_unique_ids_and_token_header | ✅ | 5 |
| test_client › test_incomplete_download_raises | ✅ | 5 |
| test_client › test_duplicate_ids_raise | ✅ | 4 |
| test_client › test_auth_errors_not_retried[401] | ✅ | 1 |
| test_client › test_auth_errors_not_retried[403] | ✅ | 2 |
| test_client › test_429_respects_retry_after | ✅ | 2 |
| test_client › test_503_then_200_recovers_with_backoff | ✅ | 2 |
| test_client › test_network_error_retries_then_gives_up_without_token | ✅ | 2 |
| test_config › test_defaults | ✅ | 0 |
| test_config › test_missing_voice_key_names_variable_without_values | ✅ | 0 |
| test_config › test_voice_keys_not_required_when_disabled | ✅ | 0 |
| test_config › test_invalid_int_names_variable | ✅ | 0 |
| test_config › test_repr_hides_secrets | ✅ | 0 |
| test_config › test_startup_exits_with_clear_message | ✅ | 90 |
| test_config › test_voice_defaults | ✅ | 0 |
| test_config › test_voice_overrides_from_env | ✅ | 0 |
| test_config › test_vad_semantic_and_server_turn_detection | ✅ | 0 |
| test_config › test_vad_values_are_configurable | ✅ | 0 |
| test_config › test_invalid_voice_settings_name_the_variable[env0-VAD_TYPE] | ✅ | 1 |
| test_config › test_invalid_voice_settings_name_the_variable[env1-VAD_THRESHOLD] | ✅ | 1 |
| test_config › test_invalid_voice_settings_name_the_variable[env2-VAD_EAGERNESS] | ✅ | 1 |
| test_config › test_invalid_voice_settings_name_the_variable[env3-VAD_SILENCE_MS] | ✅ | 1 |
| test_config › test_invalid_voice_settings_name_the_variable[env4-SESSION_WARN_SECONDS] | ✅ | 1 |
| test_config › test_health_reports_voice_status | ✅ | 608 |
| test_config › test_default_data_path_is_repo_snapshot | ✅ | 1 |
| test_config › test_relative_data_path_resolves_from_backend | ✅ | 2 |
| test_config › test_env_file_utf8_and_utf16 | ✅ | 5 |
| test_config › test_process_env_overrides_env_file | ✅ | 3 |
| test_config › test_stale_relative_data_path_falls_back_to_repo | ✅ | 2 |
| test_config › test_realtime_speed | ✅ | 0 |
| test_config › test_groq_provider_is_default_and_requires_its_keys | ✅ | 1 |
| test_datastore › test_snapshot_loads_ready_within_5s | ✅ | 305 |
| test_datastore › test_snapshot_counts | ✅ | 307 |
| test_datastore › test_inconsistent_snapshot_is_degraded | ✅ | 326 |
| test_datastore › test_types_and_aliases | ✅ | 3 |
| test_datastore › test_normalization_lowercase_without_accents | ✅ | 1 |
| test_datastore › test_rows_path_types_normalization_and_conversion_failures | ✅ | 85 |
| test_datastore › test_departamento_canonico | ✅ | 9 |
| test_datastore › test_district_mapping | ✅ | 4 |
| test_datastore › test_missing_snapshot_without_token_is_unavailable | ✅ | 16 |
| test_datastore › test_unreadable_snapshot_without_token_is_unavailable | ✅ | 21 |
| test_datastore › test_missing_snapshot_falls_back_to_full_download | ✅ | 112 |
| test_datastore › test_missing_snapshot_and_failed_download_is_unavailable | ✅ | 45 |
| test_datastore › test_provenance_and_health_without_token_skips_refresh | ✅ | 327 |
| test_datastore › test_sede_id_distinct_and_no_name_conflicts | ✅ | 23 |
| test_datastore › test_sede_id_built_on_api_path_too | ✅ | 85 |
| test_datastore › test_sede_id_defined_in_single_place | ✅ | 15 |
| test_gold › test_all_gold_questions_match_sql | ✅ | 500 |
| test_gold › test_sql_matches_values_written_in_tasks | ✅ | 0 |
| test_gold › test_honesty_cases_never_return_a_number | ✅ | 0 |
| test_gold › test_table_lists_every_question | ✅ | 0 |
| test_gold › test_tool_p95_within_200ms | ✅ | 2686 |
| test_gold › test_number_matching_respects_spoken_rounding[Hay unas 45 mil camas-45262-True] | ✅ | 1 |
| test_gold › test_number_matching_respects_spoken_rounding[Hay 45.262 camas-45262-True] | ✅ | 1 |
| test_gold › test_number_matching_respects_spoken_rounding[Hay 45262 camas-45262-True] | ✅ | 1 |
| test_gold › test_number_matching_respects_spoken_rounding[Hay 9.320 IPS-9320-True] | ✅ | 1 |
| test_gold › test_number_matching_respects_spoken_rounding[Hay 9.400 IPS-9320-False] | ✅ | 1 |
| test_gold › test_number_matching_respects_spoken_rounding[Hay 1,3 mil IPS-1270-True] | ✅ | 1 |
| test_gold › test_number_matching_respects_spoken_rounding[Hay 1,4 mil IPS-1270-False] | ✅ | 1 |
| test_gold › test_number_matching_respects_spoken_rounding[Son 813-813-True] | ✅ | 1 |
| test_gold › test_number_matching_respects_spoken_rounding[Son 814-813-False] | ✅ | 1 |
| test_gold › test_parse_numbers_units | ✅ | 0 |
| test_gold › test_ungrounded_numbers_detected | ✅ | 0 |
| test_gold › test_text_agent_runs_tool_loop_and_grounds_answer | ✅ | 69 |
| test_gold › test_check_answer_flags_invented_figures_and_zero_answers | ✅ | 1 |
| test_gold › test_agent_mode_requires_env_vars | ✅ | 1 |
| test_gold › test_number_formats_and_trailing_zero_rounding[hay alrededor de 9,320 IPS-9320-True] | ✅ | 1 |
| test_gold › test_number_formats_and_trailing_zero_rounding[hay alrededor de 6,440 camas-6438-True] | ✅ | 1 |
| test_gold › test_number_formats_and_trailing_zero_rounding[hay alrededor de 6,400 camas-6438-True] | ✅ | 1 |
| test_gold › test_number_formats_and_trailing_zero_rounding[hay alrededor de 6,500 camas-6438-False] | ✅ | 1 |
| test_gold › test_number_formats_and_trailing_zero_rounding[aproximadamente 500 camas-6438-False] | ✅ | 1 |
| test_gold › test_number_formats_and_trailing_zero_rounding[Hay 9.400 IPS-9320-False] | ✅ | 1 |
| test_gold › test_number_formats_and_trailing_zero_rounding[Son 814-813-False] | ✅ | 8 |
| test_no_secrets › test_logs_do_not_contain_token_on_auth_error | ✅ | 15 |
| test_no_secrets › test_logs_do_not_contain_token_on_retries_and_network_errors | ✅ | 15 |
| test_no_secrets › test_logs_do_not_contain_token_on_5xx | ✅ | 14 |
| test_numbers › test_number_to_words[0-None-cero] | ✅ | 1 |
| test_numbers › test_number_to_words[1-None-uno] | ✅ | 1 |
| test_numbers › test_number_to_words[1-True-una] | ✅ | 0 |
| test_numbers › test_number_to_words[1-False-un] | ✅ | 1 |
| test_numbers › test_number_to_words[15-None-quince] | ✅ | 0 |
| test_numbers › test_number_to_words[21-True-veintiuna] | ✅ | 1 |
| test_numbers › test_number_to_words[21-False-veinti\xfan] | ✅ | 0 |
| test_numbers › test_number_to_words[30-None-treinta] | ✅ | 0 |
| test_numbers › test_number_to_words[45-None-cuarenta y cinco] | ✅ | 0 |
| test_numbers › test_number_to_words[100-None-cien] | ✅ | 0 |
| test_numbers › test_number_to_words[101-None-ciento uno] | ✅ | 0 |
| test_numbers › test_number_to_words[200-True-doscientas] | ✅ | 0 |
| test_numbers › test_number_to_words[500-False-quinientos] | ✅ | 0 |
| test_numbers › test_number_to_words[1000-None-mil] | ✅ | 1 |
| test_numbers › test_number_to_words[1001-None-mil uno] | ✅ | 0 |
| test_numbers › test_number_to_words[2022-None-dos mil veintid\xf3s] | ✅ | 1 |
| test_numbers › test_number_to_words[9320-True-nueve mil trescientas veinte] | ✅ | 1 |
| test_numbers › test_number_to_words[21000-True-veintiuna mil] | ✅ | 0 |
| test_numbers › test_number_to_words[1000000-None-un mill\xf3n] | ✅ | 1 |
| test_numbers › test_number_to_words[2500000-None-dos millones quinientos mil] | ✅ | 1 |
| test_numbers › test_spoken_numbers[Tengo datos de 9.320 IPS y 15.547 sedes-Tengo datos de nueve mil trescientas veinte IPS y quince mil quinientas cuarenta y siete sedes] | ✅ | 1 |
| test_numbers › test_spoken_numbers[con corte al 5 de noviembre de 2022.-con corte al cinco de noviembre de dos mil veintid\xf3s.] | ✅ | 1 |
| test_numbers › test_spoken_numbers[Hay 21 hospitales y 1 IPS.-Hay veinti\xfan hospitales y una IPS.] | ✅ | 0 |
| test_numbers › test_spoken_numbers[Su tel\xe9fono es 878, 25, 00.-Su tel\xe9fono es ochocientos setenta y ocho, veinticinco, cero cero.] | ✅ | 1 |
| test_numbers › test_spoken_numbers[Llama al 8782500.-Llama al ochocientos setenta y ocho, veinticinco, cero cero.] | ✅ | 0 |
| test_numbers › test_spoken_numbers[Calle 48 # 25-71-Calle cuarenta y ocho n\xfamero veinticinco setenta y uno] | ✅ | 1 |
| test_numbers › test_spoken_numbers[Calle 5\xb0 N\xb0 40-02-Calle cinco n\xfamero cuarenta cero dos] | ✅ | 0 |
| test_numbers › test_spoken_numbers[El 45% son p\xfablicas-El cuarenta y cinco por ciento son p\xfablicas] | ✅ | 0 |
| test_numbers › test_spoken_numbers[en promedio 3,5-en promedio tres coma cinco] | ✅ | 1 |
| test_numbers › test_spoken_numbers[Bogot\xe1 D.C. tiene 1.270 IPS-Bogot\xe1 Distrito Capital tiene mil doscientas setenta IPS] | ✅ | 0 |
| test_numbers › test_spoken_numbers[Llama a la l\xednea 123 ya.-Llama a la l\xednea uno, dos, tres ya.] | ✅ | 0 |
| test_numbers › test_spoken_numbers[Hay 123 camas-Hay ciento veintitr\xe9s camas] | ✅ | 0 |
| test_numbers › test_spoken_numbers[Sin n\xfameros aqu\xed.-Sin n\xfameros aqu\xed.] | ✅ | 0 |
| test_profile › test_profile_totals_match_table | ✅ | 313 |
| test_profile › test_low_cardinality_columns_expose_all_values | ✅ | 0 |
| test_profile › test_departamento_canonico_exposes_all_33_values | ✅ | 0 |
| test_profile › test_high_cardinality_columns_limited_to_top_10 | ✅ | 0 |
| test_profile › test_identifier_and_contact_columns_list_no_values | ✅ | 0 |
| test_profile › test_grain_and_counts | ✅ | 0 |
| test_profile › test_nivel_atencion_coverage | ✅ | 0 |
| test_profile › test_naturaleza_distribution | ✅ | 0 |
| test_profile › test_fecha_corte_and_source | ✅ | 0 |
| test_profile › test_serializable_and_deterministic | ✅ | 317 |
| test_profile › test_profile_recomputed_once_on_refresh | ✅ | 153 |
| test_profile › test_profile_query_under_50ms_and_no_recompute | ✅ | 0 |
| test_profile › test_profile_endpoint_under_50ms | ✅ | 334 |
| test_profile › test_profile_endpoint_503_before_data | ✅ | 323 |
| test_refresh › test_successful_refresh_swaps_table_and_sets_origin_api | ✅ | 152 |
| test_refresh › test_count_mismatch_keeps_current_table | ✅ | 103 |
| test_refresh › test_download_failure_keeps_current_table[err0] | ✅ | 80 |
| test_refresh › test_download_failure_keeps_current_table[err1] | ✅ | 83 |
| test_refresh › test_queries_during_swap_do_not_fail | ✅ | 796 |
| test_relay › test_brief_is_spoken_under_t0000_with_40ms_frames | ✅ | 5810 |
| test_relay › test_text_turn_runs_tool_on_server_and_reports_metrics | ✅ | 1833 |
| test_relay › test_session_update_registers_tools_instructions_and_vad | ✅ | 406 |
| test_relay › test_audio_out_false_answers_with_text_only | ✅ | 1037 |
| test_relay › test_voice_turn_uses_deepgram_labels_and_reports_vad_silence | ✅ | 2223 |
| test_relay › test_two_voices_get_two_stable_speaker_labels | ✅ | 2544 |
| test_relay › test_barge_in_clears_audio_cancels_and_truncates | ✅ | 2969 |
| test_relay › test_deepgram_down_degrades_to_openai_transcript_with_warning | ✅ | 1124 |
| test_relay › test_deepgram_recovers_and_announces_it | ✅ | 1487 |
| test_relay › test_openai_drop_reports_error_keeps_socket_and_allows_retry | ✅ | 734 |
| test_relay › test_abrupt_close_releases_openai_and_deepgram_within_5s | ✅ | 770 |
| test_relay › test_truncate_text_cuts_on_word_boundary | ✅ | 1 |
| test_relay › test_deepgram_failure_is_described_without_secrets | ✅ | 0 |
| test_relay › test_barge_in_while_client_still_plays_a_finished_response | ✅ | 1162 |
| test_relay › test_no_clear_when_playback_already_finished | ✅ | 1883 |
| test_scope › test_off_topic_is_redirected[\xbfMe recomiendas pel\xedculas?] | ✅ | 1 |
| test_scope › test_off_topic_is_redirected[\xbfD\xf3nde cambio las llantas del carro en Manizales?] | ✅ | 0 |
| test_scope › test_off_topic_is_redirected[dame una receta de arepas] | ✅ | 0 |
| test_scope › test_off_topic_is_redirected[\xbfQui\xe9n gan\xf3 el partido de f\xfatbol?] | ✅ | 0 |
| test_scope › test_off_topic_is_redirected[\xbfqu\xe9 clima hace en Bogot\xe1?] | ✅ | 0 |
| test_scope › test_off_topic_is_redirected[cu\xe9ntame un chiste] | ✅ | 0 |
| test_scope › test_off_topic_is_redirected[ay\xfadame con mi tarea de matem\xe1ticas] | ✅ | 0 |
| test_scope › test_off_topic_is_redirected[\xbfen qu\xe9 criptomoneda invierto?] | ✅ | 0 |
| test_scope › test_off_topic_is_redirected[Hola Ivy, recomi\xe9ndame una serie] | ✅ | 0 |
| test_scope › test_off_topic_is_redirected[\xbfqu\xe9 celular me compro?] | ✅ | 0 |
| test_scope › test_off_topic_is_redirected[escr\xedbeme un c\xf3digo en python] | ✅ | 0 |
| test_scope › test_in_scope_or_small_talk_goes_to_the_model[\xbfCu\xe1ntas IPS hay en Manizales?] | ✅ | 0 |
| test_scope › test_in_scope_or_small_talk_goes_to_the_model[Hola Ivy, \xbfc\xf3mo est\xe1s?] | ✅ | 0 |
| test_scope › test_in_scope_or_small_talk_goes_to_the_model[gracias] | ✅ | 0 |
| test_scope › test_in_scope_or_small_talk_goes_to_the_model[\xbfQui\xe9n eres?] | ✅ | 0 |
| test_scope › test_in_scope_or_small_talk_goes_to_the_model[me duele la cabeza, \xbfqu\xe9 hago?] | ✅ | 0 |
| test_scope › test_in_scope_or_small_talk_goes_to_the_model[\xbfD\xf3nde hay un banco de sangre en Cali?] | ✅ | 0 |
| test_scope › test_in_scope_or_small_talk_goes_to_the_model[\xbfqu\xe9 hospitales hay en Medell\xedn?] | ✅ | 0 |
| test_scope › test_in_scope_or_small_talk_goes_to_the_model[tuve un accidente con la moto, \xbfa d\xf3nde voy?] | ✅ | 0 |
| test_scope › test_in_scope_or_small_talk_goes_to_the_model[\xbfcu\xe1ntas camas de UCI hay en Bogot\xe1?] | ✅ | 0 |
| test_scope › test_in_scope_or_small_talk_goes_to_the_model[\xbfme das el tel\xe9fono de la cl\xednica Avidanti?] | ✅ | 0 |
| test_scope › test_role_change_attempts | ✅ | 0 |
| test_scope › test_instructions_state_the_scope_rule | ✅ | 0 |
| test_scope › test_off_topic_never_reaches_the_model | ✅ | 1226 |
| test_sentiment › test_validate_normalizes_and_keeps_score_coherent | ✅ | 1 |
| test_sentiment › test_trivial_utterances | ✅ | 0 |
| test_sentiment › test_text_utterance_gets_sentiment_after_its_final | ✅ | 956 |
| test_sentiment › test_values_are_always_in_the_closed_lists_and_agent_is_not_analyzed | ✅ | 1049 |
| test_sentiment › test_short_utterance_is_neutral_without_calling_the_model | ✅ | 742 |
| test_sentiment › test_voice_utterance_gets_sentiment_with_speaker_label | ✅ | 1227 |
| test_sentiment › test_failures_are_silent_and_voice_goes_on[invalid_json] | ✅ | 1540 |
| test_sentiment › test_failures_are_silent_and_voice_goes_on[slow] | ✅ | 4433 |
| test_sentiment › test_disabled_by_env | ✅ | 1546 |
| test_sentiment › test_hand_labeled_phrases_are_valid | ✅ | 2 |
| test_sentiment › test_sentiment_follows_the_conversation | ✅ | 1127 |
| test_sentiment › test_retired_sentiment_model_falls_back | ✅ | 947 |
| test_spike_audio › test_trim_silence_and_frames | ✅ | 4 |
| test_spike_audio › test_wav_roundtrip | ✅ | 10 |
| test_spike_audio › test_classify_expected_call_is_clean | ✅ | 0 |
| test_spike_audio › test_classify_invented_filter_wrong_value_and_unneeded_call | ✅ | 0 |
| test_spike_audio › test_rule_b_lowest_median_among_passing | ✅ | 1 |
| test_spike_audio › test_rule_a_discards_below_98_percent | ✅ | 0 |
| test_spike_audio › test_p95_over_limit_is_excluded | ✅ | 0 |
| test_spike_audio › test_rule_c_tie_under_150ms_picks_most_precise | ✅ | 0 |
| test_spike_audio › test_rule_d_when_none_passes_needs_filter_guard | ✅ | 0 |
| test_spike_audio › test_table_mentions_every_group | ✅ | 0 |
| test_spike_audio › test_run_one_measures_tool_flow | ✅ | 1175 |
| test_spike_audio › test_run_one_reports_connection_errors | ✅ | 2 |
| test_spike_realtime › test_words_to_digits[Hay nueve mil trescientos veinte IPS-Hay 9.320 IPS] | ✅ | 1 |
| test_spike_realtime › test_words_to_digits[unas cuarenta y cinco mil camas-unas 45 mil camas] | ✅ | 1 |
| test_spike_realtime › test_words_to_digits[seis mil cuatrocientos treinta y ocho camas-6.438 camas] | ✅ | 1 |
| test_spike_realtime › test_words_to_digits[ochocientas trece IPS-813 IPS] | ✅ | 1 |
| test_spike_realtime › test_words_to_digits[el cinco de noviembre de dos mil veintid\xf3s-el cinco de noviembre de 2.022] | ✅ | 1 |
| test_spike_realtime › test_words_to_digits[un departamento y tres niveles-un departamento y tres niveles] | ✅ | 1 |
| test_spike_realtime › test_words_to_digits[dos millones de camas-2 millones de camas] | ✅ | 0 |
| test_spike_realtime › test_words_to_digits[mil doscientas setenta-1.270] | ✅ | 0 |
| test_spike_realtime › test_spoken_rounding_matches_expected | ✅ | 0 |
| test_spike_realtime › test_session_config_has_flat_tools_and_no_secrets | ✅ | 393 |
| test_spike_realtime › test_ask_runs_tool_round_trip_and_measures | ✅ | 57 |
| test_spike_realtime › test_ask_no_tool_honesty_and_error_paths | ✅ | 49 |
| test_spike_realtime › test_env_loader_does_not_override_or_print | ✅ | 4 |
| test_spike_realtime › test_redact_hides_key_like_fragments | ✅ | 0 |
| test_spike_realtime › test_mixed_digits_and_mil[unas 9 mil 320 IPS-unas 9.320 IPS] | ✅ | 0 |
| test_spike_realtime › test_mixed_digits_and_mil[cerca de 6 mil 438 camas-cerca de 6.438 camas] | ✅ | 0 |
| test_spike_realtime › test_mixed_digits_and_mil[unas 45 mil camas-unas 45 mil camas] | ✅ | 0 |
| test_spike_realtime › test_honesty_patterns_accept_natural_refusals | ✅ | 5 |
| test_spoken › test_formatting_for_voice | ✅ | 1 |
| test_spoken › test_guess_tool[Ivy, \xbfcu\xe1les son las IPs que hay en la ciudad de Manizales? Listamelas.-expected0] | ✅ | 551 |
| test_spoken › test_guess_tool[Necesito conocer qu\xe9 IPs hay disponibles en la ciudad de Manizales-expected1] | ✅ | 152 |
| test_spoken › test_guess_tool[\xbfCu\xe1ntas IPS hay en Bogot\xe1?-expected2] | ✅ | 151 |
| test_spoken › test_guess_tool[cu\xe1ntas camas hay en el departamento de Caldas-expected3] | ✅ | 158 |
| test_spoken › test_guess_tool[IPS en Caldas-expected4] | ✅ | 156 |
| test_spoken › test_guess_tool[\xbfqu\xe9 ambulancias hay en Cali?-expected5] | ✅ | 154 |
| test_spoken › test_guess_tool[me toca ir al hospital-None] | ✅ | 153 |
| test_spoken › test_guess_tool[hola, \xbfc\xf3mo est\xe1s?-None] | ✅ | 152 |
| test_spoken › test_answers_sound_human | ✅ | 196 |
| test_transcript › test_pieces_become_one_complete_utterance | ✅ | 2 |
| test_transcript › test_speaker_change_closes_the_utterance | ✅ | 1 |
| test_transcript › test_short_runs_do_not_change_speaker | ✅ | 0 |
| test_ws_contract › test_published_schema_matches_models | ✅ | 15 |
| test_ws_contract › test_published_typescript_matches_models | ✅ | 9 |
| test_ws_contract › test_export_check_command_passes_and_detects_staleness | ✅ | 30 |
| test_ws_contract › test_schema_defines_every_message | ✅ | 1 |
| test_ws_contract › test_typescript_has_all_types_and_unions | ✅ | 9 |
| test_ws_contract › test_all_readme_examples_validate_against_schema | ✅ | 1009 |
| test_ws_contract › test_readme_covers_every_message_type | ✅ | 1 |
| test_ws_contract › test_invalid_examples_do_not_validate[bad0] | ✅ | 47 |
| test_ws_contract › test_invalid_examples_do_not_validate[bad1] | ✅ | 47 |
| test_ws_contract › test_invalid_examples_do_not_validate[bad2] | ✅ | 47 |
| test_ws_contract › test_invalid_examples_do_not_validate[bad3] | ✅ | 48 |
| test_ws_contract › test_invalid_examples_do_not_validate[bad4] | ✅ | 48 |
| test_ws_contract › test_invalid_examples_do_not_validate[bad5] | ✅ | 48 |
| test_ws_contract › test_invalid_examples_do_not_validate[bad6] | ✅ | 47 |
| test_ws_contract › test_state_machine_allows_a_turn_cycle_and_rejects_jumps | ✅ | 2 |
| test_ws_contract › test_protocol_version_rules | ✅ | 0 |
| test_ws_contract › test_turn_ids | ✅ | 0 |
| test_ws_contract › test_start_emits_states_and_brief_equal_to_rest | ✅ | 712 |
| test_ws_contract › test_brief_skip_omits_brief_event | ✅ | 533 |
| test_ws_contract › test_full_turn_by_text_follows_order_and_schema | ✅ | 998 |
| test_ws_contract › test_invalid_messages_keep_the_connection_open[no es json-JSON inv\xe1lido] | ✅ | 593 |
| test_ws_contract › test_invalid_messages_keep_the_connection_open[{"v": 1}-falta el campo type] | ✅ | 541 |
| test_ws_contract › test_invalid_messages_keep_the_connection_open[{"type": "raro", "v": 1}-tipo de mensaje desconocido] | ✅ | 540 |
| test_ws_contract › test_invalid_messages_keep_the_connection_open[[1, 2]-el mensaje debe ser un objeto JSON] | ✅ | 594 |
| test_ws_contract › test_invalid_messages_keep_the_connection_open[{"type": "text.message", "v": 1}-campo inv\xe1lido] | ✅ | 599 |
| test_ws_contract › test_unsupported_protocol_lists_supported_versions | ✅ | 488 |
| test_ws_contract › test_voice_disabled_error | ✅ | 490 |
| test_ws_contract › test_no_active_session_for_audio_and_messages | ✅ | 491 |
| test_ws_contract › test_audio_is_forwarded_and_bad_frames_rejected | ✅ | 607 |
| test_ws_contract › test_second_start_is_rejected_without_affecting_session | ✅ | 610 |
| test_ws_contract › test_stop_sends_final_state_then_closes | ✅ | 605 |
| test_ws_contract › test_abrupt_close_releases_backend | ✅ | 607 |
| test_ws_contract › test_reconnection_starts_a_new_session_with_seq_from_1 | ✅ | 612 |
| test_ws_contract › test_openai_failure_reports_error_keeps_socket_open_and_allows_retry | ✅ | 801 |
| test_ws_contract › test_data_unavailable_before_load | ✅ | 326 |
| test_ws_limits › test_origin_rules | ✅ | 1 |
| test_ws_limits › test_disallowed_origin_is_rejected_with_403_and_logged | ✅ | 667 |
| test_ws_limits › test_cors_allows_vercel_previews | ✅ | 599 |
| test_ws_limits › test_concurrent_limit | ✅ | 676 |
| test_ws_limits › test_rate_limit_per_ip | ✅ | 685 |
| test_ws_limits › test_duration_warns_then_closes | ✅ | 2705 |
| test_ws_limits › test_limiter_unit | ✅ | 1 |

</details>

## 5. Observaciones de calidad (no bloquean)

- **Entrada basura en `buscar_ips`.** `x' OR 1=1 --` no causa daño (consultas parametrizadas; la tabla queda intacta, verificado), pero devuelve `ambiguo` con candidatos en lugar de `sin_resultados`, porque la búsqueda parcial por palabras encuentra coincidencias con fragmentos sueltos («x», «or», «1»). Para voz no es un riesgo real; para un campo de texto podría endurecerse exigiendo al menos una palabra de 3 o más letras.
- **El mock y el contrato.** El MockTransport emite `sentiment` (no `insight`): el contrato v1.0 no define un evento `insight`; la suite lo comprueba explícitamente.
- **Pablo Tobón.** «Pablo Tobón» a secas es ambiguo con razón: el dataset tiene también «Óptica Santa Lucía Pablo Tobón» y la «Unidad Hospitalaria de Castilla Jaime Tobón Arbeláez». Con el nombre completo (o con un error de transcripción como «Tovón») se resuelve sin ambigüedad.

## 6. Certificación de estabilidad técnica para la demo

**Se certifica** que, en el código evaluado y sobre el snapshot del 5 de noviembre de 2022:

1. Las cifras que el agente puede decir coinciden exactamente con SQL independiente sobre los datos.
2. Los lugares inexistentes, los datos no registrados y los nombres ambiguos producen estados explícitos (`no_encontrado`, `sin_cobertura`, `ambiguo`) y nunca un «cero» engañoso.
3. Las tools rechazan argumentos fuera de esquema y entradas de inyección sin alterar los datos, y respetan el presupuesto de dos llamadas por turno.
4. Todas las tools cumplen la meta de latencia (p95 ≤ 200 ms) con amplio margen.
5. El MockTransport respeta el orden, la numeración y el esquema del contrato WebSocket v1.0, incluida la interrupción (`audio.clear` + texto truncado), por lo que la demo de interfaz sin backend es fiel al real.

**Alcance (lo que este reporte NO cubre):** la latencia y la calidad de los proveedores externos en vivo (Groq, Deepgram STT/TTS), la precisión de la diarización con audio real, y la conducta del modelo de lenguaje (qué tool elige y cómo redacta). Esos puntos se verifican con los casos manuales de `03_e2e_manual_test_cases.md` y con `backend/scripts/voice_golden.py` contra el despliegue.

