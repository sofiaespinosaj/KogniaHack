# Frontend

React 19 + TypeScript + Vite + Tailwind 4. Interfaz de voz del agente sobre el contrato WebSocket 1.0
(`backend/README.md`, sección de eventos).

## Ejecutar

```bash
cd frontend
npm ci
npm run dev        # http://localhost:5173 ; /ws, /api, /health y /profile van por proxy a localhost:8000
npm run build      # incluye la verificación de tipos contra el contrato generado
npm run lint
```

Sin backend: `http://localhost:5173/?mock` (o `VITE_TRANSPORT=mock`) usa `MockTransport`.

## Variables (Vercel)

| Variable | Uso |
|---|---|
| `VITE_WS_URL` | URL del WebSocket del backend, p. ej. `wss://<backend>/ws`. Por defecto `/ws` en el mismo host. |
| `VITE_API_URL` | Base de la API REST del backend (reservada para `deployment-readme`). |
| `VITE_TRANSPORT` | `mock` para la demo sin backend. |

Nunca se ponen claves en el frontend: OpenAI y Deepgram solo se usan desde el backend.

## Audio

- Micrófono: `getUserMedia` con cancelación de eco, `AudioContext` a 24 kHz y un AudioWorklet que entrega
  frames PCM16 de 40 ms (1.920 bytes) por el WebSocket. «Manos libres» abre o cierra el micrófono.
- Voz del agente: los frames binarios se encolan en orden; tras `audio.clear` se vacía la cola y se descartan
  los frames hasta el siguiente `audio.start`. Cada 200 ms se envía `playback.position` para el truncado.
- El barge-in real ocurre hablando encima del agente; el botón «Interrumpir» silencia el audio en el cliente.

## Contrato

`src/api/ws-events.gen.ts` es copia del archivo generado por el backend; `src/api/contract-check.ts` hace
fallar la compilación si los tipos de la UI (`src/api/types.ts`) se apartan de él. Tras cambiar el contrato:

```bash
(cd ../backend && uv run python -m app.ws.export all) && npm run contract
```

## Prueba de extremo a extremo

```bash
npm run e2e        # = ../scripts/e2e_local.sh (requiere uv, Python y Chromium de Playwright)
```
