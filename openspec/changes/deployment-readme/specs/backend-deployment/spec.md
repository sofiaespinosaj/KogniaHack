## ADDED Requirements

### Requirement: Imagen Docker con snapshot
El sistema SHALL construirse como una imagen Docker desde la raíz del repositorio que incluya `data/snapshot.parquet` y `data/snapshot.meta.json`, que instale las dependencias bloqueadas sin las de desarrollo y que escuche en el puerto indicado por `PORT`. La imagen SHALL NOT contener claves ni archivos `.env`.

#### Scenario: Arranque sin la API
- **WHEN** el contenedor arranca sin `SODA_APP_TOKEN`
- **THEN** sirve los datos del snapshot y `/health` informa `ready` con origen `snapshot`

#### Scenario: Sin secretos en la imagen
- **WHEN** se inspeccionan las capas de la imagen
- **THEN** no hay archivos `.env` ni valores de claves

### Requirement: Plataforma con WebSocket y sin arranque en frío
El backend SHALL desplegarse en Render con una instancia siempre encendida en la región de Virginia, SHALL aceptar conexiones WebSocket seguras (WSS) en `/ws` y SHALL usar `/health` como verificación del despliegue.

#### Scenario: Sin arranque en frío
- **WHEN** el servicio lleva más de 15 minutos sin tráfico y llega una petición a `/health`
- **THEN** responde en 1 s o menos sin esperar a que arranque una instancia

#### Scenario: WSS
- **WHEN** el navegador abre `wss://<backend>/ws` desde el frontend desplegado
- **THEN** el handshake se completa por TLS y la sesión de voz funciona

#### Scenario: Despliegue fallido
- **WHEN** un despliegue nuevo no responde en `/health`
- **THEN** sigue sirviendo la versión anterior

### Requirement: Variables de entorno del backend
El backend desplegado SHALL configurarse solo con variables de entorno de la plataforma: `OPENAI_API_KEY`, `DEEPGRAM_API_KEY`, `SODA_APP_TOKEN` (opcional), `VOICE_ENABLED=true`, `CORS_ORIGINS` con el dominio de producción y el patrón de vistas previas de Vercel del proyecto, los parámetros del VAD y `OPENAI_REALTIME_MODEL`.

#### Scenario: Voz habilitada
- **WHEN** el servicio arranca con las variables de producción
- **THEN** `/health` informa `voice` igual a `enabled`

#### Scenario: Vistas previas de Vercel
- **WHEN** una vista previa del proyecto en Vercel abre el WebSocket
- **THEN** su `Origin` coincide con el patrón de `CORS_ORIGINS` y la conexión se acepta

#### Scenario: Origen ajeno
- **WHEN** una página de otro dominio intenta abrir el WebSocket
- **THEN** el handshake se rechaza con HTTP 403

### Requirement: Estado de datos y voz en /health
El endpoint `/health` SHALL informar el estado de los datos, su procedencia y el estado de la voz, e indicar si las claves de voz están presentes sin revelar sus valores.

#### Scenario: Servicio listo
- **WHEN** se consulta `/health` con el servicio listo y la voz configurada
- **THEN** la respuesta incluye `status` igual a `ready`, `voice` igual a `enabled`, la procedencia de los datos y ningún valor de clave

### Requirement: Prueba de humo contra la URL pública
El proyecto SHALL incluir un script de prueba de humo que, contra la URL pública del backend, verifique `/health`, `GET /api/brief` y una sesión WebSocket con `text.message`, envíe el `Origin` del frontend y termine con código distinto de 0 si algo falla.

#### Scenario: Todo funciona
- **WHEN** se ejecuta la prueba contra el backend desplegado
- **THEN** `/health` está listo con voz, el brief trae texto y de 3 a 5 preguntas y la sesión produce `transcript.final`, `agent.tool`, `agent.text` final y `metrics` en 20 s o menos

#### Scenario: Fallo
- **WHEN** alguna verificación falla
- **THEN** el script nombra la verificación fallida, no imprime claves y termina con código distinto de 0

### Requirement: Checklist previo a la demo
El proyecto SHALL documentar un checklist previo a la demo que incluya: claves válidas y con crédito en OpenAI y Deepgram, `CORS_ORIGINS` con los dominios finales, prueba de humo en verde, una prueba de voz desde el frontend desplegado (brief, una pregunta por voz y una interrupción), calentamiento del servicio minutos antes y congelamiento de despliegues durante la demo.

#### Scenario: Antes de la evaluación
- **WHEN** faltan 15 minutos para la evaluación
- **THEN** el equipo puede recorrer el checklist completo y marcar cada punto
