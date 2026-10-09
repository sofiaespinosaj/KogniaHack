# Backend

FastAPI (Python 3.12) que carga el dataset `s2ru-bqt6` (IPS de Colombia, datos.gov.co) en DuckDB y
lo expone al agente. Los datos salen de `data/snapshot.parquet` al arrancar y se refrescan en segundo
plano desde la API SODA3 si hay token.

## Ejecutar

```bash
cd backend
uv sync
cp .env.example .env        # completa los valores; .env no se versiona
uv run uvicorn app.main:app --port 8000
uv run pytest
```

## Configuración (variables de entorno)

| Variable | Por defecto | Notas |
|---|---|---|
| `SODA_APP_TOKEN` | — | Opcional si hay snapshot: sin él se omite el refresco. |
| `SODA_PAGE_SIZE` / `SODA_CONCURRENCY` / `SODA_MAX_TRIES` | 1000 / 4 / 5 | Descarga paginada desde SODA3. |
| `DATA_PATH` | `data` | Carpeta con `snapshot.parquet` y `snapshot.meta.json`. |
| `CORS_ORIGINS` | vacío | Orígenes permitidos, separados por comas. En desarrollo: `http://localhost:5173`. |
| `VOICE_ENABLED` | `false` | Con `true`, `OPENAI_API_KEY` y `DEEPGRAM_API_KEY` son obligatorias. |
| `OPENAI_REALTIME_MODEL` | `gpt-realtime-mini` | Elegido en el spike (`scripts/spike_audio_results.json`). |
| `REALTIME_VOICE` | `marin` | Provisional, a confirmar de oído en español. |
| `OPENAI_INPUT_TRANSCRIPTION_MODEL` | `gpt-live-transcribe` | Transcripción de entrada (respaldo si falla Deepgram). |
| `VAD_TYPE` | `server_vad` | `server_vad` (decidido en el spike) o `semantic_vad`. |
| `VAD_THRESHOLD` / `VAD_PREFIX_PADDING_MS` / `VAD_SILENCE_MS` | 0,5 / 300 / 500 | Solo con `server_vad`. `VAD_SILENCE_MS` se publica como `vad_silence_ms`. |
| `VAD_EAGERNESS` | `auto` | Solo con `semantic_vad`. |
| `ECHO_WINDOW_MS` | `0` | Ventana anti-eco tras el primer audio del agente (TBD, calibrar). Con valor > 0 el relé decide el barge-in. |
| `DEEPGRAM_MODEL` | `nova-3` | Siempre con `language=es` y `diarize=true`. |
| `WS_MAX_SESSIONS` / `WS_SESSIONS_PER_MINUTE` | 3 / 10 | Sesiones de voz simultáneas y nuevas por IP y minuto. |
| `SESSION_MAX_SECONDS` / `SESSION_WARN_SECONDS` | 900 / 780 | Duración máxima (15 min) y aviso (13 min). |
| `OPENAI_REALTIME_URL` / `DEEPGRAM_URL` | URLs oficiales | Solo para pruebas con los servicios simulados. |

Si falta una variable obligatoria el proceso termina nombrándola, sin imprimir valores.

## Endpoints

Todos devuelven JSON. `/profile` y `/api/brief` responden `503` con `{"error", "status"}` mientras no
haya datos cargados.

### `GET /health`

| Campo | Descripción |
|---|---|
| `status` | `loading`, `ready`, `degraded` (datos servibles pero el conteo no coincide con `snapshot.meta.json`) o `unavailable` (sin snapshot y sin descarga posible). |
| `error` | Motivo legible del último problema, o `null`. Nunca contiene secretos. |
| `data.dataset` | Identificador del dataset (`s2ru-bqt6`). |
| `data.source` | Origen de los datos cargados: `snapshot` o `api`. |
| `data.loaded_at` | Fecha y hora de carga (UTC, ISO 8601). |
| `data.rows` | Filas de la tabla `ips` (una fila es una sede × ítem de capacidad). |
| `data.fecha_corte` | Fecha de corte de los datos (`2022-11-05` en el snapshot actual). |
| `data.refresh_skipped_reason` | Por qué no hay refresco (p. ej. falta `SODA_APP_TOKEN`), o `null`. |
| `data.conversion_failures` | Valores no convertibles por columna tipada (quedan nulos). |

### `GET /profile`

