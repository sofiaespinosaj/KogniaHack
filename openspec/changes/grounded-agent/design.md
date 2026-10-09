## Context

La única fuente es la tabla `ips` en DuckDB y el perfil de `data-ingestion`. Cada fila es una sede × ítem de capacidad; hay 9.320 IPS y 15.547 sedes distintas. El agente corre sobre OpenAI Realtime (voz a voz) con modelo configurable por `OPENAI_REALTIME_MODEL`, de modo que el modelo decide qué tool invocar y el servidor las ejecuta.

Hechos del dataset (corte 2022-11-05) que condicionan el diseño, calculados sobre el snapshot:
- `naturaleza` por IPS distintas: privada 8.308, pública 998, mixta 14.
- `nivel_atencion` existe prácticamente solo para públicas (16.160 filas públicas con nivel y 1 privada con nivel 1); por IPS: nivel 1 = 853, nivel 2 = 113, nivel 3 = 29.
- 7 grupos de capacidad: CONSULTORIOS, SALAS, CAMAS, AMBULANCIAS, CAMILLAS, UNIDAD MOVIL y SILLAS.
- La columna `departamento` tiene 38 valores y mezcla departamentos con distritos (Bogotá D.C, Cali, Barranquilla, Cartagena, Santa Marta, Buenaventura). Hay 1.027 municipios. Con el mapeo canónico de distritos quedan 33 valores.
- `descripcion_capacidad` tiene decenas de valores (solo en CAMAS hay 41, como "Adultos", "Intensiva Adultos" o "Cuidado Intensivo Adulto"), con tildes y grafías heterogéneas.
- Definición de sede, decidida con datos (claves distintas / con más de un `nombre_sede`): `codigo_sede` = 10.921 / 1.567; `codigo_sede` + `numero_sede` = 15.547 / 0; `codigo_prestador` + `numero_sede` = 15.534 / 12. La sede física es `codigo_sede` + `numero_sede`, expuesta como la columna derivada `sede_id` definida una sola vez en `data-ingestion`; `count_sedes`, `group_by`, el perfil y el brief la usan.

## Goals / Non-Goals

**Goals:**
- Que ninguna cifra hablada provenga del modelo: todas salen de un resultado de tool.
- Argumentos acotados que impidan SQL arbitrario y errores de conteo.
- Respuestas breves y naturales para voz, con honestidad sobre los límites de la fuente.
- Brief inicial útil que haga lucir al agente en los primeros segundos de la demo.

**Non-Goals:**
- Transporte, eventos WebSocket, STT, TTS, barge-in y latencia de voz (`realtime-voice`).
- Transcripción diarizada y análisis de sentimiento.
- Cualquier fuente distinta de `ips`.

## Decisions

