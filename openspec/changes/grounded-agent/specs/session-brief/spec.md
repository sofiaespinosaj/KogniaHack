## ADDED Requirements

### Requirement: Brief como saludo conversacional
El sistema SHALL generar al conectar la fuente un saludo hablado de la asistente Ivy, cálido y breve, que diga en lenguaje cotidiano en qué puede ayudar (encontrar hospitales y clínicas, a dónde ir, cómo contactarlas, capacidad cercana) e invite a la persona a conversar, y SHALL NOT incluir información que no esté respaldada por el perfil. El corte de los datos SHALL entregarse en el campo `fecha_corte` del brief para mostrarlo en pantalla, sin leerlo en el saludo (decisión de producto).

#### Scenario: Saludo amable
- **WHEN** se genera el brief con el snapshot actual
- **THEN** el texto empieza saludando como Ivy, menciona hospitales y clínicas de Colombia y termina con una pregunta que invita a conversar

#### Scenario: Sin lenguaje técnico
- **WHEN** se genera el brief
- **THEN** el texto no menciona «dataset», «base de datos», la fecha de corte ni el grano de los datos

#### Scenario: Corte disponible para la UI
- **WHEN** los datos provienen del snapshot
- **THEN** el brief trae `fecha_corte` igual a 2022-11-05 y el texto no afirma que los datos sean actuales

### Requirement: Limitaciones explicadas en la conversación
La asistente SHALL explicar en la conversación, cuando la pregunta lo requiera, que las IPS se cuentan como prestadores distintos y que el nivel de atención casi solo existe para IPS públicas, según las reglas de `agent-grounding`.

#### Scenario: Pregunta por nivel de atención
- **WHEN** la persona pregunta por IPS de un nivel de atención sin indicar naturaleza
- **THEN** la respuesta aclara que el dato corresponde principalmente a IPS públicas

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
