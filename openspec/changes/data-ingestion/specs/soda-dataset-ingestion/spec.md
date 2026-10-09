## ADDED Requirements

### Requirement: Cliente SODA3 con autenticación por X-App-Token
El sistema SHALL consultar `https://www.datos.gov.co/api/v3/views/s2ru-bqt6/query.json` mediante `POST` con cuerpo `{"query": "...", "page": {"pageNumber": N, "pageSize": 1000}}`, autenticando solo con la cabecera `X-App-Token` cuyo valor se lee de la variable de entorno `SODA_APP_TOKEN`, y SHALL NOT incluir el token en logs, respuestas ni código fuente.

#### Scenario: Token presente
- **WHEN** el backend refresca los datos con `SODA_APP_TOKEN` definida
- **THEN** cada llamada a SODA3 incluye la cabecera `X-App-Token`

#### Scenario: Token ausente
- **WHEN** el backend arranca sin `SODA_APP_TOKEN`
- **THEN** carga el snapshot, omite el refresco, registra una advertencia sin revelar secretos y reporta el motivo en los metadatos

### Requirement: Paginación completa y validada
El sistema SHALL obtener el total con `SELECT count(*)`, descargar las páginas con `ORDER BY :id`, `pageSize` 1000 y `pageNumber` desde 1, y SHALL validar que las filas descargadas igualen el total y que los `:id` sean únicos y no nulos.

#### Scenario: Descarga completa
- **WHEN** se ejecuta una descarga completa
- **THEN** se obtienen tantas filas como el total reportado (41.427 en el corte actual) sin `:id` duplicados

#### Scenario: Descarga incompleta
- **WHEN** el número de filas descargadas no coincide con el total o hay `:id` duplicados
- **THEN** el sistema descarta la descarga, conserva la tabla vigente y registra el error

### Requirement: Arranque snapshot-first
El sistema SHALL cargar `data/snapshot.parquet` en una tabla DuckDB en memoria durante el arranque, SHALL pasar a estado `ready` en 5 s o menos y SHALL NOT bloquear las sesiones esperando a la API.

#### Scenario: Arranque normal
- **WHEN** el backend arranca con el snapshot disponible
- **THEN** el estado de datos es `ready` en 5 s o menos y las sesiones se aceptan sin esperar al refresco

#### Scenario: Snapshot ausente o ilegible
- **WHEN** el snapshot no existe o no se puede leer
- **THEN** el sistema intenta una descarga completa desde la API, queda en estado `loading` hasta terminar y pasa a `unavailable` si también falla, informándolo en `/health` sin abortar con una traza

### Requirement: Refresco en segundo plano con swap atómico
El sistema SHALL refrescar el dataset desde la API en segundo plano, con una meta de 180 s o menos, y SHALL reemplazar la tabla `ips` mediante un swap atómico solo si el conteo de filas coincide con el total reportado por la API.

#### Scenario: Refresco exitoso
- **WHEN** la descarga en segundo plano termina con conteo igual al total reportado
- **THEN** la tabla `ips` se reemplaza atómicamente, el origen pasa a `api` y las consultas en curso no fallan

#### Scenario: Refresco fallido
- **WHEN** la API falla, devuelve datos incompletos o el conteo no coincide
- **THEN** la tabla vigente se conserva, el origen sigue siendo `snapshot` y el estado sigue en `ready`

#### Scenario: Meta de duración del refresco
- **WHEN** se mide un refresco completo con la API disponible
- **THEN** termina en 180 s o menos (referencia: 126,6 s con concurrencia 4)

### Requirement: Tratamiento de errores de la API
El sistema SHALL NOT reintentar respuestas 401 y 403, SHALL respetar `Retry-After` en respuestas 429 y SHALL reintentar con backoff exponencial los errores de red y 5xx hasta un máximo configurable.

#### Scenario: Token inválido
- **WHEN** la API responde 401 o 403
- **THEN** el sistema no reintenta, registra un error de autenticación sin el token y conserva los datos vigentes

#### Scenario: Límite de peticiones
- **WHEN** la API responde 429 con `Retry-After`
- **THEN** el sistema espera ese tiempo antes de reintentar

#### Scenario: Error transitorio
- **WHEN** una página responde 503 en el primer intento y 200 en el segundo
- **THEN** la página se incorpora a la descarga sin intervención del usuario

