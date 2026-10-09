# Despliegue de Lumi

Backend en **Render** (Docker, siempre encendido, Virginia) y frontend en **Vercel**. Las claves viven solo en
Render; el frontend solo conoce la URL pública del backend.

## 1. Backend en Render

1. Render → **New → Blueprint** → elige este repositorio. Render lee `render.yaml` (servicio `lumi-backend`,
   Docker con `backend/Dockerfile`, plan **Starter**, región Virginia, rama `dev`, *health check* `/health`).
   - El plan Starter (de pago) evita que el servicio se duerma: con el plan gratuito, la primera petición tras
     15 minutos sin uso tarda alrededor de un minuto, que es inaceptable en una demo en vivo.
2. Render pide los valores marcados `sync: false`:
   | Variable | Valor |
   |---|---|
   | `GROQ_API_KEY` | tu clave de Groq (`gsk_...`) |
   | `DEEPGRAM_API_KEY` | tu clave de Deepgram |
   | `SODA_APP_TOKEN` | opcional; déjalo vacío para servir el snapshot incluido |
   | `CORS_ORIGINS` | por ahora `http://localhost:5173`; en el paso 3 pones los dominios de Vercel |
3. Espera el despliegue y abre `https://<servicio>.onrender.com/health`. Debe decir `"status":"ready"`,
   `"voice":"enabled"`, `"voice_provider":"groq"` y `voice_keys` con `groq` y `deepgram` en `true`.

## 2. Frontend en Vercel

1. Vercel → **Add New → Project** → este repositorio → **Root Directory: `frontend`** (Vercel detecta Vite;
   `frontend/vercel.json` fija el build y la reescritura a `index.html`).
2. **Environment Variables** (Production y Preview):
   | Variable | Valor |
   |---|---|
   | `VITE_WS_URL` | `wss://<servicio>.onrender.com/ws` |
   | `VITE_API_URL` | `https://<servicio>.onrender.com` |
3. Despliega. El dominio de producción queda como `https://<proyecto>.vercel.app` y las vistas previas como
   `https://<proyecto>-<rama-o-hash>-<equipo>.vercel.app`.

## 3. Conectar los dos (CORS)

En Render → `lumi-backend` → **Environment**, cambia `CORS_ORIGINS` por el dominio de producción y el patrón de
vistas previas de tu proyecto, separados por coma:

```
https://<proyecto>.vercel.app,https://<proyecto>-*-<equipo>.vercel.app
```

El `*` solo cubre un tramo del subdominio, así que no acepta cualquier `*.vercel.app`. Guarda: Render redespliega.

## 4. Prueba de humo

Desde tu equipo, en `backend/`:

```bash
uv run python -m scripts.smoke https://<servicio>.onrender.com --origin https://<proyecto>.vercel.app
```

Verifica `/health`, CORS, `/api/brief` y una sesión WebSocket por WSS con una pregunta que usa una herramienta.
Termina con «Prueba de humo superada.» o con la línea `FALLA` que explica qué revisar.

## Checklist previo a la demo

- [ ] **Claves y crédito**: saldo disponible en Deepgram y límites de Groq suficientes (el plan gratuito de Groq
      limita peticiones por minuto; si el agente dice «tuve un problema para consultar», revisa en los logs de Render
      si aparece `HTTP 429`).
- [ ] **`/health`** con `ready`, `voice: enabled` y las dos claves presentes.
- [ ] **CORS**: `CORS_ORIGINS` con el dominio final de Vercel; la prueba de humo con `--origin` pasa.
- [ ] **Prueba de humo** en verde contra la URL pública.
- [ ] **Prueba de voz desde el frontend desplegado**, con audífonos: suena el brief, una pregunta por voz
      (por ejemplo «¿a qué IPS puedo ir en Manizales?»), una interrupción hablando encima de Lumi, y el historial
      muestra «Hablante 1».
- [ ] **Calentar** el servicio 5 minutos antes: abrir `/health` y correr la prueba de humo.
- [ ] **Congelar despliegues** durante la demo: un despliegue corta las sesiones abiertas (desactiva *Auto-Deploy*
      en Render o no hagas push a `dev`).
- [ ] Plan B visual: `https://<proyecto>.vercel.app/?mock` funciona sin backend.

## Problemas frecuentes

| Síntoma | Causa probable |
|---|---|
| El front muestra «Error» al conectar | `VITE_WS_URL` mal escrita (debe ser `wss://` y terminar en `/ws`) o el origen no está en `CORS_ORIGINS` (el backend responde 403 y lo registra como «Origen rechazado») |
| «El servicio de voz no está disponible» | En los logs de Render: `No se pudo iniciar Groq: …` con el motivo (clave inválida, sin red) |
| «No puedo escucharte en este momento» | Deepgram no conecta; los logs dicen `No se pudo conectar con Deepgram: HTTP …` (401 clave, 402 sin saldo) |
| El micrófono no abre | El sitio debe abrirse por `https://`; el aviso en pantalla dice la causa (permiso, otro programa lo usa…) |
