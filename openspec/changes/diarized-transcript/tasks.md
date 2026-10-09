## 1. Etiquetas estables y estabilización

- [ ] 1.1 Fijar las etiquetas `speaker_N` en el primer resultado final de cada id de Deepgram y conservarlas toda la sesión; verificar con pruebas unitarias de orden de aparición y estabilidad
- [ ] 1.2 Hacer que las parciales usen solo etiquetas ya existentes (la del enunciado en curso si el id es nuevo); verificar con una prueba de parciales con ids alternos
- [ ] 1.3 Unir al hablante vecino las rachas más cortas que `SPEAKER_MIN_RUN_MS` (inicial 500 ms, TBD) dentro de un final; verificar con una prueba de racha corta y documentar la variable en `backend/README.md`

## 2. Anti-eco

- [ ] 2.1 Registrar los intervalos de audio del agente enviados al cliente (por turno) y su texto; verificar con una prueba unitaria
- [ ] 2.2 Descartar los segmentos que coinciden en tiempo (con margen, TBD) y texto (similitud ≥ 0,6, TBD) con el agente, sin consumir etiqueta y con registro sin texto; verificar con pruebas de eco y de interrupción real usando el Deepgram simulado

## 3. Marcas de tiempo, formato y fin de enunciado

- [ ] 3.1 Calcular `ts` y `ts_end` desde el inicio de la sesión y recalcular el desfase al reconectar con Deepgram; verificar con una prueba de reconexión que los `ts` no vuelven a cero
- [ ] 3.2 Pedir `smart_format`, `punctuate`, `interim_results`, `endpointing` y `utterance_end_ms` (valores TBD) y cerrar el enunciado con `speech_final` o `UtteranceEnd`; verificar con el Deepgram simulado que hay parciales antes del final

## 4. Vocabulario del dominio

- [ ] 4.1 Construir la lista de términos (siglas, grupos de capacidad y departamentos del dataset) con prioridad y tope configurable, y enviarla como `keyterm`; verificar con una prueba que la URL de Deepgram incluye los términos y respeta el tope

## 5. Verificación

- [ ] 5.1 Versionar un audio corto de dos voces con su transcripción y hablante esperados por enunciado (origen TBD) en `backend/tests/audio/`
- [ ] 5.2 Escribir el script de verificación contra Deepgram real que calcule el porcentaje de hablante correcto y el WER de las preguntas de oro, falle por debajo del 90 % y guarde el informe; ejecutarlo y adjuntar el informe
