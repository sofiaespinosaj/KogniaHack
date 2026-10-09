## 0. Spike de modelo (30 minutos)

- [ ] 0.1 Escribir un script mínimo (`backend/scripts/spike_realtime.py`) que abra OpenAI Realtime, registre las tools de `agent-tools`, envíe una pregunta por texto y reciba el audio de respuesta
- [ ] 0.2 Medir `first_audio_ms` (envío de la pregunta a primer fragmento de audio) con `gpt-realtime-mini` y con el modelo completo, en varias repeticiones con y sin tool
- [ ] 0.3 Comprobar si el modelo soporta `semantic_vad` y verificar en la documentación vigente el modelo de transcripción de entrada más barato recomendado
- [ ] 0.4 Registrar los resultados y fijar el valor de `OPENAI_REALTIME_MODEL` y del VAD antes de construir el relé

## 1. Configuración y arranque de la voz

- [ ] 1.1 Añadir a la configuración y a `.env.example`: `VOICE_ENABLED`, `REALTIME_VOICE=marin` (provisional, a confirmar de oído en español), `OPENAI_REALTIME_MODEL`, `OPENAI_INPUT_TRANSCRIPTION_MODEL`, parámetros del VAD (valores del spike o `server_vad` con umbral 0,5, relleno previo 300 ms y silencio 500 ms), límites de la protección del WebSocket y `DEEPGRAM_MODEL=nova-3`; exigir `OPENAI_API_KEY` y `DEEPGRAM_API_KEY` solo con `VOICE_ENABLED=true`, fallando con mensaje claro y sin imprimir valores
- [ ] 1.2 Informar el estado de la voz (`enabled` o `disabled`) en `/health`; el despliegue fija `VOICE_ENABLED=true` (se coordina con `deployment-readme`)
- [ ] 1.3 Añadir las dependencias de cliente WebSocket para OpenAI Realtime y Deepgram y verificar que el entorno instala limpio

## 2. Contrato de eventos (`ws-event-contract`)

- [ ] 2.1 Definir los modelos de mensajes (cliente a servidor y servidor a cliente) con versión `1.0`, `type`, `v` y `seq`, validados por esquema
- [ ] 2.2 Implementar el endpoint WebSocket único con distinción de frames binarios (audio de 40 ms) y JSON, y los errores `invalid_message`, `no_active_session` y `unsupported_protocol`
- [ ] 2.3 Implementar la máquina de estados de `session.state` y las reglas de orden y numeración por `seq`
- [ ] 2.4 Publicar el contrato con los ejemplos JSON en el `backend/README.md` (sección de eventos)
- [ ] 2.5 Alinear `session.brief` con `GET /api/brief` (mismos `texto`, `preguntas`, `fecha_corte`, `origen`); el endpoint REST ya existe, verificar que ambos usan la misma fuente
- [ ] 2.6 Probar el contrato con un cliente simulado: inicio, turno completo, mensaje inválido, reconexión y versión no soportada
- [ ] 2.7 Exportar el JSON Schema desde los modelos a `backend/contract/ws-events.schema.json` con un comando reproducible
- [ ] 2.8 Generar los tipos TypeScript del frontend desde el esquema (generador y ruta TBD) con un comando reproducible
- [ ] 2.9 Añadir una prueba que valide todos los ejemplos JSON del README contra el esquema y otra que falle si el esquema publicado no coincide con los modelos
- [ ] 2.10 Incluir `vad_silence_ms` en `metrics` (ausente con `semantic_vad`) y `detail` en los errores; documentar que tras `audio.clear` el cliente descarta los frames binarios hasta el siguiente `audio.start`

## 3. Relé hacia OpenAI Realtime

- [ ] 3.1 Abrir la conexión servidor a servidor con OpenAI por sesión con modelo y voz de entorno, audio PCM16 24 kHz, transcripción de entrada siempre activa y las instrucciones de `agent-grounding`
- [ ] 3.2 Registrar las function tools de `agent-tools` y ejecutar las llamadas en el servidor devolviendo la salida de la función; emitir `agent.tool` con el resumen
- [ ] 3.3 Reenviar el audio del micrófono a OpenAI y el audio de respuesta al cliente con `audio.start` y `audio.end`
- [ ] 3.4 Emitir `agent.text` desde la transcripción de salida de OpenAI (acumulado, `final`, `interrupted`)
- [ ] 3.5 Emitir el brief como primera respuesta bajo `t-0000` (o saltarlo con `brief` igual a `skip`)
- [ ] 3.6 Implementar la entrada `text.message` y el modo sin audio (`audio_out` en falso)

