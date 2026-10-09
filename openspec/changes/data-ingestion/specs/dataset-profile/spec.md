## ADDED Requirements

### Requirement: Perfil del dataset
El sistema SHALL calcular, tras cada carga o refresco, un perfil con nombre y tipo de cada columna de `ips`, número total de filas, valores nulos por columna y los valores de cada columna con sus conteos: TODOS los valores distintos cuando la columna tiene 50 o menos (para que otros módulos, como los enums de `grounded-agent`, se generen desde el perfil) y solo los 10 principales cuando tiene más de 50, salvo identificadores y datos de contacto, de los que no se listan valores.

#### Scenario: Perfil tras carga exitosa
- **WHEN** la carga a DuckDB finaliza
- **THEN** el perfil está disponible y su total de filas coincide con el de la tabla `ips`

#### Scenario: Columna categórica
- **WHEN** una columna tiene 50 valores distintos o menos
- **THEN** el perfil incluye todos sus valores con sus conteos (por ejemplo los 33 valores de `departamento_canonico`)

#### Scenario: Columna de alta cardinalidad
- **WHEN** una columna tiene más de 50 valores distintos
- **THEN** el perfil incluye solo sus 10 valores principales con sus conteos y marca que la lista no es completa

### Requirement: Grano de los datos
El sistema SHALL declarar en el perfil que cada fila representa una sede por ítem de capacidad, y SHALL definir IPS como `COUNT(DISTINCT codigo_prestador)` y sedes como `COUNT(DISTINCT sede_id)`, donde `sede_id` es la columna derivada de `ips` que combina `codigo_sede` y `numero_sede`.

#### Scenario: Conteos del corte actual
- **WHEN** se solicita el perfil del snapshot actual
- **THEN** reporta 41.427 filas, 9.320 IPS distintas y 15.547 sedes distintas

#### Scenario: Pregunta sobre cuántas IPS
- **WHEN** el agente necesita responder cuántas IPS existen
- **THEN** el perfil le indica que debe contar prestadores distintos y no filas

### Requirement: Cobertura por columna
El sistema SHALL incluir en el perfil el número y el porcentaje de valores nulos de cada columna y SHALL señalar las limitaciones de cobertura conocidas, entre ellas que `nivel_atencion` es nulo en 25.266 filas (61 %) y es prácticamente exclusivo de IPS públicas (16.160 filas públicas con nivel y 1 fila privada con nivel 1).

#### Scenario: Cobertura de nivel de atención
- **WHEN** se solicita la cobertura de `nivel_atencion`
- **THEN** el perfil reporta 25.266 filas nulas (61 %), 16.160 filas públicas con nivel y 1 fila privada con nivel 1, con la nota de que el dato es prácticamente exclusivo de IPS públicas

#### Scenario: Pregunta sobre el nivel de una IPS privada
- **WHEN** el agente consulta el perfil para responder sobre el nivel de atención de una IPS privada
- **THEN** el perfil le permite informar que, salvo una excepción en la fuente, el nivel de atención no existe para IPS privadas

### Requirement: Distribución de naturaleza
El sistema SHALL incluir en el perfil la distribución de filas por naturaleza jurídica.

#### Scenario: Distribución del corte actual
- **WHEN** se solicita la distribución por naturaleza del snapshot actual
- **THEN** reporta pública 16.174, privada 25.067 y mixta 186

### Requirement: Antigüedad de los datos
El sistema SHALL incluir en el perfil la fecha de corte de los datos (2022-11-05 en el snapshot actual) y el origen (`api` o `snapshot`) para que el agente los cite al responder.

#### Scenario: Corte citable
- **WHEN** se genera el brief a partir del perfil
- **THEN** el perfil provee la fecha de corte 2022-11-05 junto con el origen de los datos

### Requirement: Insumo para el brief
El sistema SHALL exponer el perfil en una estructura serializable, determinista y basada solo en los datos cargados, para que el agente genere el brief sin inventar contenido.

#### Scenario: Perfil disponible
- **WHEN** el agente solicita el perfil
- **THEN** recibe grano, conteos, cobertura, distribución de naturaleza, fecha de corte y origen

#### Scenario: Perfil tras refresco
- **WHEN** un refresco reemplaza la tabla `ips`
- **THEN** el perfil se recalcula una vez y refleja los nuevos conteos y origen

### Requirement: Rendimiento del perfil
El sistema SHALL calcular el perfil una sola vez por carga o refresco y servirlo desde memoria en menos de 50 ms.

#### Scenario: Consulta repetida
- **WHEN** se solicita el perfil varias veces después de la carga
- **THEN** cada respuesta tarda menos de 50 ms y no recalcula agregaciones
