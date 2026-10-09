## Why

El agente debe responder por voz solo con evidencia verificable de la tabla `ips` (dataset `s2ru-bqt6`). Sin tools con argumentos acotados, el modelo tendería a inventar cifras o a contar filas como IPS; sin reglas de honestidad, respondería "cero" donde el dato simplemente no existe (por ejemplo, el nivel de atención de IPS privadas). Además, el criterio de UX/demo exige que el agente explique primero de qué trata la fuente y qué se le puede preguntar.

## What Changes

- Tools de consulta con argumentos validados (enums tomados del perfil) y sin SQL libre: `count_ips`, `count_sedes`, `sum_capacidad`, `top_n`, `group_by` y `buscar_ips`.
- Resultados con un formato común (valor, filtros aplicados, filas usadas, fecha de corte, origen), acotados a 10 elementos, con "no encontrado" más sugerencias para lugares inexistentes.
- Reglas de grounding como instrucciones de sesión: solo evidencia de tools, honestidad sobre lo que está fuera de la fuente, tratamiento de `nivel_atencion`, cita de la fecha de corte, conteo por prestadores distintos y estilo hablado.
- Brief inicial generado a partir del perfil del dataset y emitido como respuesta inicial de la sesión, con 3 a 5 preguntas sugeridas respondibles con las tools.
- Conjunto de preguntas de oro con respuesta esperada calculada por SQL para medir que el agente coincide con los datos.

El agente corre sobre OpenAI Realtime (voz a voz), con el modelo configurable mediante `OPENAI_REALTIME_MODEL`. Las tools se registran como function tools de la sesión Realtime y se ejecutan del lado del servidor contra DuckDB; sus resultados vuelven como salida de la función en JSON compacto. El transporte, los eventos y la latencia pertenecen al change `realtime-voice`.

## Capabilities

### New Capabilities
- `agent-tools`: function tools de consulta sobre `ips` con argumentos validados, formato común de resultado, límites y manejo de lugares inexistentes.
- `agent-grounding`: reglas de honestidad, cobertura de datos, cita del corte, conteo correcto y estilo hablado del agente.
- `session-brief`: brief inicial de la sesión con alcance, antigüedad, limitaciones y preguntas sugeridas.

### Modified Capabilities

(ninguna)

## Impact

- Código nuevo en el backend FastAPI (`agent/tools`, `agent/instructions`, `agent/brief`); sin cambios en el frontend.
- Depende de la tabla `ips` y del perfil de `data-ingestion` (enums, grano, cobertura, fecha de corte, origen).
- Variables de entorno: `OPENAI_API_KEY` y `OPENAI_REALTIME_MODEL`, solo en el backend.
- El contrato de eventos WebSocket se define una sola vez en `realtime-voice` y este change lo referencia sin repetirlo.
