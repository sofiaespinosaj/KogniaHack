## ADDED Requirements

### Requirement: Versión y estructura de los mensajes
El contrato SHALL identificar su versión (`"1.0"`) en `session.start` y en `session.state`, SHALL usar mensajes de texto JSON con los campos `type` y `v` (entero de versión mayor, `1`) y SHALL añadir `seq` (entero creciente por sesión) a todo mensaje del servidor al cliente. Los campos `ts` y `ts_end` SHALL expresarse en milisegundos desde el inicio de la sesión.

#### Scenario: Versión aceptada
- **WHEN** el cliente envía `session.start` con `protocol` igual a `"1.0"`
- **THEN** el servidor responde con `session.state` que incluye `protocol` igual a `"1.0"`

#### Scenario: Versión no soportada
- **WHEN** el cliente envía `session.start` con una versión mayor no soportada
- **THEN** el servidor responde con el error `unsupported_protocol` y la lista de versiones soportadas

#### Scenario: Numeración
- **WHEN** el servidor emite mensajes JSON
- **THEN** cada uno lleva `seq` y los valores son estrictamente crecientes sin repeticiones

### Requirement: Esquema y tipos publicados
El contrato SHALL publicarse como JSON Schema exportado desde los modelos de mensajes del backend en `backend/contract/ws-events.schema.json` y como tipos TypeScript generados desde ese esquema para el frontend, y el repositorio SHALL incluir una prueba que valide todos los ejemplos JSON del README contra el esquema.

#### Scenario: Esquema exportado
- **WHEN** se ejecuta la exportación del esquema
- **THEN** `backend/contract/ws-events.schema.json` contiene la definición de todos los mensajes del contrato y coincide con los modelos vigentes

#### Scenario: Tipos para el frontend
- **WHEN** se ejecuta la generación de tipos
- **THEN** el frontend dispone de tipos TypeScript de todos los mensajes, generados desde el esquema y no escritos a mano

#### Scenario: Ejemplos del README
- **WHEN** corre la prueba de ejemplos
- **THEN** cada ejemplo JSON del README valida contra el esquema y la prueba falla si alguno no valida

#### Scenario: Esquema desactualizado
- **WHEN** los modelos cambian sin regenerar el esquema
- **THEN** una prueba falla indicando que el esquema publicado está desactualizado

### Requirement: Mensajes del cliente al servidor
El contrato SHALL definir como mensajes del cliente: audio binario, `session.start`, `session.stop`, `text.message` y `playback.position`.

Ejemplos:

```json
{"type": "session.start", "v": 1, "protocol": "1.0", "brief": "speak", "audio_out": true}
{"type": "session.stop", "v": 1}
{"type": "text.message", "v": 1, "text": "¿Cuántas IPS hay en Antioquia?"}
{"type": "playback.position", "v": 1, "turn_id": "t-0003", "played_ms": 1840}
```

`brief` toma los valores `speak` o `skip`. `audio_out` indica si el agente responde con audio. `playback.position` informa cuántos milisegundos de audio del turno se han reproducido.

#### Scenario: Inicio de sesión
- **WHEN** el cliente envía `session.start`
- **THEN** el servidor responde con `session.state` en `conectando` y luego en `listo`

#### Scenario: Fin de sesión
- **WHEN** el cliente envía `session.stop`
- **THEN** el servidor cierra las conexiones externas y responde con `session.state` final antes de cerrar

#### Scenario: Mensaje inválido
- **WHEN** el cliente envía un JSON sin `type` o con un tipo desconocido
- **THEN** el servidor responde con el error `invalid_message` sin cerrar la sesión

### Requirement: Audio binario
El contrato SHALL usar frames binarios exclusivamente para audio PCM16 mono a 24 kHz little-endian en ambos sentidos: del cliente al servidor es el micrófono y del servidor al cliente es la voz del agente, con frames de 40 ms (1.920 bytes).

#### Scenario: Audio del micrófono
- **WHEN** el cliente envía un frame binario durante una sesión activa
- **THEN** el servidor lo trata como audio del micrófono

#### Scenario: Audio fuera de sesión
- **WHEN** llega un frame binario sin sesión activa
- **THEN** el servidor lo descarta y responde con el error `no_active_session`