Perfil calculado una vez por carga o refresco y servido desde memoria.

| Campo | Descripción |
|---|---|
| `grain` | Qué representa una fila. |
| `definitions` | Cómo se cuentan `ips` (`COUNT(DISTINCT codigo_prestador)`) y `sedes` (`COUNT(DISTINCT sede_id)`). |
| `counting_guidance` | Aviso: las IPS se cuentan como prestadores distintos, nunca filas. |
| `rows`, `ips_distintas`, `sedes_distintas` | Conteos totales. |
| `columns[]` | Por columna: `name`, `type`, `nulls`, `null_pct`, `distinct` y, salvo identificadores, contactos y `*_norm`: `values` (`[{value, count}]`) y `values_complete`. Con 50 distintos o menos `values` trae todos los valores (`values_complete: true`); con más, solo los 10 principales (`false`). |
| `coverage.nivel_atencion` | `null_rows`, `null_pct`, `rows_with_level_publica`, `rows_with_level_privada`. |
| `coverage.notes[]` | Limitaciones de cobertura en texto. |
| `naturaleza` | Filas por naturaleza jurídica. |
| `fecha_corte`, `source` | Fecha de corte y origen (`api` o `snapshot`). |

### `GET /api/brief`

Brief inicial de la sesión, determinista: el mismo perfil produce el mismo brief y se reconstruye tras
cada refresco. Las preguntas se validan ejecutándolas contra las tools.

| Campo | Descripción |
|---|---|
| `texto` | Texto del brief (hablado, de unos 20 s): alcance, cifras, corte, grano y cobertura. |
| `preguntas` | De 3 a 5 preguntas sugeridas, todas respondibles con las tools. |
| `fecha_corte` | Fecha de corte de los datos. |
| `origen` | `snapshot` o `api`. |

## CORS y protección del WebSocket

`CORS_ORIGINS` define los orígenes permitidos; otros orígenes no reciben cabeceras CORS. Para desarrollo
con Vite use `CORS_ORIGINS=http://localhost:5173` (ya es el valor de `.env.example`). Se admiten patrones con
`*` para las vistas previas de Vercel, p. ej. `https://*.vercel.app`.

El WebSocket `/ws` valida el `Origin` del handshake con la misma lista (un origen no permitido recibe HTTP 403;
sin `Origin`, como en la prueba de humo, se acepta), limita las sesiones simultáneas y las nuevas por IP
(tomada de `X-Forwarded-For` detrás del proxy de la plataforma) y la duración. Cada límite responde
`session_limit` con `detail.reason` (`concurrent`, `rate` o `duration`) y se registra con la IP, sin claves.

## Voz: relé con OpenAI Realtime y Deepgram

`app/voice/relay.py` abre por sesión una conexión servidor a servidor con OpenAI Realtime (PCM16 24 kHz,
tools de `grounded-agent` ejecutadas en el servidor, transcripción de entrada siempre activa) y
`app/voice/deepgram.py` bifurca el mismo audio a Deepgram (`nova-3`, `es`, `diarize=true`) en tareas
propias: Deepgram nunca retrasa a OpenAI. Barge-in: al detectar voz con una respuesta en curso se envía
`audio.clear`, se cancela la respuesta y se trunca el elemento al punto reproducido según `playback.position`.

### Pruebas sin claves

`scripts/fake_services.py` simula OpenAI Realtime y Deepgram (VAD por energía, una tool por pregunta,
hablantes alternos). Lo usan `tests/test_relay.py` y la prueba de extremo a extremo con el frontend:

```bash
scripts/e2e_local.sh          # desde la raíz: simulados + backend + Vite + Chromium con micrófono falso
```

### Preguntas de oro por voz

```bash
uv run python -m scripts.voice_golden --url wss://<backend>/ws --runs 20 --out informe.json
```

Envía el audio de `tests/audio/gold` a ritmo real y reporta mediana y p95 de `first_audio_ms` y la latencia
percibida (`vad_silence_ms` + `first_audio_ms`). Falla si la mediana supera 1.500 ms; el p95 de 2.500 ms es
una meta orientativa.

## Eventos del WebSocket (contrato 1.0)

Un solo WebSocket por sesión: `ws://<host>/ws` (en producción `wss://`). Los frames se distinguen por tipo:

