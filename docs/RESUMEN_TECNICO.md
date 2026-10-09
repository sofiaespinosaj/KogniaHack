# Ivy: resumen técnico

Agente de voz en español que responde preguntas sobre las IPS de Colombia (dataset `s2ru-bqt6` de datos.gov.co, unas 41.000 filas). Muestra en vivo la transcripción con hablantes, el sentimiento por frase y la evidencia de cada cifra.

## Cómo resolvimos el problema

- **Datos confiables y rápidos.** La API de datos.gov.co tardaba unos 127 s y daba timeout con consultas grandes. La descargamos paginada (páginas de 1.000 filas, 4 en paralelo, reintentos con backoff) y guardamos un **snapshot Parquet** de 2 MB. El backend arranca con el snapshot en unos 5 s y refresca en segundo plano desde la API.
- **Cero cifras inventadas.** El LLM no responde de memoria. Llama a **tools** que ejecutan SQL sobre DuckDB, y cada cifra se muestra en la UI con su evidencia (filtros, filas usadas, fecha de corte).
- **Baja latencia.** Voz por etapas en streaming: el agente empieza a hablar con la primera frase, sin esperar la respuesta completa. Las preguntas comunes ejecutan la tool antes de llamar al LLM.
- **Conversación natural.** El usuario puede interrumpir al agente (barge-in), el eco del altavoz se descarta y los números se leen como los diría una persona.

## Arquitectura

```
Navegador (React, Vercel) ──WebSocket único──► Backend FastAPI (Render, Docker)
                                                ├─ Deepgram nova-3: escucha, transcribe y diariza
                                                ├─ Groq gpt-oss-120b: razona y llama a las tools
                                                │     └─ Tools SQL ──► DuckDB en memoria (snapshot)
                                                ├─ Deepgram Aura-2: voz de respuesta
                                                └─ Groq gpt-oss-20b: sentimiento por frase (aparte)
```

- Las claves viven solo en el backend; el navegador solo conoce la URL del backend.
- Un contrato de eventos versionado (JSON Schema y tipos TypeScript generados) entre el front y el back.
- Alternativa lista con el mismo contrato: OpenAI Realtime voz a voz (`VOICE_PROVIDER=openai`).

## Stack

| Capa | Tecnología |
|---|---|
| Frontend | React 19, Vite, TypeScript, Tailwind |
| Backend | Python, FastAPI, WebSocket |
| Datos | DuckDB en memoria, Parquet, API SODA de datos.gov.co |
| Oído (STT y diarización) | Deepgram `nova-3`, español |
| Cerebro (LLM) | Groq `openai/gpt-oss-120b`; respaldo `openai/gpt-oss-20b` |
| Voz (TTS) | Deepgram Aura-2 `aura-2-celeste-es` |
| Sentimiento | Groq `openai/gpt-oss-20b` |
| Despliegue | Render (backend), Vercel (frontend) |
| Pruebas | pytest, e2e con Chromium y servicios simulados |
| Especificación | OpenSpec (un change por capacidad) |

## Preguntas técnicas probables

**¿Cómo evitan que el agente invente datos?**
Las cifras solo pueden salir de las tools, que consultan DuckDB con SQL. Las instrucciones lo prohíben, el historial no guarda resultados viejos de tools (se vuelve a consultar) y la UI muestra la evidencia de cada respuesta.

**¿Por qué DuckDB y no Postgres?**
Es una base analítica que corre dentro del proceso de Python, sin servidor aparte. Con 41.000 filas responde en milisegundos, lee Parquet directo y no agrega infraestructura ni costo.

**¿Qué pasa si la API de datos.gov.co se cae?**
Nada visible: el agente usa el snapshot y cita su fecha de corte (2022-11-05). El refresco solo reemplaza la tabla si la descarga completa pasa la validación (conteo e IDs únicos).

**¿Por qué el snapshot?**
Para que el arranque y la demo no dependan de una API lenta (unos 127 s) e inestable. Arranca en unos 5 s.

**¿Cómo logran baja latencia?**
Streaming en todas las etapas, TTS frase por frase, prefetch de la tool en preguntas comunes, historial corto (4 turnos) y respuestas cortas. La meta es el primer audio en 1,5 s o menos (p50) tras terminar de hablar, medido en el servidor.

**¿Cómo funciona la diarización?**
Deepgram con `diarize=true` etiqueta a cada hablante. Los IDs se mapean a `speaker_1`, `speaker_2`… en orden de aparición, estables durante la sesión; el agente siempre es `agent`.

**¿Cómo manejan las interrupciones?**
Si el usuario habla mientras el agente responde, se cancela la respuesta, el cliente vacía su cola de audio y en el historial queda solo lo que el usuario alcanzó a escuchar.

**¿Y el eco del altavoz?**
El navegador usa cancelación de eco, y el backend descarta transcripciones que coinciden con lo que el agente está diciendo, para que no interrumpan ni aparezcan como habla del usuario.

**¿Cómo manejan el contexto?**
Un historial por sesión en memoria con el prompt del sistema y los últimos 4 turnos. Los resultados de las tools viven solo dentro del turno.

**¿Qué pasa si Groq se queda sin cuota?**
Pasa al modelo de respaldo. Si ninguno responde y ya hay datos consultados, responde con esos datos; nunca se queda en silencio.

**¿Qué pasa si falla Deepgram?**
Como Deepgram es el oído, el agente no puede escuchar por voz. La sesión no se cae: la UI avisa que se puede escribir la pregunta (el chat de texto sigue funcionando) y se reintenta la conexión en segundo plano. Al volver, se informa a la UI.

**¿Cómo evitan preguntas fuera de tema?**
Un filtro previo al LLM detecta temas ajenos o intentos de sacar al agente de su papel y responde con una redirección fija, sin gastar cuota.

**¿Cómo protegen las claves y el endpoint público?**
Las claves solo están en el backend y nunca se registran (hay pruebas que lo verifican). El WebSocket valida el `Origin` y limita a 3 sesiones a la vez, 10 nuevas por IP por minuto y 15 minutos por sesión.

**¿Cómo lo probaron?**
Unos 260 tests con pytest sin claves (APIs simuladas), un e2e con Chromium y micrófono falso, evaluación por voz de las preguntas de oro midiendo latencia y una prueba de humo contra el despliegue.

**¿Cómo calculan el sentimiento?**
Un modelo de texto pequeño analiza cada frase final en segundo plano, sin bloquear la voz, y devuelve sentimiento, emoción y un puntaje de -1 a 1. Limitación: analiza el texto, no el tono de voz.

**¿Por qué Groq y no OpenAI Realtime?**
Groq da inferencia muy rápida y el pipeline por etapas permite usar Deepgram para la diarización con el mismo audio. OpenAI Realtime quedó implementado como alternativa con el mismo contrato.
