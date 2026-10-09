## 1. Configuración y esquema

- [ ] 1.1 Añadir `OPENAI_SENTIMENT_MODEL` (por defecto TBD), tiempo máximo (3 s) y límites de concurrencia a la configuración y a `.env.example`, sin imprimir valores; verificar con pruebas de configuración
- [ ] 1.2 Definir el esquema JSON de salida (enums cerrados y `score` en [-1, 1]) y su validación local con la regla de coherencia del score; verificar con pruebas de valores válidos, inválidos e incoherentes

## 2. Análisis asíncrono

- [ ] 2.1 Implementar el cliente del modelo de texto con Structured Outputs, el contexto de los dos enunciados anteriores y el atajo de enunciados cortos; verificar con pruebas que usan un cliente simulado (sin red)
- [ ] 2.2 Lanzar el análisis tras cada `transcript.final` humano emitido por el relé, emitir `sentiment` con el contrato existente y registrar la latencia; verificar con `tests/test_relay.py` que el evento llega con el mismo `turn_id` y `utt_id` y que el agente no se analiza
- [ ] 2.3 Aplicar el tiempo máximo de 3 s, el fallo silencioso y la concurrencia limitada; verificar con pruebas de timeout, error, salida inválida y ráfaga, comprobando que no se emite `error` al cliente y que la voz no se retrasa

## 3. Frontend y documentación

- [ ] 3.1 Mostrar `sentiment`, `emotion` y `score` en Live Insights con la nota «basado en el texto» y cambiar el mock de `neutral` a `neutro`; verificar con `npm run build` y una captura
- [ ] 3.2 Documentar el análisis, sus valores y la limitación de solo texto en `backend/README.md`

## 4. Evaluación

- [ ] 4.1 Crear `backend/tests/sentiment/frases.json` con unas 10 frases en español etiquetadas a mano (sentimiento y emoción)
- [ ] 4.2 Escribir y ejecutar el script de evaluación con el modelo real; guardar el informe con aciertos por campo, tabla esperado frente a obtenido y latencia p50 frente a la meta de 2 s