## 4. Latencia, VAD e interrupciones

- [ ] 4.1 Configurar el VAD de OpenAI (`semantic_vad` si el modelo lo soporta; si no, `server_vad` con 0,5 / 300 ms / 500 ms) y ajustarlo con las preguntas de oro en español
- [ ] 4.2 Medir `first_audio_ms` (fin de habla del VAD a primer frame enviado), `tool_ms` y `total_ms` por turno y emitir `metrics` con `vad_silence_ms`
- [ ] 4.3 Implementar el barge-in: `audio.clear`, cancelación de la respuesta, truncado según `playback.position` y texto marcado como interrumpido; medir el tiempo hasta `audio.clear` frente a la meta de 300 ms
- [ ] 4.4 Ignorar detecciones de voz durante la ventana corta posterior al inicio del audio del agente para evitar eco (valor TBD, calibrar)

## 5. Deepgram y degradación

- [ ] 5.1 Bifurcar el mismo audio PCM16 24 kHz a Deepgram streaming (`nova-3`, `language=es`, `diarize=true`) en una tarea independiente de la ruta de OpenAI
- [ ] 5.2 Verificar la diarización con un audio de prueba de dos voces: deben distinguirse dos hablantes
- [ ] 5.3 Emitir `transcript.partial` y `transcript.final` con `turn_id`, `utt_id`, `speaker`, `ts` y `source` (las reglas de etiquetado se implementan en `diarized-transcript`)
- [ ] 5.4 Degradar a la transcripción de entrada de OpenAI sin etiquetas, con `degraded` en verdadero y aviso `deepgram_unavailable` en 2 s o menos; reintentar Deepgram en segundo plano
- [ ] 5.5 Manejar la caída de OpenAI con `openai_unavailable`, estado `error`, WebSocket abierto y reintento con un nuevo `session.start`
- [ ] 5.6 Probar la degradación con fallos simulados de Deepgram y de OpenAI

## 6. Ciclo de vida y protección del WebSocket

- [ ] 6.1 Permitir una sola sesión de voz por conexión (`session_already_active`)
- [ ] 6.2 Validar `Origin` contra `CORS_ORIGINS` y rechazar con HTTP 403 los orígenes no permitidos
- [ ] 6.3 Limitar a 3 las sesiones simultáneas y a 10 por minuto las sesiones nuevas por IP; responder `session_limit` con `detail.reason` y registrar cada límite sin claves
- [ ] 6.4 Aplicar la duración máxima de 15 minutos con aviso `session_expiring` a los 13 y cierre ordenado con `session_limit`
- [ ] 6.5 Liberar las conexiones a OpenAI y Deepgram y las tareas al cerrar por cualquier causa en 5 s o menos; prueba de cierre abrupto
- [ ] 6.6 Verificar que ningún mensaje al cliente contiene SQL, claves ni trazas, y que las claves no aparecen en logs
- [ ] 6.7 Pruebas de cada límite (origen, simultáneas, por IP, duración) con el registro correspondiente

## 7. Verificación de voz

- [ ] 7.1 Crear la prueba de las preguntas de oro por voz (o con audio sintético) con unas 20 corridas, que registre `first_audio_ms` y `vad_silence_ms` por turno y reporte mediana, p95 y latencia percibida
- [ ] 7.2 Ejecutarla contra el backend desplegado: falla si la mediana de `first_audio_ms` supera 1.500 ms; el p95 de 2.500 ms es meta orientativa. Si falla, probar el modelo completo cambiando `OPENAI_REALTIME_MODEL`
- [ ] 7.3 Probar el barge-in de extremo a extremo: el agente calla, el cliente vacía la cola, descarta los frames hasta el siguiente `audio.start` y el texto queda truncado
