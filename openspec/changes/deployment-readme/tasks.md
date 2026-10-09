## 1. Backend en Render

- [x] 1.1 Revisar `backend/Dockerfile` (snapshot incluido, sin `.env`, `PORT`) y añadir un `.dockerignore`; verificar con `docker build -f backend/Dockerfile .` y un arranque local sin `SODA_APP_TOKEN` que responda `ready` en `/health` — Hecho: imagen probada localmente (usuario sin privilegios, snapshot, `--proxy-headers`) y `.dockerignore` en la raíz.
- [x] 1.2 Añadir a `/health` la presencia de las claves de voz (sin valores); verificar con una prueba que la respuesta no contiene valores de claves — Hecho: `voice_provider` y `voice_keys` (solo presencia).
- [ ] 1.3 Crear el servicio en Render (plan siempre encendido, Virginia, *health check* `/health`, decidir si se versiona `render.yaml`) y cargar las variables de producción; verificar `voice: enabled` en la URL pública — Preparado: `render.yaml` (Blueprint); falta crear el servicio con las claves.
- [ ] 1.4 Configurar `CORS_ORIGINS` con el dominio de producción y el patrón de vistas previas del proyecto; verificar que un `Origin` ajeno recibe 403 y uno de Vercel se acepta — Patrones con `*` soportados y probados; falta poner los dominios finales.

## 2. Frontend en Vercel

- [ ] 2.1 Crear el proyecto en Vercel con raíz `frontend/` y las variables `VITE_WS_URL` y `VITE_API_URL` para producción y vistas previas; verificar que la URL de producción carga y conecta por WSS — Preparado: `frontend/vercel.json` y `frontend/.env.example`; falta crear el proyecto.
- [x] 2.2 Comprobar que el paquete publicado no contiene claves (búsqueda de `sk-` y de la clave de Deepgram) y que sin micrófono se ofrece el teclado — Hecho: el bundle no contiene claves; sin micrófono la UI ofrece el teclado.

## 3. Prueba de humo y checklist

- [ ] 3.1 Escribir `scripts/smoke.py` (health, `/api/brief` y sesión WebSocket con `text.message` y `Origin`), con código de salida y sin imprimir claves; verificar contra el backend local con servicios simulados y contra la URL pública — `backend/scripts/smoke.py` verificado contra la imagen Docker con servicios simulados; falta contra la URL pública.
- [ ] 3.2 Documentar el checklist previo a la demo (claves y crédito, CORS, prueba de humo, prueba de voz desde el frontend desplegado, calentamiento, congelar despliegues) y recorrerlo una vez completo — Documentado en `docs/DEPLOY.md`; falta recorrerlo.

## 4. README

- [ ] 4.1 Escribir el `README.md` de una página (qué es, URLs, stack, diagrama, decisiones, ejecución local, pruebas, limitaciones) y la declaración de uso de IA; verificar que el jurado puede seguirlo sin abrir otros archivos — `README.md` escrito; faltan las URLs finales y que el equipo complete la declaración de IA.
