# Agente Vocal Cognitivo

## Propósito

Agente conversacional por voz para el hackatón Kognia Labs (Reto 01). Indexa datos como su **única fuente de conocimiento**. Al iniciar explica de qué trata la fuente y qué se le puede preguntar; responde por voz con baja latencia; y muestra en pantalla la transcripción diarizada y el análisis de sentimiento y emociones en vivo.

## Fuentes de datos

Única fuente: **API SODA3 de datos.gov.co**. No hay documentos ni subida de archivos.

- Dataset `s2ru-bqt6`: «Relación de IPS públicas y privadas según el nivel de atención y capacidad instalada» (+41.000 filas).
- Endpoint: `https://www.datos.gov.co/api/v3/views/s2ru-bqt6/query.json`
- Requiere token de aplicación.
- Máximo 1.000 filas por llamada: es necesario paginar o filtrar.

## Stack técnico

- **Backend:** FastAPI (Python 3.11+, asyncio).
- **Frontend:** React + Vite + TypeScript.
- **Transporte:** un solo WebSocket por sesión.
- **Voz:** Voz a voz con OpenAI Realtime (modelo en `OPENAI_REALTIME_MODEL`, provisional `gpt-realtime-mini`, a confirmar con el spike de latencia), con FastAPI como relé por WebSocket; las tools se ejecutan en el servidor. Transcripción diarizada con Deepgram streaming (`diarize=true`, español) alimentada con el mismo audio del micrófono, porque OpenAI no entrega etiquetas de hablante. Los turnos del agente salen de la transcripción de salida de OpenAI. Sentimiento y emociones con un modelo de texto pequeño de OpenAI sobre cada enunciado final, fuera de la ruta de voz.
- **Datos tabulares:** DuckDB en memoria.
- **Despliegue:** frontend en Vercel; backend en un servicio con soporte de WebSockets (Render / Railway / Fly) con Docker.

## Restricciones

- La URL pública debe funcionar sin instalación local ni demo local. La evaluación dura 10 minutos y es en vivo.
- El agente responde SOLO con resultados de sus tools; si no hay evidencia, lo dice.
- Los secretos viven solo en el backend (variables de entorno).
- Claves necesarias solo en el backend: `OPENAI_API_KEY` y `DEEPGRAM_API_KEY` (más `SODA_APP_TOKEN`, opcional si hay snapshot).
- El README debe declarar qué se generó con IA.

## Criterios de éxito (peso)

| Criterio | Peso |
|---|---|
| Voz y latencia | 20% |
| Transcripción diarizada | 15% |
| Despliegue y entregable | 10% |
| UX / diseño / demo | 25% |
| Otros criterios | TBD |

## Guion de prueba (evaluación en vivo)

1. Conectar la fuente (el dataset) y presentar el brief.
2. Brief con 3 a 5 preguntas sugeridas.
3. Tres preguntas por voz: resumen, detalle fino, fuera de la fuente.
4. Revisión de la transcripción diarizada y el panel de sentimiento.
5. Preguntas de arquitectura.

## Convenciones

- Nombres de capabilities en `kebab-case`.
- Requisitos redactados con "SHALL".
- Cada requisito tiene al menos un escenario `WHEN/THEN`.
- Idioma de specs: español.
- Idioma de código e identificadores: inglés.

## Pendientes (TBD)

- Pesos de los criterios de éxito restantes (los dados suman 70%).
- Modelo de texto para sentimiento/emociones (OpenAI, a definir).
- Plataforma final del backend (Render, Railway o Fly) y URLs públicas.
- Estructura de directorios del repositorio y convenciones de testing.
- Latencia: primer audio de respuesta en 1,5 s o menos (p50); se valida en `realtime-voice`.