### Requirement: Estado de la sesión
El servidor SHALL emitir `session.state` con `state` en `conectando`, `listo`, `escuchando`, `pensando`, `hablando` o `error` cada vez que cambie, con `detail` opcional.

Ejemplo:

```json
{"type": "session.state", "v": 1, "seq": 2, "state": "escuchando", "protocol": "1.0", "voice": "enabled"}
```

#### Scenario: Ciclo de un turno
- **WHEN** el usuario habla, el agente consulta una tool y responde
- **THEN** los estados se emiten en el orden `escuchando`, `pensando`, `hablando` y `escuchando`

#### Scenario: Error
- **WHEN** ocurre un error fatal de la voz
- **THEN** el servidor emite `session.state` con `state` igual a `error`

### Requirement: Transcripción del usuario
El servidor SHALL emitir `transcript.partial` y `transcript.final` con `turn_id`, `utt_id`, `speaker`, `ts`, `text` y `source`; `transcript.final` SHALL incluir además `ts_end`. Los eventos con el mismo `utt_id` SHALL ser sucesivas versiones del mismo enunciado y la versión final SHALL reemplazar a las parciales. `speaker` SHALL ser `agent` para el agente y un identificador de hablante humano (`speaker_1`, `speaker_2`, etc.) cuando haya etiquetas, o `user` cuando no las haya. El significado y la estabilización de las etiquetas se definen en `diarized-transcript`.

Ejemplo:

```json
{"type": "transcript.partial", "v": 1, "seq": 14, "turn_id": "t-0002", "utt_id": "u-0005", "speaker": "speaker_1", "ts": 31250, "text": "cuántas IPS públicas", "source": "deepgram", "degraded": false}
{"type": "transcript.final", "v": 1, "seq": 17, "turn_id": "t-0002", "utt_id": "u-0005", "speaker": "speaker_1", "ts": 31250, "ts_end": 33480, "text": "¿Cuántas IPS públicas hay en Antioquia?", "source": "deepgram", "degraded": false}
```

`source` toma los valores `deepgram`, `openai` o `text`.

#### Scenario: Parciales y final
- **WHEN** el usuario dice una frase
- **THEN** el cliente recibe uno o más `transcript.partial` y un `transcript.final` con el mismo `utt_id`, y el final reemplaza a las parciales

#### Scenario: Varios hablantes en un turno
- **WHEN** dos personas hablan dentro del mismo turno
- **THEN** los eventos comparten `turn_id`, tienen `utt_id` distintos y `speaker` distinto

#### Scenario: Fuente degradada
- **WHEN** Deepgram no está disponible
- **THEN** los eventos llevan `source` igual a `openai`, `speaker` igual a `user` y `degraded` en verdadero

### Requirement: Texto del agente
El servidor SHALL emitir `agent.text` con `turn_id`, `text` (acumulado hasta ese momento), `final` e `interrupted`, tomado de la transcripción de salida de OpenAI.

Ejemplo:

```json
{"type": "agent.text", "v": 1, "seq": 25, "turn_id": "t-0002", "text": "En Antioquia hay unas 840 IPS", "final": false, "interrupted": false}
```

#### Scenario: Texto en curso
- **WHEN** el agente va hablando
- **THEN** el cliente recibe `agent.text` con `final` en falso y el texto acumulado

#### Scenario: Texto final
- **WHEN** el agente termina de responder
- **THEN** el cliente recibe `agent.text` con `final` en verdadero y el texto completo

### Requirement: Audio de respuesta
El servidor SHALL delimitar el audio del agente con los mensajes `audio.start` y `audio.end` (con `turn_id`) y SHALL emitir `audio.clear` (con `turn_id`) cuando deba descartarse el audio pendiente por una interrupción, tras lo cual el cliente SHALL descartar todos los frames binarios que reciba hasta el siguiente `audio.start`.

Ejemplo:

```json
{"type": "audio.start", "v": 1, "seq": 20, "turn_id": "t-0002", "format": "pcm16", "sample_rate": 24000}
{"type": "audio.clear", "v": 1, "seq": 31, "turn_id": "t-0002"}
```

#### Scenario: Respuesta hablada
- **WHEN** el agente responde con voz
- **THEN** el cliente recibe `audio.start`, los frames binarios del turno y `audio.end`

