## 0. Spike de modelo (30 minutos)

- [x] 0.1 Escribir un script mínimo (`backend/scripts/spike_realtime.py`) que abra OpenAI Realtime, registre las tools de `agent-tools`, envíe una pregunta por texto y reciba el audio de respuesta
- [x] 0.2 Medir `first_audio_ms` (envío de la pregunta a primer fragmento de audio) con `gpt-realtime-mini` y con el modelo completo, en varias repeticiones con y sin tool
- [x] 0.3 Comprobar si el modelo soporta `semantic_vad` y verificar en la documentación vigente el modelo de transcripción de entrada más barato recomendado
- [x] 0.4 Registrar los resultados y fijar el valor de `OPENAI_REALTIME_MODEL` y del VAD antes de construir el relé — Resultado: `gpt-realtime-mini` con `server_vad` (regla d de `scripts/spike_audio_results.json`; ningún candidato cumplió la regla a, la precisión de cifras fue 77,8 % y se marcó `needs_filter_guard`). Por defecto `VAD_TYPE=server_vad`. El guardián de filtros inventados queda pendiente (TBD, `grounded-agent`).

## 1. Configuración y arranque de la voz

- [x] 1.1 Añadir a la configuración y a `.env.example`: `VOICE_ENABLED`, `REALTIME_VOICE=marin` (provisional, a confirmar de oído en español), `OPENAI_REALTIME_MODEL`, `OPENAI_INPUT_TRANSCRIPTION_MODEL`, parámetros del VAD (valores del spike o `server_vad` con umbral 0,5, relleno previo 300 ms y silencio 500 ms), límites de la protección del WebSocket y `DEEPGRAM_MODEL=nova-3`; exigir `OPENAI_API_KEY` y `DEEPGRAM_API_KEY` solo con `VOICE_ENABLED=true`, fallando con mensaje claro y sin imprimir valores
- [x] 1.2 Informar el estado de la voz (`enabled` o `disabled`) en `/health`; el despliegue fija `VOICE_ENABLED=true` (se coordina con `deployment-readme`)
- [x] 1.3 Añadir las dependencias de cliente WebSocket para OpenAI Realtime y Deepgram y verificar que el entorno instala limpio

## 2. Contrato de eventos (`ws-event-contract`)

- [x] 2.1 Definir los modelos de mensajes (cliente a servidor y servidor a cliente) con versión `1.0`, `type`, `v` y `seq`, validados por esquema
- [x] 2.2 Implementar el endpoint WebSocket único con distinción de frames binarios (audio de 40 ms) y JSON, y los errores `invalid_message`, `no_active_session` y `unsupported_protocol`
- [x] 2.3 Implementar la máquina de estados de `session.state` y las reglas de orden y numeración por `seq`
- [x] 2.4 Publicar el contrato con los ejemplos JSON en el `backend/README.md` (sección de eventos)
- [x] 2.5 Alinear `session.brief` con `GET /api/brief` (mismos `texto`, `preguntas`, `fecha_corte`, `origen`); el endpoint REST ya existe, verificar que ambos usan la misma fuente
- [x] 2.6 Probar el contrato con un cliente simulado: inicio, turno completo, mensaje inválido, reconexión y versión no soportada
- [x] 2.7 Exportar el JSON Schema desde los modelos a `backend/contract/ws-events.schema.json` con un comando reproducible
- [x] 2.8 Generar los tipos TypeScript del frontend desde el esquema (generador y ruta TBD) con un comando reproducible — Hecho: el frontend copia `backend/contract/ws-events.ts` a `frontend/src/api/ws-events.gen.ts` (`npm run contract`) y `contract-check.ts` hace fallar la compilación si `types.ts` diverge.
- [x] 2.9 Añadir una prueba que valide todos los ejemplos JSON del README contra el esquema y otra que falle si el esquema publicado no coincide con los modelos
- [x] 2.10 Incluir `vad_silence_ms` en `metrics` (ausente con `semantic_vad`) y `detail` en los errores; documentar que tras `audio.clear` el cliente descarta los frames binarios hasta el siguiente `audio.start`

## 3. Relé hacia OpenAI Realtime

- [x] 3.1 Abrir la conexión servidor a servidor con OpenAI por sesión con modelo y voz de entorno, audio PCM16 24 kHz, transcripción de entrada siempre activa y las instrucciones de `agent-grounding`
- [x] 3.2 Registrar las function tools de `agent-tools` y ejecutar las llamadas en el servidor devolviendo la salida de la función; emitir `agent.tool` con el resumen
- [x] 3.3 Reenviar el audio del micrófono a OpenAI y el audio de respuesta al cliente con `audio.start` y `audio.end`
- [x] 3.4 Emitir `agent.text` desde la transcripción de salida de OpenAI (acumulado, `final`, `interrupted`)
- [x] 3.5 Emitir el brief como primera respuesta bajo `t-0000` (o saltarlo con `brief` igual a `skip`)
- [x] 3.6 Implementar la entrada `text.message` y el modo sin audio (`audio_out` en falso)

