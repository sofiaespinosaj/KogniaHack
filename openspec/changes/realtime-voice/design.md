## Context

El agente corre sobre OpenAI Realtime (voz a voz). OpenAI no entrega etiquetas de hablante ni marcas de tiempo por palabra, por lo que la transcripción diarizada del usuario viene de Deepgram, alimentada con el mismo audio del micrófono. Las tools de `grounded-agent` deben ejecutarse en el servidor contra DuckDB, y las claves nunca pueden llegar al navegador. La evaluación es en vivo (10 minutos), con peso de 20 % en voz y latencia y 15 % en transcripción diarizada. `data-ingestion` ya define la configuración validada al arrancar y el snapshot-first; `grounded-agent` define las tools, el grounding y el brief.

## Goals / Non-Goals

**Goals:**
- Primer audio en 1,5 s o menos (p50) tras terminar el turno del usuario.
- Barge-in fiable: el agente calla rápido y no queda audio viejo en el cliente.
- Un único contrato de eventos, versionado y con ejemplos, reutilizado por los demás changes.
- Degradación elegante: la sesión no se rompe si falla Deepgram u OpenAI.

**Non-Goals:**
- Reglas de diarización (cómo se asignan y estabilizan las etiquetas de hablante): `diarized-transcript`.
- Modelo, prompt y esquema interno del análisis de sentimiento: `sentiment-emotion`.
- Interfaz y estados visuales: `frontend-experience`.
- Dockerfile, CORS, WSS y `/health` completo: `deployment-readme`.
- Autenticación de usuarios y reanudación de sesiones (fuera de v1).

## Decisions

1. **Relé en FastAPI en vez de conexión directa del navegador a OpenAI.** Un relé permite ejecutar las tools en el servidor, mantener las claves fuera del navegador y bifurcar el audio a Deepgram. Alternativa: el navegador se conecta a OpenAI con un token efímero; descartada porque no permite tools del lado del servidor sobre DuckDB ni la bifurcación a Deepgram. Costo: un salto adicional de red, que se mide dentro de la meta de latencia.
2. **Un solo WebSocket por sesión, con mensajes binarios y JSON.** Los frames binarios son siempre audio (cliente a servidor: micrófono; servidor a cliente: respuesta del agente), y los de texto son siempre JSON con campo `type`. La dirección elimina la ambigüedad. Alternativa: dos sockets (audio y eventos); descartada por la restricción de un socket por sesión y por la complicación de sincronizar.
3. **Formato de audio: PCM16 mono a 24 kHz en ambos sentidos.** Es el formato nativo de OpenAI Realtime y se reenvía sin transcodificar a Deepgram (`encoding=linear16`, `sample_rate=24000`), de modo que la bifurcación no añade latencia a la ruta crítica. El audio llega a Deepgram por una tarea independiente: un fallo o retraso allí no bloquea a OpenAI.
4. **Definición de la latencia.** `first_audio_ms` es el tiempo entre el evento de fin de habla del usuario detectado por el VAD del servidor de OpenAI y el envío al cliente del primer frame de audio de respuesta. Se mide y se publica en el servidor. La reproducción en el navegador añade un retardo adicional que no se incluye; el cliente puede reportarlo, pero la meta aplica a la medición del servidor.
5. **Barge-in con truncado.** Al detectar voz del usuario con una respuesta en curso: (a) el servidor envía `audio.clear` al cliente y cancela la respuesta en OpenAI; (b) trunca el elemento de la conversación al punto realmente reproducido, para que el modelo no crea que dijo algo que el usuario no escuchó. El servidor necesita saber cuánto audio se reprodujo, por eso el cliente envía `playback.position` periódicamente. Alternativa: estimar por bytes enviados; descartada porque sobreestima lo escuchado por el buffer del navegador.
6. **Modelo de identificadores.** `turn_id` agrupa un intercambio (lo que dice el usuario y la respuesta del agente) y `utt_id` identifica un enunciado individual dentro de un turno, porque en un turno pueden hablar varios humanos. Las transcripciones parciales y la final de un enunciado comparten `utt_id`; la final reemplaza a las parciales. El sentimiento se asocia por `turn_id` y `utt_id`. El brief usa el turno `t-0000`.
7. **Fuente de verdad del texto visible.** Para el usuario manda Deepgram (única fuente con etiquetas de hablante); para el agente manda la transcripción de salida de OpenAI. Si Deepgram falla, el texto del usuario pasa a la transcripción de entrada de OpenAI, sin etiquetas, marcada como degradada. Esto exige habilitar la transcripción de entrada en la sesión de OpenAI; queda siempre activa con el modelo más barato que recomiende la documentación vigente (configurable con `OPENAI_INPUT_TRANSCRIPTION_MODEL`, a verificar en el spike); así el respaldo no añade retraso al fallar Deepgram.
8. **Sin reanudación en v1.** Una reconexión crea una sesión nueva; el cliente conserva su transcripción local y puede pedir `brief: "skip"` para no repetir el brief hablado. Alternativa: tokens de reanudación con buffer de eventos; descartada por complejidad frente al valor en una evaluación de 10 minutos.
9. **Orden por `seq`.** Cada mensaje servidor a cliente lleva un número de secuencia creciente por sesión para detectar pérdidas y reordenar eventos de fuentes distintas (Deepgram, OpenAI, sentimiento asíncrono).
10. **Estado de la voz y arranque.** `VOICE_ENABLED` activa el módulo; con `true` exige `OPENAI_API_KEY` y `DEEPGRAM_API_KEY` siguiendo la configuración validada de `data-ingestion`. Con `false` el backend arranca y sirve datos y `GET /api/brief`, y `/health` informa que la voz está apagada. El despliegue debe fijar `true`.
11. **Protección del WebSocket público.** El endpoint es público, así que valida `Origin` contra `CORS_ORIGINS`, limita a 3 las sesiones simultáneas y a 10 las nuevas por IP y minuto, y fija 15 minutos de duración máxima con aviso a los 13. Todos los límites cierran con `session_limit` (y `detail.reason`) y se registran sin secretos. Una sesión de voz por conexión, con liberación de las conexiones a OpenAI y Deepgram. Alternativa: sin límites; descartada por el riesgo de consumo de la clave de OpenAI y de saturación durante la demo.
12. **Elección del modelo por spike.** Antes de construir el relé se mide `first_audio_ms` con `gpt-realtime-mini` y con el modelo completo mediante un script mínimo (30 minutos). El valor de `OPENAI_REALTIME_MODEL` se decide con esos datos y se reconsidera si las preguntas de oro fallan la meta.
13. **VAD.** Se prefiere `semantic_vad` si el modelo lo soporta, porque evita cortar pausas naturales; si no, `server_vad` con umbral 0,5, relleno previo de 300 ms y silencio de 500 ms. Con `server_vad` el silencio configurado se publica como `vad_silence_ms` para reportar la latencia percibida (`vad_silence_ms` + `first_audio_ms`); con `semantic_vad` el campo se omite.
14. **Contrato como artefacto.** Los modelos de mensajes del backend son la fuente; de ellos se exporta `backend/contract/ws-events.schema.json` y se generan los tipos TypeScript del frontend. Una prueba valida que los ejemplos del README cumplen el esquema y que el esquema publicado está al día. Alternativa: tipos escritos a mano en cada lado; descartada por el riesgo de divergencia.