1. **Tools tipadas, nunca SQL libre.** Cada tool traduce argumentos validados a consultas parametrizadas en DuckDB. Alternativa: una tool `run_sql`; descartada por riesgo de errores de conteo, inyección y respuestas sin acotar.
2. **Enums tomados del perfil.** `naturaleza`, `nivel_atencion`, `grupo_capacidad` y `departamento` se publican como enums en el esquema de cada tool, generados al arrancar desde el perfil, de modo que no pueden divergir de los datos. `municipio`, `descripcion_capacidad` y nombres de IPS no son enums (1.027 municipios, decenas de descripciones y miles de nombres): se resuelven con normalización `*_norm` y coincidencia aproximada.
3. **Departamento canónico.** Los enums y filtros de departamento usan la columna `departamento_canonico`, creada en `data-ingestion` con un mapeo fijo de los distritos a su departamento: Cali y Buenaventura a Valle del Cauca, Barranquilla a Atlántico, Cartagena a Bolívar y Santa Marta a Magdalena; Bogotá D.C. permanece como está. Así "IPS en el Valle del Cauca" incluye Cali y Buenaventura. Cuando el filtro corresponde a un departamento que absorbe distritos, el resultado lleva `incluye_distritos` con los distritos incluidos, para que el agente pueda mencionarlo. Alternativa: dejar `departamento` sin mapear; descartada porque subcontaría el Valle del Cauca (285 frente a 813 IPS).
4. **Descripción de capacidad por texto.** `descripcion_capacidad` se resuelve contra `descripcion_capacidad_norm`: primero coincidencia exacta, luego aproximada. Si hay varios candidatos plausibles devuelve `ambiguo` con la lista; si no coincide, `no_encontrado` con hasta 3 sugerencias, nunca cero.
5. **Conjunto de tools mínimo.** `count_ips` (`COUNT DISTINCT codigo_prestador`), `count_sedes` (`COUNT DISTINCT sede_id`), `sum_capacidad`, `top_n` y `group_by` comparten un mismo objeto de filtros (departamento, municipio, naturaleza, nivel_atencion). `buscar_ips` resuelve nombres. Pocas tools con esquemas claros reducen errores de selección del modelo.
6. **Envoltorio común de resultado.** Todo resultado es JSON compacto con `valor`, `filtros`, `filas_usadas`, `fecha_corte` y `origen`, más `estado` (`ok`, `sin_resultados`, `no_encontrado`, `ambiguo`). Mantenerlo corto reduce tokens y latencia en la sesión Realtime. Máximo 10 elementos por resultado.
7. **Lugares inexistentes no devuelven cero.** Si el filtro de departamento o municipio no existe en los datos, la tool devuelve `no_encontrado` con hasta 3 sugerencias por similitud, para que el agente pida aclaración en lugar de afirmar "cero IPS".
8. **Desambiguación en `buscar_ips`.** Búsqueda sobre `nombre_prestador_norm` y `nombre_sede_norm` con coincidencia aproximada; si hay más de un candidato plausible devuelve `ambiguo` con la lista (máx. 10) y el agente pregunta cuál.
9. **Instrucciones de sesión concisas.** Las reglas de grounding, estilo hablado y honestidad se escriben como instrucciones breves de la sesión Realtime; los datos concretos (cobertura, grano, corte) llegan en el brief y en los resultados, no se duplican en el prompt. Alternativa: prompt largo con todo el perfil; descartada por latencia y por riesgo de que el modelo responda de memoria.
10. **Presupuesto de llamadas.** Una o dos llamadas a tools por turno, para sostener la latencia. Las preguntas compuestas se cubren con `group_by` o `top_n` con filtros, no con cadenas de llamadas.
11. **Brief como respuesta inicial.** Al conectar la fuente, el servidor construye el brief determinista desde el perfil y lo emite como respuesta inicial de la sesión (el modelo lo habla; el texto base viene del servidor para no inventar). Las preguntas sugeridas se validan ejecutándolas contra las tools.
12. **Preguntas de oro como contrato de calidad.** El conjunto de pruebas con respuesta calculada por SQL se regenera desde el snapshot; el agente debe coincidir con ellas.

## Risks / Trade-offs

- [El modelo elige mal la tool o los filtros] → Esquemas con enums y descripciones precisas; preguntas de oro que cubren los casos difíciles.
- [Nombres de lugar con grafías distintas (tildes, "Bogotá D.C")] → Filtros comparados contra columnas `*_norm`; sugerencias cuando no hay coincidencia.
- [Dato ausente interpretado como cero (nivel de atención privado)] → Regla de grounding explícita y estado `sin_cobertura` en el resultado cuando se filtra por nivel y naturaleza no pública.
- [Cifras habladas poco naturales] → Redondeo y estilo definidos en `agent-grounding`; el resultado conserva el valor exacto para la UI.
- [Resultado muy largo degrada la voz] → Tope de 10 elementos y JSON compacto; el agente resume en 1 a 3 frases.
- [Dependencia de un solo proveedor de voz a voz] → Tools y reglas son independientes del proveedor; solo el registro de function tools es específico de Realtime.

## Open Questions
- Modelo: valor provisional `gpt-realtime-mini` en `.env.example`; si falla alguna pregunta de oro, se cambia `OPENAI_REALTIME_MODEL` al modelo completo y se registra el resultado.
- Umbral de similitud de `buscar_ips`, de las sugerencias de lugar y de la resolución de `descripcion_capacidad` (TBD; se calibra con pruebas).
- Voz y tono de la sesión Realtime (TBD; pertenece a `realtime-voice`).
