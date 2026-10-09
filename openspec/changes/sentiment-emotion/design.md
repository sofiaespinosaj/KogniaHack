## Context

El relé de `realtime-voice` emite `transcript.final` para el usuario desde Deepgram (con `speaker_N`), desde la transcripción de entrada de OpenAI en modo degradado (`speaker: "user"`) o desde `text.message` (`source: "text"`). El contrato ya fija el evento `sentiment` y permite que llegue después de eventos de turnos posteriores; el cliente lo asocia por `turn_id` y `utt_id`. El ejemplo del contrato usa `"sentiment": "neutral"` como ilustración; los valores permitidos se fijan aquí.

## Goals / Non-Goals

**Goals:**
- Cero impacto en la latencia de la voz y en la UI, aunque el análisis falle o tarde.
- Valores cerrados y validados: la UI nunca recibe un valor fuera de la lista.
- Una medición de calidad pequeña pero reproducible.

**Non-Goals:**
- Analizar la prosodia, el tono o el audio (solo texto).
- Analizar el texto del agente.
- Redefinir el evento `sentiment` o sus reglas de orden (`ws-event-contract`).
- Sentimiento agregado por hablante o por sesión (posible mejora futura).

## Decisions

1. **Tarea asíncrona por enunciado.** Cada `transcript.final` humano encola un análisis en una tarea independiente del relé; la emisión de `sentiment` usa la misma conexión y numeración `seq`. Alternativa: pedir el sentimiento a OpenAI Realtime dentro de la respuesta; descartada porque añade tokens y latencia a la ruta de voz.
2. **Modelo de texto pequeño con Structured Outputs.** Llamada a la API de OpenAI con `response_format` de tipo `json_schema` estricto (enums cerrados y `score` numérico) y validación local del resultado contra el mismo esquema. Modelo por defecto TBD (candidato: el modelo de texto más barato y rápido vigente, verificado en la documentación); configurable con `OPENAI_SENTIMENT_MODEL`. Alternativa: clasificador local; descartada por el tiempo de la hackatón y la calidad en español.
3. **Contexto corto.** Se envían los dos enunciados humanos anteriores de la sesión (con su `speaker`) además del actual, marcando cuál se clasifica. Ayuda con respuestas como «sí, esa» sin inflar el prompt. Alternativa: tres anteriores; se deja configurable (TBD, inicial 2).
4. **Valores y coherencia del score.** `sentiment` en `positivo`, `neutro`, `negativo`; `emotion` en `interés`, `curiosidad`, `confusión`, `frustración`, `sorpresa`, `enojo`, `alegría`, `neutralidad`; `score` en [-1, 1] con signo coherente: positivo > 0, negativo < 0 y neutro dentro de [-0,3; 0,3] (umbral TBD). Si el modelo devuelve un score incoherente, se recorta al rango del sentimiento.
5. **Atajo para enunciados muy cortos.** Con menos de 3 palabras (TBD) o solo muletillas («eh», «ajá», «ok»), se emite `neutro` / `neutralidad` / 0 sin llamar al modelo.
6. **Tiempo máximo y fallo silencioso.** 3 s por análisis; ante timeout, error de red, respuesta inválida o falta de cuota no se emite `sentiment` ni `error` al cliente: solo se registra el tipo de fallo (sin texto ni claves). La UI simplemente no muestra emoción para ese enunciado.
7. **Concurrencia limitada.** Como máximo 2 análisis en curso por sesión y 6 en el proceso (TBD). Si hay más, se descarta el análisis más antiguo pendiente (el más nuevo es el más útil en vivo).
8. **Meta de latencia.** p50 de 2 s o menos entre la emisión de `transcript.final` y la de `sentiment`, medida en el servidor y registrada por enunciado.
9. **Evaluación.** Unas 10 frases en español etiquetadas a mano (sentimiento y emoción) en `backend/tests/sentiment/frases.json`, con un script que llama al modelo real y reporta aciertos y latencia.

## Risks / Trade-offs

- [Solo texto: la ironía o el tono enojado con palabras neutras no se detectan] → Limitación declarada en el README y en la UI («basado en el texto»).
- [La API de OpenAI tarda más de 3 s en hora pico] → Fallo silencioso; la meta se mide y se reporta.
- [Costo por enunciado] → Atajo para enunciados cortos y modelo pequeño.
- [Emociones poco frecuentes mal clasificadas] → Lista cerrada pequeña; la evaluación muestra los errores.
- [El ejemplo del contrato usa `neutral`] → No se redefine el contrato; los valores válidos son los de esta capability y el mock del frontend se alinea.

## Open Questions

- Modelo por defecto de `OPENAI_SENTIMENT_MODEL` (TBD, verificar el más barato y rápido vigente con Structured Outputs).
- Umbral de palabras del atajo y rango del score para `neutro` (TBD, calibrar con la evaluación).
- Límites exactos de concurrencia por sesión y por proceso (TBD).
- Meta de aciertos de la evaluación (TBD; propuesta: 8 de 10 en `sentiment` y 6 de 10 en `emotion`).
