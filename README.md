# Lumi · agente de voz sobre las IPS de Colombia

Lumi es una asistente de voz conversacional (Kognia Labs, Reto 01) que responde **solo** con datos del dataset
abierto `s2ru-bqt6` de datos.gov.co: IPS públicas y privadas de Colombia,
su nivel de atención, su capacidad instalada y el contacto de cada sede (41.427 filas, corte al 5 de noviembre de
2022). Al iniciar se presenta y explica qué se le puede preguntar; responde por voz con baja latencia y muestra en
pantalla la transcripción con hablantes y la evidencia de cada respuesta.

**URLs públicas:** frontend `https://<proyecto>.vercel.app` · backend `https://<servicio>.onrender.com` (TBD al
desplegar; ver [docs/DEPLOY.md](docs/DEPLOY.md)).

## Stack

| Capa | Tecnología |
|---|---|
| Frontend | React 19 + TypeScript + Vite + Tailwind 4, en Vercel |
| Backend | FastAPI (Python 3.12, asyncio), en Render con Docker |
| Datos | DuckDB en memoria, cargado desde un snapshot Parquet versionado (refresco opcional desde SODA3) |
| Oído | Deepgram streaming `nova-3` en español con diarización |
| Cerebro | Groq (`openai/gpt-oss-120b`) con *function calling*; alternativa: OpenAI Realtime |
| Voz | Deepgram Aura-2 en español (`aura-2-celeste-es`); alternativa: OpenAI Realtime |

## Arquitectura

```
Navegador (micrófono PCM16 24 kHz) ──WSS /ws──► FastAPI ──► Deepgram STT (texto + hablantes + fin de turno)
      ▲            un solo WebSocket                 │
      │  audio de Lumi + eventos JSON                ├──► Groq LLM ──tools──► DuckDB (snapshot del dataset)
      └──────────────────────────────────────────────┤
                                                     └──► Deepgram Aura-2 (voz, frase a frase)
```

- Un único WebSocket por sesión: frames binarios = audio en ambos sentidos; frames de texto = eventos JSON del
  contrato versionado (`backend/README.md`, esquema en `backend/contract/`).
- Las herramientas (contar IPS y sedes, sumar capacidad, rankings, listar sedes de un lugar, buscar por nombre)
  se ejecutan en el servidor; las claves nunca llegan al navegador.

## Decisiones técnicas

- **Relé en el servidor** en vez de conectar el navegador a los servicios de IA: permite ejecutar las tools sobre
  DuckDB, bifurcar el audio a Deepgram y mantener las claves fuera del navegador.
- **Respuestas solo con evidencia**: el LLM no tiene cifras en su prompt; todo número, nombre o dirección sale de
  una tool, y si no hay dato lo dice. Excepción por seguridad: ante una emergencia recomienda la línea 123.
- **Voz por etapas con Groq** (Deepgram → Groq → Aura-2): Lumi empieza a hablar con la primera frase mientras el
  resto se genera, sintetiza por adelantado las frases siguientes y dice «déjame revisar» mientras consulta.
- **Interrupciones**: si la persona habla, Lumi calla al instante, incluso si su respuesta ya se generó y sigue
  sonando; el modelo solo recuerda lo que la persona alcanzó a oír. Un filtro evita que el eco de su propia voz
  la interrumpa.
- **Transcripción por enunciados completos** con hablantes estables (`speaker_1`, `speaker_2`…).
- **Snapshot primero**: el backend arranca con el Parquet incluido en la imagen, sin depender de la API.
- **Contrato como artefacto**: el esquema JSON y los tipos TypeScript se generan desde los modelos del backend y
  una prueba de compilación avisa si el frontend se aparta.
- **Especificación con OpenSpec** (`openspec/changes/`): cada capacidad tiene propuesta, diseño, requisitos y tareas.

## Ejecutar en local

```bash
# backend (copia backend/.env.example a backend/.env y pon GROQ_API_KEY y DEEPGRAM_API_KEY)
cd backend && uv sync && uv run uvicorn app.main:app --port 8000
# frontend (otra terminal)
cd frontend && npm ci && npm run dev      # http://localhost:5173  ·  sin backend: http://localhost:5173/?mock
```

## Pruebas

```bash
cd backend && uv run pytest                 # contrato, tools, agente, relé y voz con servicios simulados
cd frontend && npm run build && npm run lint
scripts/e2e_local.sh                        # navegador con micrófono falso → front → backend → simulados
cd backend && uv run python -m scripts.smoke https://<backend>   # prueba de humo del despliegue
```

## Limitaciones conocidas

- Los datos son una foto con corte al 5 de noviembre de 2022: capacidad instalada, no disponibilidad ni servicios
  vigentes (por ejemplo, no confirman que una sede atienda urgencias hoy).
- El nivel de atención casi solo está registrado para IPS públicas.
- El sentimiento y la emoción, cuando se activen, se infieren solo del texto (sin tono de voz).
- La diarización depende de Deepgram; si Deepgram no está disponible no hay entrada por voz (se puede escribir).
- El plan gratuito de Groq limita las peticiones por minuto.

## Uso de inteligencia artificial

Declaración del equipo (completar y revisar antes de entregar):

- **Código y especificaciones asistidos con IA**: gran parte del backend (relé de voz, voz por etapas con Groq,
  contrato, límites del WebSocket, pruebas y servicios simulados), del frontend (transporte WebSocket, audio,
  transcripción en vivo) y de los documentos de OpenSpec, este README y la guía de despliegue se generaron con
  **Claude Code** (Anthropic) bajo la dirección del equipo, que definió los requisitos, revisó y probó los cambios.
- **Audio sintético de prueba**: las preguntas de oro en `backend/tests/audio/gold/` se generaron con
  `gpt-4o-mini-tts` (OpenAI).
- **En ejecución**: Lumi usa modelos de IA de Groq (LLM) y Deepgram (transcripción y voz), o de OpenAI Realtime
  si se configura.
- TBD: otras herramientas usadas por el equipo y las partes escritas sin IA.
