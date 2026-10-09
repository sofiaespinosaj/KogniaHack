## ADDED Requirements

### Requirement: Frontend en Vercel
El frontend SHALL desplegarse en Vercel desde la carpeta `frontend/` como sitio estático construido con Vite, con un despliegue de producción y vistas previas por rama.

#### Scenario: Producción
- **WHEN** se abre la URL de producción del frontend
- **THEN** la aplicación carga sin instalación local y se conecta al backend desplegado

#### Scenario: Vista previa
- **WHEN** se abre una vista previa de una rama
- **THEN** la aplicación se conecta al mismo backend y el WebSocket es aceptado

### Requirement: Variables del frontend sin claves
El frontend SHALL configurarse con `VITE_API_URL` (base HTTPS del backend) y `VITE_WS_URL` (URL WSS de `/ws`) y SHALL NOT contener claves de OpenAI, Deepgram ni SODA en su código, su configuración ni el paquete publicado.

#### Scenario: Conexión configurada
- **WHEN** el frontend se construye con `VITE_WS_URL=wss://<backend>/ws`
- **THEN** abre el WebSocket con esa URL

#### Scenario: Sin secretos en el paquete
- **WHEN** se busca en los archivos publicados por Vercel un prefijo de clave como `sk-`
- **THEN** no aparece ninguna clave

### Requirement: Micrófono en contexto seguro
El frontend desplegado SHALL servirse por HTTPS para que el navegador permita el micrófono y SHALL ofrecer la entrada por teclado si el micrófono no está disponible o se niega el permiso.

#### Scenario: Permiso denegado
- **WHEN** el usuario niega el permiso del micrófono
- **THEN** la UI lo indica y permite escribir las preguntas