### Requirement: Tabla ips normalizada
El sistema SHALL exponer los datos en una tabla `ips` con alias legibles (por ejemplo `codigo_prestador`, `nombre_prestador`, `direccion`, `telefono`, `grupo_capacidad`, `descripcion_capacidad`), `nivel_atencion` y `cantidad_capacidad` como enteros, `fecha_corte` como fecha, el texto original en `fecha_corte_texto` y una columna `departamento_canonico` que asigna los distritos a su departamento (Cali y Buenaventura a Valle del Cauca, Barranquilla a Atlántico, Cartagena a Bolívar, Santa Marta a Magdalena; Bogotá D.C. sin cambio), y columnas `*_norm` (departamento, municipio, nombre de prestador, nombre de sede, grupo y descripción de capacidad) en minúsculas y sin tildes.

#### Scenario: Tipos y alias
- **WHEN** se describe la tabla `ips`
- **THEN** `nivel_atencion` y `cantidad_capacidad` son enteros, `fecha_corte` es fecha y existen las columnas con alias limpios

#### Scenario: Columnas normalizadas
- **WHEN** una fila tiene el departamento "Bogotá D.C." (u otro valor con tildes o mayúsculas)
- **THEN** `departamento_norm` contiene el mismo texto en minúsculas y sin tildes

#### Scenario: Departamento canónico
- **WHEN** una fila tiene departamento "Cali"
- **THEN** su `departamento_canonico` es "Valle del Cauca" y ninguna fila queda sin valor canónico

#### Scenario: Valores no convertibles
- **WHEN** un valor numérico o de fecha no se puede convertir
- **THEN** la columna tipada queda nula, se conserva el texto original donde aplique y el recuento de fallos se reporta en los metadatos

### Requirement: Metadatos de procedencia
El sistema SHALL conservar y exponer la procedencia de los datos: identificador del dataset, fecha de carga, origen (`api` o `snapshot`), número de filas y fecha de corte de los datos (2022-11-05 en el snapshot actual), para que el agente pueda citar de dónde y de cuándo sale cada dato.

#### Scenario: Consulta de procedencia
- **WHEN** otro módulo solicita los metadatos del dataset
- **THEN** recibe `s2ru-bqt6`, la fecha de carga, el origen, el número de filas y la `fecha_corte`

### Requirement: Configuración validada al arrancar
El sistema SHALL leer su configuración de variables de entorno (`SODA_APP_TOKEN`, `SODA_PAGE_SIZE`, `SODA_CONCURRENCY`, `SODA_MAX_TRIES`, `DATA_PATH`, `CORS_ORIGINS` y las claves de LLM, STT y TTS), SHALL terminar el arranque con un mensaje claro que nombre la variable cuando falte una obligatoria, y SHALL NOT imprimir los valores de las variables. Las claves de LLM, STT y TTS son obligatorias solo cuando el módulo que las usa está habilitado; `SODA_APP_TOKEN` es opcional si existe snapshot.

#### Scenario: Clave de módulo habilitado ausente
- **WHEN** el backend arranca con un módulo habilitado (LLM, STT o TTS) y sin su clave
- **THEN** el proceso termina con un mensaje que nombra la variable faltante y no imprime ningún valor de configuración

#### Scenario: Variable opcional con valor por defecto
- **WHEN** `SODA_PAGE_SIZE`, `SODA_CONCURRENCY` o `SODA_MAX_TRIES` no están definidas
- **THEN** el sistema usa los valores 1000, 4 y 5 respectivamente

#### Scenario: Plantilla de configuración
- **WHEN** se revisa el repositorio
- **THEN** existe `.env.example` con todas las variables y placeholders, y `.env` está excluido del control de versiones

### Requirement: Verificación del snapshot cargado
El sistema SHALL verificar tras cargar el snapshot que el conteo de filas coincida con el registrado en `snapshot.meta.json`.

#### Scenario: Snapshot consistente
- **WHEN** se carga el snapshot actual
- **THEN** la tabla `ips` tiene 41.427 filas y 10.921 sedes distintas

#### Scenario: Snapshot inconsistente
- **WHEN** el conteo cargado no coincide con el de `snapshot.meta.json`
- **THEN** el sistema registra el error y marca el estado como `degraded`
