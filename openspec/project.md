# Agente Vocal Cognitivo

## Propósito

Agente conversacional por voz para el hackatón Kognia Labs (Reto 01). Indexa datos como su **única fuente de conocimiento**. Al iniciar explica de qué trata la fuente y qué se le puede preguntar; responde por voz con baja latencia; y muestra en pantalla la transcripción diarizada y el análisis de sentimiento y emociones en vivo.

## Fuentes de datos

1. **Obligatoria — API SODA3 de datos.gov.co**
   - Dataset `s2ru-bqt6`: «Relación de IPS públicas y privadas según el nivel de atención y capacidad instalada» (+41.000 filas).
   - Endpoint: `https://www.datos.gov.co/api/v3/views/s2ru-bqt6/query.json`
   - Requiere token de aplicación.
   - Máximo 1.000 filas por llamada: es necesario paginar o filtrar.
2. **Documento sorpresa** (PDF / DOCX / TXT / CSV) entregado por el jurado en vivo. Debe procesarse sin fallar.

## Stack técnico

- **Backend:** FastAPI (Python 3.11+, asyncio).
- **Frontend:** React + Vite + TypeScript.
- **Transporte:** un solo WebSocket por sesión.
- **Voz:** STT streaming con diarización (Deepgram); LLM rápido con tool calling; TTS streaming.
- **Datos tabulares:** DuckDB en memoria.
- **Documentos:** chunking + embeddings + BM25.
- **Despliegue:** frontend en Vercel; backend en un servicio con soporte de WebSockets (Render / Railway / Fly) con Docker.

## Restricciones

- La URL pública debe funcionar sin instalación local ni demo local. La evaluación dura 10 minutos y es en vivo.
- El agente responde SOLO con resultados de sus tools; si no hay evidencia, lo dice.
- Los secretos viven solo en el backend (variables de entorno).
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

1. Cargar el documento.
2. Brief con 3 a 5 preguntas sugeridas.
3. Tres preguntas por voz: resumen, detalle fino, fuera del documento.
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
- Proveedores concretos de LLM y TTS.
- Proveedor de embeddings y modelo de análisis de sentimiento/emociones.
- Plataforma final del backend (Render, Railway o Fly) y URLs públicas.
- Estructura de directorios del repositorio y convenciones de testing.
- Objetivo numérico de latencia.
