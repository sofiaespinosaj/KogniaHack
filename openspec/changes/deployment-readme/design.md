## Context

El backend es FastAPI con DuckDB en memoria, carga `data/snapshot.parquet` al arrancar y mantiene un WebSocket largo por sesión hacia el navegador y otros dos por sesión hacia OpenAI Realtime y Deepgram. Ya existe `backend/Dockerfile` que copia el snapshot y escucha en `$PORT`. El frontend es una SPA de Vite que lee `VITE_WS_URL` (y reservará `VITE_API_URL`). La protección del WebSocket (Origin contra `CORS_ORIGINS`, límites por IP con `X-Forwarded-For`) ya está implementada en `realtime-voice`, y `CORS_ORIGINS` admite patrones con `*`.

## Goals / Non-Goals

**Goals:**
- Una URL pública que funcione a la primera durante los 10 minutos de la evaluación.
- Ningún secreto en el frontend ni en el repositorio.
- Una verificación automática (prueba de humo) y una manual (checklist) antes de la demo.

**Non-Goals:**
- Escalado horizontal, varias réplicas o balanceo de sesiones.
- CI/CD completo o infraestructura como código más allá de un archivo de servicio opcional.
- Dominio propio (se usan los dominios de Render y Vercel; TBD si se añade uno).

## Decisions

1. **Plataforma del backend: Render, plan Starter o superior, región Virginia (us-east).**
   - WebSocket nativo sobre HTTPS (WSS) sin configuración adicional y TLS automático.
   - El plan de pago mantiene la instancia siempre encendida: sin arranque en frío (el gratuito se duerme a los 15 minutos y tarda en despertar).
   - Despliegue desde Docker con *health check* sobre `/health`: un despliegue que no arranca no reemplaza al anterior.
   - Costo fijo y predecible (unos USD 7 al mes), sin facturación por uso que sorprenda durante la demo.
   - Virginia queda cerca de los servidores de OpenAI y Deepgram (EE. UU.), que dominan la latencia del relé; el salto desde Colombia es corto.
   - Alternativas: **Railway** (también sin dormir y con WebSocket, pero facturación por uso y menos control del *health check*); **Fly.io** (máquinas con `min_machines_running = 1` y `auto_stop_machines = false`, más configuración y CLI propia). Ambas son válidas; se elige Render por simplicidad y costo fijo.
   - Riesgo aceptado: un despliegue corta los WebSocket abiertos, así que no se despliega durante la demo.
2. **Imagen con el snapshot.** Se mantiene el Dockerfile actual (Python 3.12 slim, `uv sync --frozen --no-dev`, snapshot copiado en `/app/data`). Con `SODA_APP_TOKEN` el refresco corre en segundo plano; sin él se sirve el snapshot.
3. **Variables del backend en el panel de Render** (nunca en el repositorio): `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, `SODA_APP_TOKEN` (opcional), `VOICE_ENABLED=true`, `CORS_ORIGINS=https://<proyecto>.vercel.app,https://<proyecto>-*-<equipo>.vercel.app`, `VAD_TYPE=server_vad`, `VAD_THRESHOLD`, `VAD_PREFIX_PADDING_MS`, `VAD_SILENCE_MS`, `OPENAI_REALTIME_MODEL=gpt-realtime-mini`. El patrón de vistas previas se limita al proyecto y al equipo para no aceptar cualquier `*.vercel.app`.
4. **Frontend en Vercel** con `VITE_WS_URL=wss://<backend>.onrender.com/ws` y `VITE_API_URL=https://<backend>.onrender.com` para producción y vistas previas. Son valores públicos; las claves nunca pasan por el frontend.
5. **`/health`** informa `status` de los datos (`loading`, `ready`, `degraded`, `unavailable`), la procedencia (`data`) y `voice` (`enabled` o `disabled`). Se añade si las claves de voz están presentes (sin valores) para que el checklist lo vea de un vistazo.
6. **Prueba de humo** (`scripts/smoke.py`, Python con `httpx` y `websockets`, dependencias que ya tiene el backend) contra la URL pública: `/health` listo y con voz, `/api/brief` con texto y de 3 a 5 preguntas, y una sesión WebSocket con `brief: "skip"` y `text.message` que debe producir `transcript.final`, `agent.tool`, `agent.text` final y `metrics` en 20 s o menos. Envía la cabecera `Origin` del frontend para probar CORS. Código de salida distinto de 0 si falla algo.
7. **Calentamiento.** Aunque no haya arranque en frío, antes de la demo se llama a `/health` y se corre la prueba de humo para abrir conexiones y cargar cachés del sistema operativo.
8. **README de una página** en la raíz: qué es, URL pública, stack, diagrama de arquitectura, decisiones técnicas clave (relé, Deepgram, DuckDB, snapshot, contrato), cómo ejecutar en local y la declaración de uso de IA.

9. **Actualización: proveedor de voz Groq.** Con `VOICE_PROVIDER=groq` (por defecto desde que se agotó el crédito de OpenAI) las claves del backend son `GROQ_API_KEY` y `DEEPGRAM_API_KEY`; `OPENAI_API_KEY` solo se necesita con `VOICE_PROVIDER=openai`. La región de Virginia sigue cerca de Groq y Deepgram.

## Risks / Trade-offs

- [Las claves no tienen crédito el día de la demo] → El checklist exige verificar saldo de OpenAI y Deepgram y correr la prueba de humo con voz habilitada.
- [CORS u Origin mal configurados bloquean el WebSocket desde Vercel] → La prueba de humo envía el `Origin` de producción; el checklist incluye una prueba de voz desde el frontend desplegado.
- [Un despliegue corta las sesiones en curso] → Congelar despliegues durante la demo.
- [La IP real detrás del proxy] → Render envía `X-Forwarded-For`; el límite por IP lo usa (verificado en la prueba de humo con dos sesiones).
- [Falla OpenAI durante la demo] → La degradación de `realtime-voice` mantiene la sesión; el frontend con `?mock` queda como plan B visual.

## Migration Plan

1. Crear el servicio en Render desde el repositorio con `backend/Dockerfile` (contexto en la raíz) y *health check* `/health`.
2. Cargar las variables del backend y desplegar; esperar `status: ready` y `voice: enabled`.
3. Crear el proyecto en Vercel con raíz `frontend/`, cargar `VITE_WS_URL` y `VITE_API_URL` y desplegar.
4. Actualizar `CORS_ORIGINS` con los dominios finales de Vercel y redesplegar el backend.
5. Correr la prueba de humo y el checklist. Reversión: Render y Vercel permiten volver al despliegue anterior desde su panel.

## Open Questions

- Nombres finales de los servicios y URLs públicas (TBD).
- Si se versiona un `render.yaml` o se configura solo desde el panel (TBD).
- Si se añade un dominio propio (TBD).
