## Why

La evaluación pondera la voz y la latencia en 20 % y la transcripción diarizada en 15 %, y se hace en vivo durante 10 minutos. Hace falta definir cómo el navegador, FastAPI, OpenAI Realtime y Deepgram trabajan juntos con baja latencia, cómo se interrumpe al agente y cómo se degrada con elegancia, además de un único contrato de eventos del WebSocket que el frontend y los demás changes puedan usar sin ambigüedad.

## What Changes

- Un solo WebSocket por sesión entre el navegador y FastAPI. FastAPI actúa de relé hacia OpenAI Realtime (WebSocket servidor a servidor), ejecuta del lado del servidor las function tools de `grounded-agent` y bifurca el mismo audio del micrófono (PCM16 24 kHz) hacia Deepgram streaming con `diarize=true` y español.
- Meta de latencia: primer audio de respuesta en 1,5 s o menos (p50) tras terminar el turno del usuario, medida en el servidor y enviada a la UI.
- Barge-in: al hablar el usuario mientras el agente responde, se cancela la respuesta, se trunca lo no reproducido y el cliente vacía su cola de audio.
- VAD configurable y ajustado a español; el brief de `grounded-agent` se emite como primera respuesta de la sesión.
- Degradación controlada ante fallos de Deepgram o de OpenAI; límite de duración y limpieza de recursos por sesión.
- Contrato de eventos del WebSocket versionado, con ejemplos JSON, definido una sola vez aquí; el brief también se expone por `GET /api/brief`.
- Configuración de voz por entorno (`VOICE_ENABLED`, `REALTIME_VOICE`, claves) y aviso en `/health` cuando la voz está apagada.
- Protección del WebSocket público: validación de `Origin`, 3 sesiones simultáneas, límite de sesiones nuevas por IP y 15 minutos de duración máxima.
- Contrato publicado como JSON Schema (`backend/contract/ws-events.schema.json`) y tipos TypeScript generados para el frontend.
- Spike inicial de 30 minutos para decidir el modelo Realtime midiendo `first_audio_ms`.
- Prueba de las preguntas de oro por voz (o con audio sintético) con registro de latencias.

## Capabilities

### New Capabilities
- `voice-session`: ciclo de vida de la sesión de voz, relé a OpenAI Realtime, bifurcación a Deepgram, latencia, barge-in, VAD, degradación y límites.
- `ws-event-contract`: contrato versionado de mensajes del WebSocket (cliente a servidor y servidor a cliente), orden, reconexión y fuente de verdad del texto visible.

### Modified Capabilities

(ninguna)

## Impact

- Código nuevo en el backend FastAPI (`voice/relay`, `voice/deepgram`, `ws/protocol`, `api/brief`); el frontend consume el contrato en `frontend-experience`.
- Dependencias nuevas: cliente WebSocket para OpenAI Realtime y para Deepgram.
- Variables de entorno nuevas, solo en el backend: `VOICE_ENABLED`, `OPENAI_API_KEY`, `OPENAI_REALTIME_MODEL`, `REALTIME_VOICE`, `DEEPGRAM_API_KEY`, parámetros de VAD y límite de duración de sesión.
- Reutiliza sin redefinir: tools y reglas de `grounded-agent` (`agent-tools`, `agent-grounding`, `session-brief`) y los datos y la configuración de `data-ingestion`.
- Los changes `diarized-transcript`, `sentiment-emotion` y `frontend-experience` referencian este contrato en lugar de redefinirlo.
