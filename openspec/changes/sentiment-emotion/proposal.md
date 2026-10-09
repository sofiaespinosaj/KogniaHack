## Why

El evento `sentiment` ya está definido en el contrato de `realtime-voice` (`ws-event-contract`), pero ese change deja aquí el análisis: qué modelo lo produce, qué valores puede tomar y cómo se garantiza que nunca frene la voz. El panel del jurado muestra sentimiento y emoción por enunciado, así que hace falta una definición cerrada, medible y que falle en silencio.

## What Changes

- Análisis asíncrono por cada `transcript.final` de un humano, fuera de la ruta de voz.
- Modelo de texto pequeño de OpenAI con salida JSON validada por esquema, configurable con `OPENAI_SENTIMENT_MODEL`.
- Contexto de los dos enunciados humanos anteriores de la sesión además del actual.
- Valores cerrados en español: `sentiment` en `positivo`, `neutro` o `negativo`; `emotion` en una lista cerrada (interés, curiosidad, confusión, frustración, sorpresa, enojo, alegría, neutralidad); `score` de -1 a 1.
- Enunciados muy cortos resueltos como neutros sin llamar al modelo.
- Tiempo máximo de 3 s y fallo silencioso; concurrencia limitada; meta de 2 s o menos (p50) entre `transcript.final` y `sentiment`.
- Limitación declarada: se analiza solo el texto, sin prosodia.
- Evaluación con unas 10 frases etiquetadas a mano.

## Capabilities

### New Capabilities
- `sentiment-analysis`: análisis de sentimiento y emoción de los enunciados humanos, sus valores permitidos, tiempos, concurrencia, fallos y evaluación.

### Modified Capabilities

(ninguna)

## Impact

- Backend: un módulo nuevo de análisis (p. ej. `app/sentiment/`) invocado tras cada `transcript.final` humano que emite el relé de voz; no toca la ruta de audio.
- Contrato: se reutiliza sin cambios el evento `sentiment` de `ws-event-contract` (`turn_id`, `utt_id`, `speaker`, `sentiment`, `emotion`, `score`) y su regla de orden (el `transcript.final` precede a su `sentiment`).
- Variables de entorno nuevas, solo en el backend: `OPENAI_SENTIMENT_MODEL` (y opcionales de tiempo máximo y concurrencia); usa la `OPENAI_API_KEY` existente.
- Frontend: el panel de Live Insights muestra los valores en español; el mock deja de usar `neutral` y pasa a `neutro`.
- Costo: una llamada a un modelo de texto pequeño por enunciado humano no trivial.
