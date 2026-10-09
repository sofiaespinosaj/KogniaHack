## Context

`realtime-voice` bifurca el audio del micrófono (PCM16 24 kHz) a Deepgram streaming en una tarea independiente y emite `transcript.partial` y `transcript.final` según `ws-event-contract`. La implementación actual traduce los ids de Deepgram por orden de aparición y separa en enunciados las rachas de palabras de un mismo hablante, sin estabilización, sin anti-eco y sin vocabulario. El agente habla por los altavoces del navegador; el cliente usa la cancelación de eco del navegador, pero en salas con altavoces el audio del agente puede volver por el micrófono y llegar a Deepgram como si fuera un humano.

## Goals / Non-Goals

**Goals:**
- Etiquetas que no cambian una vez fijadas y que no parpadean en la UI.
- Ningún enunciado del propio agente etiquetado como humano.
- Metas medibles y reproducibles con un audio de prueba versionado.

**Non-Goals:**
- Redefinir el contrato de eventos, la degradación o la bifurcación del audio (`realtime-voice`).
- Identificar personas por nombre o reconocer voces entre sesiones.
- Diarizar la voz del agente: su texto viene de la transcripción de salida de OpenAI.

## Decisions

1. **Etiquetas por orden de primera aparición, con ámbito de sesión.** Cada id de Deepgram recibe `speaker_N` la primera vez que aparece en un resultado final y lo conserva hasta el fin de la sesión; los ids de Deepgram nunca se exponen. Alternativa: exponer el id de Deepgram; descartada porque empieza en 0, puede saltar números y no es estable entre reconexiones del stream.
2. **Las parciales no crean hablantes.** Una parcial usa el hablante mayoritario por duración entre los ya conocidos; si el id es nuevo, conserva la etiqueta del enunciado en curso hasta el final. Así un hablante nuevo aparece por primera vez en un `transcript.final`. Alternativa: etiquetar las parciales con lo que diga Deepgram; descartada por el parpadeo visible.
3. **Duración mínima para reasignar.** Dentro de un resultado final, una racha de otro hablante más corta que `SPEAKER_MIN_RUN_MS` (inicial 500 ms, TBD calibrar) se une al hablante vecino en vez de abrir un enunciado nuevo. Evita enunciados de una palabra y hablantes fantasma por errores de Deepgram en los cambios de turno.
4. **Fin de enunciado.** El `transcript.final` se emite cuando Deepgram marca `is_final`; los resultados con `speech_final` o un evento `UtteranceEnd` cierran el enunciado. Parámetros: `interim_results=true`, `endpointing` de 300 ms (TBD calibrar) y `utterance_end_ms` de 1.000 ms (TBD).
5. **Anti-eco por tiempo y texto.** Un segmento se descarta como eco si se solapa en el tiempo con audio del agente enviado al cliente (más un margen de 300 ms, TBD) y su texto se parece al texto del agente de ese intervalo (similitud de tokens normalizados mayor o igual a 0,6, TBD). Solo con ambas condiciones: si el usuario interrumpe al agente con otras palabras, su enunciado se conserva. Alternativa: descartar todo lo que se solape en tiempo; descartada porque borraría los barge-in reales.
6. **Marcas de tiempo.** Deepgram mide desde el primer audio de cada conexión; el servidor suma el desfase entre el inicio de la sesión y ese primer frame. Tras reconectar con Deepgram el desfase se recalcula. `ts` es el inicio de la primera palabra y `ts_end` el final de la última.
7. **Formato.** `smart_format=true` y `punctuate=true` en español; los números se dejan como los formatee Deepgram (dígitos).
8. **Vocabulario.** Se envía a Deepgram una lista de términos clave (`keyterm`, compatible con `nova-3`): una lista fija (IPS, REPS, ESE, sedes, camas, consultorios, ambulancias, camillas, salas, unidad móvil, sillas, nivel de atención) más los departamentos y distritos del dataset tomados al arrancar. Tope de términos TBD según el límite vigente de Deepgram.
9. **Verificación con audio versionado.** Un audio corto (unos 60 s, TBD) con dos voces distintas que alternan, con su transcripción y hablante esperados por enunciado, más las preguntas de oro de `grounded-agent`. Un script produce un informe con el porcentaje de enunciados con hablante correcto y el error de transcripción (WER) por pregunta.

## Risks / Trade-offs

- [Deepgram confunde voces parecidas] → Metas medidas con voces claramente distintas; se documenta la limitación.
- [El anti-eco descarta un enunciado humano que repite al agente] → Requiere coincidencia de tiempo y texto; los descartes se registran (sin texto) para calibrar.
- [La duración mínima retrasa la aparición de un hablante real con frases muy cortas] → Umbral configurable; las frases cortas siguen apareciendo, solo con la etiqueta vecina.
- [La lista de vocabulario supera el límite de Deepgram] → Prioridad: términos fijos, luego departamentos; tope configurable.
- [Las parciales muestran temporalmente la etiqueta anterior] → Aceptado: el final corrige; nunca se muestra un hablante que luego desaparezca.

## Open Questions

- Valores finales de `SPEAKER_MIN_RUN_MS`, `endpointing`, `utterance_end_ms` y del margen y umbral del anti-eco (TBD, calibrar con el audio de prueba).
- Meta exacta de WER en las preguntas de oro (TBD; propuesta inicial 15 % o menos).
- Origen del audio de dos voces: grabado por el equipo o sintético con dos voces TTS distintas (TBD).
- Límite vigente de términos de `keyterm` en Deepgram (TBD, verificar en la documentación).