- **Binarios = audio**, siempre PCM16 mono 24 kHz little-endian, frames de 40 ms (1.920 bytes). Cliente→servidor es el
  micrófono; servidor→cliente es la voz del agente.
- **Texto = JSON** con `type` y `v` (versión mayor, `1`). Los mensajes del servidor llevan además `seq`, estrictamente
  creciente por conexión. `ts` y `ts_end` son milisegundos desde el inicio de la sesión.

El contrato se define en `app/ws/protocol.py` (fuente de verdad). De ahí se exportan, con un comando reproducible,
[`contract/ws-events.schema.json`](contract/ws-events.schema.json) y los tipos de
[`contract/ws-events.ts`](contract/ws-events.ts) para el frontend:

```bash
uv run python -m app.ws.export all            # regenera ambos
uv run python -m app.ws.export all --check    # falla si están desactualizados (también lo hace una prueba)
```

### Cliente → servidor

```json
{"type": "session.start", "v": 1, "protocol": "1.0", "brief": "speak", "audio_out": true}
{"type": "session.stop", "v": 1}
{"type": "text.message", "v": 1, "text": "¿Cuántas IPS hay en Antioquia?"}
{"type": "playback.position", "v": 1, "turn_id": "t-0003", "played_ms": 1840}
```

`brief` es `speak` o `skip` (con `skip` no se habla el brief ni se emite `session.brief`; úselo al reconectar).
`audio_out` en falso hace que el agente responda solo con texto. `playback.position` informa cuántos milisegundos del
audio del turno se han reproducido (se usa para truncar tras una interrupción).

### Servidor → cliente

Estado de la sesión (`conectando`, `listo`, `escuchando`, `pensando`, `hablando`, `error`). `protocol` y `voice` van en
`conectando` y `listo`; `voice` indica si la voz está `enabled` o `disabled`:

```json
{"type": "session.state", "v": 1, "seq": 1, "state": "conectando", "protocol": "1.0", "voice": "enabled"}
{"type": "session.state", "v": 1, "seq": 2, "state": "escuchando"}
```

Brief (mismos `texto`, `preguntas`, `fecha_corte` y `origen` que `GET /api/brief`), siempre bajo el turno `t-0000`:

```json
{"type": "session.brief", "v": 1, "seq": 3, "turn_id": "t-0000", "texto": "Tengo datos de IPS públicas y privadas…", "preguntas": ["¿Cuántas IPS hay en total?", "¿Qué departamento tiene más IPS?"], "fecha_corte": "2022-11-05", "origen": "snapshot"}
```

Transcripción del usuario. Los eventos con el mismo `utt_id` son versiones sucesivas del mismo enunciado y el final
reemplaza a los parciales. `speaker` es `speaker_N` (con etiquetas), `user` (sin etiquetas) o `agent`; `source` es
`deepgram`, `openai` o `text`:

```json
{"type": "transcript.partial", "v": 1, "seq": 14, "turn_id": "t-0002", "utt_id": "u-0005", "speaker": "speaker_1", "ts": 31250, "text": "cuántas IPS públicas", "source": "deepgram", "degraded": false}
{"type": "transcript.final", "v": 1, "seq": 17, "turn_id": "t-0002", "utt_id": "u-0005", "speaker": "speaker_1", "ts": 31250, "ts_end": 33480, "text": "¿Cuántas IPS públicas hay en Antioquia?", "source": "deepgram", "degraded": false}
```

Texto del agente (acumulado; `final` cierra el turno; `interrupted` marca que se cortó):

```json
{"type": "agent.text", "v": 1, "seq": 25, "turn_id": "t-0002", "text": "En Antioquia hay unas 840 IPS", "final": false, "interrupted": false}
```

Audio del agente. `audio.start` precede a los frames binarios del turno y `audio.end` los sigue. Tras `audio.clear` el
cliente **vacía su cola y descarta todos los frames binarios que reciba hasta el siguiente `audio.start`**, sea cual sea
el turno al que pertenezcan:

```json
{"type": "audio.start", "v": 1, "seq": 20, "turn_id": "t-0002", "format": "pcm16", "sample_rate": 24000}
{"type": "audio.end", "v": 1, "seq": 30, "turn_id": "t-0002"}
{"type": "audio.clear", "v": 1, "seq": 31, "turn_id": "t-0002"}
```

Evidencia de las tools (sin SQL ni claves; listas de 10 elementos como máximo):