15. **Proveedor alternativo por etapas (`VOICE_PROVIDER=groq`, añadido tras agotarse el crédito de OpenAI).** Deepgram streaming hace de oído (transcripción diarizada y fin de turno por `speech_final` / `UtteranceEnd`), Groq hace de cerebro (Chat Completions con streaming y las mismas tools de `agent-tools`) y Deepgram Aura-2 en español hace de voz, frase a frase. El contrato de eventos no cambia. Diferencias con OpenAI Realtime: `vad_silence_ms` es el `endpointing` de Deepgram; `first_audio_ms` se mide desde `speech_final`; sin Deepgram no hay entrada por voz (solo texto), porque no hay transcripción de respaldo. Pendiente: formalizarlo en los requisitos de `voice-session`, hoy redactados para OpenAI Realtime.

## Risks / Trade-offs

- [Latencia por el salto extra del relé] → La medición del servidor la incluye; el relé reenvía audio sin transcodificar y sin esperar a Deepgram.
- [El VAD de servidor corta o no corta en español] → Parámetros configurables por entorno, `semantic_vad` preferido y calibración con las preguntas de oro.
- [Eco del altavoz activa el barge-in] → El cliente usa cancelación de eco del navegador; el servidor ignora detecciones durante una ventana corta tras iniciar el audio (valor TBD).
- [Deepgram y OpenAI discrepan en el texto del usuario] → Se muestra solo la fuente de verdad; OpenAI sirve de respaldo, nunca se mezclan en la misma línea.
- [Etiquetas de hablante inestables al inicio] → Responsabilidad de `diarized-transcript`; el contrato permite re-emitir el `speaker` en el evento final.
- [Costo de la transcripción de entrada de OpenAI siempre activa] → Modelo más barato recomendado por la documentación; se acepta el costo a cambio de un respaldo sin retraso.
- [IP real tras el proxy del despliegue] → El límite por IP usa la IP del cliente que informe el proxy de confianza del servicio de despliegue (se verifica en `deployment-readme`).
- [Cold start del backend durante la demo] → Se aborda en `deployment-readme` (sin cold start); `/health` y la carga snapshot-first permiten calentar el servicio.

## Open Questions

- Confirmar de oído en español la voz provisional `marin` de `REALTIME_VOICE`.
- Modelo de transcripción de entrada de OpenAI exacto: verificar en la documentación vigente cuál es el más barato recomendado (spike).
- Si el modelo elegido soporta `semantic_vad`; si no, se usa `server_vad` con los valores acordados.
- Verificar la diarización de `nova-3` con un audio de dos voces.
- Ventana de supresión de detecciones de voz tras iniciar el audio del agente para evitar eco (TBD, a calibrar).
- Generador de tipos TypeScript a usar y ubicación exacta en el frontend (TBD).

Decididos: duración máxima de sesión 15 minutos (aviso a los 13); frames de audio de 40 ms; unas 20 corridas en la prueba de latencia con p50 de 1.500 ms como criterio de falla y p95 de 2.500 ms como meta orientativa; Deepgram `nova-3` con `language=es`; puntaje de sentimiento de -1 a 1.
