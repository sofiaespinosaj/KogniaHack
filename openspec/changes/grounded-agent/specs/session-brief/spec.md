## ADDED Requirements

### Requirement: Brief generado desde el perfil
El sistema SHALL generar al conectar la fuente un brief a partir del perfil del dataset que explique de qué trata, su alcance, su antigüedad (corte del 5 de noviembre de 2022) y sus limitaciones, y SHALL NOT incluir información que no esté en el perfil.

#### Scenario: Contenido del brief
- **WHEN** se genera el brief con el snapshot actual
- **THEN** menciona que trata de IPS públicas y privadas según su nivel de atención y capacidad instalada, con 9.320 IPS y 15.547 sedes, y el corte del 5 de noviembre de 2022

#### Scenario: Origen citado
- **WHEN** los datos provienen del snapshot
- **THEN** el brief indica el corte y no afirma que los datos sean actuales

### Requirement: Limitaciones declaradas en el brief
El brief SHALL declarar el grano de los datos (cada fila es una sede por ítem de capacidad, por lo que las IPS se cuentan como prestadores distintos) y que el nivel de atención casi solo existe para IPS públicas.

#### Scenario: Grano y nivel de atención
- **WHEN** se genera el brief
- **THEN** incluye una frase sobre el conteo por prestadores distintos y otra sobre la cobertura del nivel de atención

### Requirement: Preguntas sugeridas
El brief SHALL incluir entre 3 y 5 preguntas sugeridas pertinentes al dataset, y cada una SHALL poder responderse con las tools de `agent-tools`.

#### Scenario: Cantidad de preguntas
- **WHEN** se genera el brief
- **THEN** contiene entre 3 y 5 preguntas sugeridas

#### Scenario: Preguntas respondibles
- **WHEN** se ejecuta la validación del brief
- **THEN** cada pregunta sugerida se resuelve con una o dos llamadas a tools y el resultado tiene estado `ok`

#### Scenario: Sin preguntas sobre lo no cubierto
- **WHEN** se revisan las preguntas sugeridas
- **THEN** ninguna pide datos fuera de la fuente ni el nivel de atención de IPS privadas

### Requirement: Brief como respuesta inicial de la sesión
El sistema SHALL emitir el brief como respuesta inicial de la sesión Realtime una vez establecida la conexión, sin esperar a que el usuario hable, y SHALL entregar al cliente el texto del brief y las preguntas sugeridas en datos estructurados para mostrarlos en pantalla. El esquema del evento corresponde al contrato definido en `realtime-voice`.

#### Scenario: Inicio de sesión
- **WHEN** la sesión queda lista
- **THEN** el agente inicia la respuesta con el brief hablado sin intervención del usuario

#### Scenario: Brief hablado breve
- **WHEN** el agente dice el brief
- **THEN** su duración hablada es de 20 s o menos (meta inicial, a validar)

#### Scenario: Datos para la pantalla
- **WHEN** se emite el brief
- **THEN** el cliente recibe el texto y la lista de preguntas sugeridas como datos estructurados

### Requirement: Brief determinista y reutilizable
El sistema SHALL construir el brief de forma determinista desde el perfil, almacenarlo en memoria y reconstruirlo tras cada refresco de datos.

#### Scenario: Mismo perfil, mismo brief
- **WHEN** se genera el brief dos veces con el mismo perfil
- **THEN** el contenido es idéntico

#### Scenario: Refresco de datos
- **WHEN** un refresco cambia el perfil
- **THEN** las sesiones nuevas reciben un brief con las cifras actualizadas
