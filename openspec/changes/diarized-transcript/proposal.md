## Why

La transcripción diarizada pesa 15 % en la evaluación en vivo. `realtime-voice` ya entrega los eventos `transcript.partial` y `transcript.final` con `speaker`, pero deja explícitamente a este change las reglas que dan sentido a esa etiqueta: cómo se numeran los hablantes, cómo se evita que parpadeen, qué hacer con el eco del agente y cómo se mide que la diarización funciona.

## What Changes

- Reglas de etiquetado de la transcripción del usuario que llega de Deepgram (`nova-3`, español, `diarize=true`): ids de Deepgram traducidos a `speaker_1`, `speaker_2`... por orden de primera aparición y estables durante toda la sesión; el agente siempre es `agent`.
- Estabilización: el hablante de las parciales es provisional, el definitivo se fija en `transcript.final` y un cambio de hablante exige una duración mínima de habla.
- Anti-eco: los segmentos de Deepgram que coinciden en tiempo y en texto con lo que el agente está diciendo no se etiquetan como humanos.
- Marcas de tiempo `ts` y `ts_end` coherentes con el inicio de la sesión, puntuación y formato inteligente, resultados parciales y detección del fin de enunciado.
- Vocabulario del dominio (IPS, REPS, departamentos y grupos de capacidad) enviado a Deepgram para mejorar la precisión.
- Verificación con un audio corto de dos voces y metas medibles, con un informe de resultados.

## Capabilities

### New Capabilities
- `speaker-labeling`: etiquetado, estabilización, anti-eco, marcas de tiempo, formato y vocabulario de la transcripción del usuario, y su verificación.

### Modified Capabilities

(ninguna)

## Impact

- Backend: el módulo de Deepgram y la traducción de sus resultados a eventos del contrato (`app/voice/deepgram.py`, `app/voice/speakers.py`), que hoy implementan solo el mapeo mínimo por orden de aparición.
- Contrato: se reutiliza sin cambios el de `realtime-voice` (`ws-event-contract`): `transcript.partial`, `transcript.final`, `speaker`, `ts`, `ts_end`, `source` y `degraded`. La degradación a `speaker: "user"` cuando falla Deepgram sigue definida allí.
- Datos: la lista de vocabulario se toma de los valores del dataset que ya carga `data-ingestion`.
- Pruebas: un audio de dos voces en `backend/tests/audio/` y un informe de verificación.
- Sin variables de entorno nuevas obligatorias; los umbrales (duración mínima, similitud del anti-eco) son configurables con valores por defecto.