## 4. Latencia, VAD e interrupciones

- [ ] 4.1 Configurar el VAD de OpenAI (`semantic_vad` si el modelo lo soporta; si no, `server_vad` con 0,5 / 300 ms / 500 ms) y ajustarlo con las preguntas de oro en español — Configurado (`server_vad` 0,5 / 300 / 500); el ajuste fino con las preguntas de oro en español queda pendiente de claves reales.
- [x] 4.2 Medir `first_audio_ms` (fin de habla del VAD a primer frame enviado), `tool_ms` y `total_ms` por turno y emitir `metrics` con `vad_silence_ms`
- [x] 4.3 Implementar el barge-in: `audio.clear`, cancelación de la respuesta, truncado según `playback.position` y texto marcado como interrumpido; medir el tiempo hasta `audio.clear` frente a la meta de 300 ms — Probado con servicios simulados (`tests/test_relay.py`): `audio.clear` < 300 ms desde la detección en local; falta medirlo contra OpenAI real (7.3).
- [ ] 4.4 Ignorar detecciones de voz durante la ventana corta posterior al inicio del audio del agente para evitar eco (valor TBD, calibrar) — Implementado como `ECHO_WINDOW_MS` (por defecto 0: sin ventana); el valor sigue TBD hasta calibrar con audio real.

## 5. Deepgram y degradación

- [x] 5.1 Bifurcar el mismo audio PCM16 24 kHz a Deepgram streaming (`nova-3`, `language=es`, `diarize=true`) en una tarea independiente de la ruta de OpenAI
- [ ] 5.2 Verificar la diarización con un audio de prueba de dos voces: deben distinguirse dos hablantes — Pendiente con Deepgram real (requiere `DEEPGRAM_API_KEY`); con el Deepgram simulado se prueba el mapeo a dos hablantes.
- [x] 5.3 Emitir `transcript.partial` y `transcript.final` con `turn_id`, `utt_id`, `speaker`, `ts` y `source` (las reglas de etiquetado se implementan en `diarized-transcript`)
- [x] 5.4 Degradar a la transcripción de entrada de OpenAI sin etiquetas, con `degraded` en verdadero y aviso `deepgram_unavailable` en 2 s o menos; reintentar Deepgram en segundo plano
- [x] 5.5 Manejar la caída de OpenAI con `openai_unavailable`, estado `error`, WebSocket abierto y reintento con un nuevo `session.start`
- [x] 5.6 Probar la degradación con fallos simulados de Deepgram y de OpenAI

## 6. Ciclo de vida y protección del WebSocket

- [x] 6.1 Permitir una sola sesión de voz por conexión (`session_already_active`)
- [x] 6.2 Validar `Origin` contra `CORS_ORIGINS` y rechazar con HTTP 403 los orígenes no permitidos
- [x] 6.3 Limitar a 3 las sesiones simultáneas y a 10 por minuto las sesiones nuevas por IP; responder `session_limit` con `detail.reason` y registrar cada límite sin claves
- [x] 6.4 Aplicar la duración máxima de 15 minutos con aviso `session_expiring` a los 13 y cierre ordenado con `session_limit`
- [x] 6.5 Liberar las conexiones a OpenAI y Deepgram y las tareas al cerrar por cualquier causa en 5 s o menos; prueba de cierre abrupto
- [x] 6.6 Verificar que ningún mensaje al cliente contiene SQL, claves ni trazas, y que las claves no aparecen en logs
- [x] 6.7 Pruebas de cada límite (origen, simultáneas, por IP, duración) con el registro correspondiente

## 7. Verificación de voz

- [x] 7.1 Crear la prueba de las preguntas de oro por voz (o con audio sintético) con unas 20 corridas, que registre `first_audio_ms` y `vad_silence_ms` por turno y reporte mediana, p95 y latencia percibida — `scripts/voice_golden.py`; verificado en local contra los simulados.
- [ ] 7.2 Ejecutarla contra el backend desplegado: falla si la mediana de `first_audio_ms` supera 1.500 ms; el p95 de 2.500 ms es meta orientativa. Si falla, probar el modelo completo cambiando `OPENAI_REALTIME_MODEL` — Pendiente: requiere el backend desplegado con claves reales (`deployment-readme`).
- [ ] 7.3 Probar el barge-in de extremo a extremo: el agente calla, el cliente vacía la cola, descarta los frames hasta el siguiente `audio.start` y el texto queda truncado — Pendiente con OpenAI real; la versión simulada pasa (`test_barge_in_clears_audio_cancels_and_truncates` y `scripts/e2e_local.sh`).
