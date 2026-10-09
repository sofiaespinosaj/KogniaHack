## Why

La evaluación es en vivo, sobre una URL pública y sin instalación local, y el despliegue y el entregable pesan 10 %. `realtime-voice` deja a este change el Dockerfile, la plataforma, CORS, WSS y el `/health` completo, y `project.md` exige un README que declare qué se generó con IA. Un fallo de configuración el día de la demo (CORS, claves sin crédito, servicio dormido) anula todo lo demás.

## What Changes

- Imagen Docker del backend con el snapshot del dataset incluido, para arrancar sin depender de la API SODA3.
- Backend en **Render** (plan con instancia siempre encendida, región de Virginia), con WebSocket y sin arranque en frío; decisión justificada frente a Railway y Fly.
- Frontend en Vercel con `VITE_API_URL` y `VITE_WS_URL`, sin claves.
- Variables de entorno del backend: `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, `SODA_APP_TOKEN` (opcional), `VOICE_ENABLED=true`, `CORS_ORIGINS` con el dominio de producción y el patrón de vistas previas de Vercel, parámetros del VAD y `OPENAI_REALTIME_MODEL`.
- WSS extremo a extremo y `/health` que informa el estado de los datos y de la voz.
- Script de prueba de humo contra la URL pública: `/health`, `/api/brief` y una sesión WebSocket con `text.message`.
- Checklist previo a la demo: claves y crédito, CORS, prueba de voz desde el frontend desplegado y calentamiento del servicio.
- README de una página con stack, arquitectura, decisiones técnicas y declaración de qué se generó con IA.

## Capabilities

### New Capabilities
- `backend-deployment`: imagen, plataforma, variables de entorno, WSS, `/health`, prueba de humo y checklist del backend.
- `frontend-deployment`: despliegue del frontend en Vercel, sus variables y su conexión con el backend.
- `project-readme`: README de una página del proyecto, con la declaración de uso de IA.

### Modified Capabilities

(ninguna)

## Impact

- `backend/Dockerfile` (ya existe con el snapshot; se ajusta si hace falta), configuración del servicio en Render (`render.yaml`, TBD si se versiona) y `scripts/smoke.py` nuevo.
- Configuración del proyecto en Vercel (variables `VITE_*`); sin cambios de código del frontend más allá de usar esas variables, que ya lee.
- `README.md` en la raíz del repositorio.
- Reutiliza sin redefinir: la configuración validada de `data-ingestion`, la protección del WebSocket y el contrato de `realtime-voice` y el `GET /api/brief` de `grounded-agent`.
- Costo: plan de pago mínimo de Render para evitar el arranque en frío.