#### Scenario: Interrupción
- **WHEN** el usuario interrumpe
- **THEN** el cliente recibe `audio.clear` y los frames binarios de ese turno posteriores a él no se reproducen

#### Scenario: Descarte hasta el siguiente audio.start
- **WHEN** el cliente recibe frames binarios después de `audio.clear` y antes del siguiente `audio.start`
- **THEN** los descarta todos, sin importar el turno al que pertenezcan

#### Scenario: Reanudación del audio
- **WHEN** el cliente recibe un nuevo `audio.start`
- **THEN** vuelve a encolar y reproducir los frames binarios que siguen

### Requirement: Evidencia de las tools
El servidor SHALL emitir `agent.tool` con `turn_id`, `call_id`, `name`, `args`, `status` (`running`, `done` o `error`) y, al terminar, `summary` con los campos del resultado definidos en `agent-tools` (valor, filtros, filas usadas, fecha de corte, origen y estado), de modo que la UI muestre la evidencia.

Ejemplo:

```json
{"type": "agent.tool", "v": 1, "seq": 22, "turn_id": "t-0002", "call_id": "c-01", "name": "count_ips", "args": {"departamento": "Antioquia"}, "status": "done", "summary": {"valor": 837, "filtros": {"departamento": "Antioquia"}, "filas_usadas": 4410, "fecha_corte": "2022-11-05", "origen": "snapshot", "estado": "ok"}}
```

#### Scenario: Tool exitosa
- **WHEN** una tool termina con éxito
- **THEN** el cliente recibe `agent.tool` con `status` igual a `done` y el `summary`

#### Scenario: Sin datos sensibles
- **WHEN** se emite `agent.tool`
- **THEN** no contiene SQL ni claves ni más de 10 elementos de lista

### Requirement: Sentimiento por enunciado
El servidor SHALL emitir `sentiment` con `turn_id`, `utt_id`, `speaker`, `sentiment`, `emotion` y `score` cuando termine el análisis asíncrono de un enunciado final, sin bloquear la voz. `score` SHALL ser un número entre -1 y 1. El análisis y los valores permitidos de `emotion` se definen en `sentiment-emotion`.

Ejemplo:

```json
{"type": "sentiment", "v": 1, "seq": 40, "turn_id": "t-0002", "utt_id": "u-0005", "speaker": "speaker_1", "sentiment": "neutral", "emotion": "curiosidad", "score": 0.1}
```

#### Scenario: Llegada tardía
- **WHEN** el análisis termina después de que el agente empezó a responder
- **THEN** el evento `sentiment` se emite igualmente y el cliente lo asocia por `turn_id` y `utt_id`

### Requirement: Métricas por turno
El servidor SHALL emitir `metrics` con `turn_id` y los campos `first_audio_ms`, `vad_silence_ms` (el silencio configurado del VAD, ausente con `semantic_vad`), `tool_ms` (si hubo tools) y `total_ms`, en milisegundos medidos en el servidor. La latencia percibida SHALL calcularse como `vad_silence_ms` más `first_audio_ms`.

Ejemplo:

```json
{"type": "metrics", "v": 1, "seq": 45, "turn_id": "t-0002", "first_audio_ms": 1120, "vad_silence_ms": 500, "tool_ms": 85, "total_ms": 4300}
```

#### Scenario: Turno completo
- **WHEN** termina un turno con respuesta de voz
- **THEN** el cliente recibe `metrics` con `first_audio_ms` y `total_ms`

#### Scenario: Latencia percibida
- **WHEN** `metrics` trae `vad_silence_ms` igual a 500 y `first_audio_ms` igual a 1.120
- **THEN** la latencia percibida es 1.620 ms

#### Scenario: Turno interrumpido
- **WHEN** el turno fue interrumpido antes del primer audio
- **THEN** `metrics` omite `first_audio_ms` e incluye `interrupted` en verdadero

### Requirement: Errores tipificados
El servidor SHALL emitir `error` con `code`, `message` en español, `severity` (`warning` o `fatal`) y `recoverable` y un objeto opcional `detail` (por ejemplo `reason` o `seconds_left`), usando al menos los códigos `voice_disabled`, `session_already_active`, `session_limit`, `unsupported_protocol`, `invalid_message`, `no_active_session`, `origin_not_allowed`, `session_expiring`, `openai_unavailable`, `deepgram_unavailable`, `data_unavailable` e `internal`.