```json
{"type": "agent.tool", "v": 1, "seq": 22, "turn_id": "t-0002", "call_id": "c-01", "name": "count_ips", "args": {"departamento": "Antioquia"}, "status": "done", "summary": {"valor": 837, "filtros": {"departamento": "Antioquia"}, "filas_usadas": 4410, "fecha_corte": "2022-11-05", "origen": "snapshot", "estado": "ok"}}
```

Sentimiento por enunciado (asíncrono; llega después del `transcript.final`, a veces después de eventos de turnos
posteriores: se asocia por `turn_id` y `utt_id`; `score` va de -1 a 1):

```json
{"type": "sentiment", "v": 1, "seq": 40, "turn_id": "t-0002", "utt_id": "u-0005", "speaker": "speaker_1", "sentiment": "neutral", "emotion": "curiosidad", "score": 0.1}
```

Métricas del turno, medidas en el servidor. `vad_silence_ms` es el silencio configurado del VAD y **no aparece con
`semantic_vad`**. La latencia percibida es `vad_silence_ms + first_audio_ms`. Un turno interrumpido antes del primer
audio omite `first_audio_ms` e incluye `interrupted`:

```json
{"type": "metrics", "v": 1, "seq": 45, "turn_id": "t-0002", "first_audio_ms": 1120, "vad_silence_ms": 500, "tool_ms": 85, "total_ms": 4300}
{"type": "metrics", "v": 1, "seq": 46, "turn_id": "t-0003", "total_ms": 900, "interrupted": true}
```

Errores tipificados: `code`, `message` en español (sin trazas, SQL ni claves), `severity` (`warning` o `fatal`),
`recoverable` y un `detail` opcional. Códigos: `voice_disabled`, `session_already_active`, `session_limit`,
`unsupported_protocol`, `invalid_message`, `no_active_session`, `origin_not_allowed`, `session_expiring`,
`openai_unavailable`, `deepgram_unavailable`, `data_unavailable` e `internal`:

```json
{"type": "error", "v": 1, "seq": 50, "code": "deepgram_unavailable", "message": "La transcripción con hablantes no está disponible; se muestra una transcripción sin etiquetas.", "severity": "warning", "recoverable": true}
{"type": "error", "v": 1, "seq": 51, "code": "unsupported_protocol", "message": "La versión del protocolo no está soportada.", "severity": "fatal", "recoverable": false, "detail": {"supported": ["1.0"]}}
{"type": "error", "v": 1, "seq": 52, "code": "invalid_message", "message": "El mensaje no es válido.", "severity": "warning", "recoverable": true, "detail": {"reason": "falta el campo type"}}
{"type": "error", "v": 1, "seq": 53, "code": "session_limit", "message": "Se alcanzó un límite de sesiones.", "severity": "fatal", "recoverable": true, "detail": {"reason": "rate"}}
{"type": "error", "v": 1, "seq": 54, "code": "session_expiring", "message": "La sesión está por terminar.", "severity": "warning", "recoverable": true, "detail": {"seconds_left": 120}}
```

### Orden y reglas

- Los mensajes JSON se entregan en orden de `seq`; el `seq` no se repite ni retrocede dentro de una conexión.
- Orden relativo dentro de un turno con tool: `transcript.final`, `agent.tool`, `audio.start`, `agent.text` final y
  `metrics`. `sentiment` y `metrics` pueden llegar después de eventos del turno siguiente.
- Ciclo de estados de un turno: `escuchando`, `pensando`, `hablando`, `escuchando`. Un error fatal de la voz pasa a
  `error` y la conexión sigue abierta: un nuevo `session.start` crea una sesión nueva.
- Sin reanudación: cada conexión es una sesión nueva (`seq` desde 1 y `turn_id` desde `t-0001`). Tras un corte, el
  cliente reconecta con espera exponencial y envía `session.start` con `brief` igual a `skip`; conserva su
  transcripción local.
- Una versión mayor no soportada recibe `unsupported_protocol` con `detail.supported`.
- Fuente del texto visible: del usuario, Deepgram (`source: "deepgram"`); del agente, la transcripción de salida de
  OpenAI. Si Deepgram falla, el texto del usuario pasa a OpenAI con `degraded: true` y `speaker: "user"`; las dos
  fuentes nunca se mezclan en un mismo enunciado.