Ejemplo:

```json
{"type": "error", "v": 1, "seq": 50, "code": "deepgram_unavailable", "message": "La transcripción con hablantes no está disponible; se muestra una transcripción sin etiquetas.", "severity": "warning", "recoverable": true}
```

#### Scenario: Advertencia
- **WHEN** falla Deepgram
- **THEN** el servidor emite `error` con `severity` igual a `warning` y la sesión continúa

#### Scenario: Mensaje sin detalles internos
- **WHEN** se emite cualquier `error`
- **THEN** el mensaje no incluye trazas, SQL ni claves

### Requirement: Brief por evento y por REST
El servidor SHALL emitir `session.brief` con `turn_id` igual a `t-0000` y los campos `texto`, `preguntas`, `fecha_corte` y `origen` al iniciar la sesión, y SHALL exponer exactamente el mismo contenido en `GET /api/brief` para su uso sin voz (esquema ya implementado: `texto`, `preguntas`, `fecha_corte`, `origen`), respondiendo 503 mientras los datos no estén disponibles.

Ejemplo:

```json
{"type": "session.brief", "v": 1, "seq": 3, "turn_id": "t-0000", "texto": "Tengo datos de IPS públicas y privadas…", "preguntas": ["¿Cuántas IPS hay en total?", "¿Qué departamento tiene más IPS?", "¿Cuántas camas hay en Antioquia?"], "fecha_corte": "2022-11-05", "origen": "snapshot"}
```

#### Scenario: Brief por REST
- **WHEN** el cliente llama a `GET /api/brief` con la voz apagada
- **THEN** recibe `texto`, `preguntas`, `fecha_corte` y `origen`

#### Scenario: Brief por evento
- **WHEN** la sesión pasa a `listo`
- **THEN** el cliente recibe `session.brief` con el mismo `texto`, `preguntas`, `fecha_corte` y `origen` que `GET /api/brief`

### Requirement: Reglas de orden
El contrato SHALL garantizar que los mensajes JSON de una sesión se entregan en orden de `seq`, que `audio.start` precede a los frames de su turno y `audio.end` los sigue, que el `transcript.final` de un enunciado precede a su `sentiment` y que `metrics` de un turno llega después de `agent.text` final. SHALL permitir que `sentiment` y `metrics` lleguen después de eventos de turnos posteriores, por lo que el cliente los asocia por `turn_id`.

#### Scenario: Orden dentro de un turno
- **WHEN** se completa un turno con tool
- **THEN** el cliente recibe `transcript.final`, `agent.tool`, `audio.start`, `agent.text` final y `metrics` en ese orden relativo

#### Scenario: Evento tardío
- **WHEN** `sentiment` de un turno llega después del primer evento del turno siguiente
- **THEN** el cliente lo asocia por `turn_id` y no lo atribuye al turno actual

### Requirement: Reconexión
El contrato SHALL tratar cada conexión como una sesión nueva sin reanudación, SHALL permitir que el cliente reconecte con espera exponencial y envíe `session.start` con `brief` igual a `skip`, y SHALL numerar los `turn_id` desde `t-0001` en la nueva sesión; el cliente conserva su transcripción local.

#### Scenario: Reconexión tras corte de red
- **WHEN** el WebSocket se corta y el cliente reconecta
- **THEN** el servidor crea una sesión nueva, reinicia `seq` y `turn_id`, y el cliente identifica la separación en su historial

### Requirement: Fuente de verdad del texto visible
El contrato SHALL establecer que el texto visible del usuario proviene de Deepgram (`source` igual a `deepgram`) y el del agente de la transcripción de salida de OpenAI, que el texto de OpenAI para el usuario solo se emite como respaldo marcado `degraded` y que ambas fuentes nunca se mezclan en un mismo enunciado.

#### Scenario: Funcionamiento normal
- **WHEN** Deepgram está disponible
- **THEN** ningún `transcript.*` con `source` igual a `openai` llega al cliente

#### Scenario: Texto del agente
- **WHEN** el agente responde
- **THEN** `agent.text` se construye solo con la transcripción de salida de OpenAI
