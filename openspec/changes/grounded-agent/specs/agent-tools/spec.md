## ADDED Requirements

### Requirement: Registro de function tools en la sesión
El sistema SHALL registrar las tools `count_ips`, `count_sedes`, `sum_capacidad`, `top_n`, `group_by` y `buscar_ips` como function tools de la sesión Realtime, SHALL ejecutarlas del lado del servidor contra la tabla `ips` de DuckDB y SHALL devolver cada resultado como salida de la función en JSON compacto.

#### Scenario: Sesión con tools
- **WHEN** se crea una sesión
- **THEN** la sesión expone exactamente esas seis tools con sus esquemas de argumentos

#### Scenario: Ejecución en servidor
- **WHEN** el modelo invoca una tool
- **THEN** el servidor ejecuta la consulta en DuckDB y devuelve el resultado como salida de la función sin exponer SQL ni credenciales al cliente

### Requirement: Argumentos validados y sin SQL libre
El sistema SHALL validar los argumentos de cada tool contra un esquema y SHALL NOT aceptar SQL libre. Los valores de `naturaleza`, `nivel_atencion`, `grupo_capacidad` y `departamento` SHALL ser enums generados desde el perfil de datos, y el filtro de departamento SHALL aplicarse sobre `departamento_canonico`.

#### Scenario: Enum válido
- **WHEN** el modelo invoca `count_ips` con `naturaleza` igual a "Pública"
- **THEN** la tool ejecuta la consulta con ese filtro

#### Scenario: Argumento fuera del esquema
- **WHEN** el modelo invoca una tool con un valor que no pertenece al enum o con un campo desconocido
- **THEN** la tool devuelve un error de validación compacto sin ejecutar ninguna consulta

#### Scenario: Enums derivados del perfil
- **WHEN** el perfil cambia tras un refresco de datos
- **THEN** los enums de la sesión siguiente reflejan los valores vigentes

### Requirement: Departamento canónico
El sistema SHALL filtrar y agrupar por `departamento_canonico`, que asigna Cali y Buenaventura a Valle del Cauca, Barranquilla a Atlántico, Cartagena a Bolívar y Santa Marta a Magdalena, y deja Bogotá D.C. como está, y SHALL incluir el campo `incluye_distritos` en el resultado cuando el departamento filtrado absorba distritos.

#### Scenario: Valle del Cauca con distritos
- **WHEN** se invoca `count_ips` con departamento "Valle del Cauca"
- **THEN** el valor incluye las IPS de Cali y Buenaventura y el resultado indica `incluye_distritos` con esos dos distritos

#### Scenario: Departamento sin distritos
- **WHEN** se invoca `count_ips` con departamento "Antioquia"
- **THEN** el resultado no incluye el campo `incluye_distritos`

#### Scenario: Bogotá D.C.
- **WHEN** se invoca `count_ips` con departamento "Bogotá D.C"
- **THEN** el filtro se aplica sin mapeo adicional

### Requirement: Tools de conteo y suma
El sistema SHALL ofrecer `count_ips` que cuente `COUNT(DISTINCT codigo_prestador)`, `count_sedes` que cuente `COUNT(DISTINCT sede_id)`, donde `sede_id` es la columna derivada de `ips` definida en `data-ingestion` y `sum_capacidad` que sume `cantidad_capacidad` filtrando por `grupo_capacidad` y, opcionalmente, `descripcion_capacidad`, todas con filtros opcionales de departamento, municipio, naturaleza y nivel de atención.

#### Scenario: Conteo de IPS
- **WHEN** se invoca `count_ips` sin filtros
- **THEN** el valor es 9.320, el número de prestadores distintos, y no el de filas

#### Scenario: Conteo de sedes
- **WHEN** se invoca `count_sedes` sin filtros
- **THEN** el valor es 15.547

#### Scenario: Suma de capacidad
- **WHEN** se invoca `sum_capacidad` con `grupo_capacidad` "CAMAS" y `descripcion_capacidad` "Adultos"
- **THEN** el valor es la suma de `cantidad_capacidad` de esas filas

### Requirement: Resolución de la descripción de capacidad
El sistema SHALL resolver `descripcion_capacidad` contra la columna `descripcion_capacidad_norm` (sin tildes ni mayúsculas) priorizando la coincidencia exacta y luego la aproximada, SHALL devolver estado `ambiguo` con la lista de candidatos cuando haya varios plausibles, y SHALL devolver `no_encontrado` con hasta 3 sugerencias, nunca cero, cuando no coincida con ninguna.

#### Scenario: Coincidencia exacta
- **WHEN** se invoca `sum_capacidad` con grupo "CAMAS" y descripción "adultos"
- **THEN** resuelve la descripción "Adultos" y suma solo esas filas, sin incluir "Intensiva Adultos"

#### Scenario: Descripción coloquial sin coincidencia
- **WHEN** se invoca `sum_capacidad` con una descripción que no existe, como "camas para extraterrestres"
- **THEN** devuelve `no_encontrado` con hasta 3 descripciones similares y ningún valor numérico

#### Scenario: Varios candidatos
- **WHEN** la descripción coincide de forma aproximada con varias, como "cuidado intensivo" (que no es una descripción exacta); si la descripción coincide exactamente, como "cuidado intensivo adulto", se resuelve sin ambigüedad
- **THEN** devuelve `ambiguo` con los candidatos para que el agente pregunte cuál

### Requirement: Tools de ranking y agrupación
El sistema SHALL ofrecer `top_n` y `group_by` que agrupen por una dimensión permitida (departamento, municipio, naturaleza, nivel de atención o grupo de capacidad) con una métrica permitida (IPS distintas por `codigo_prestador`, sedes distintas por `sede_id` o suma de capacidad), con los mismos filtros opcionales y un máximo de 10 elementos.

#### Scenario: Ranking de departamentos
- **WHEN** se invoca `top_n` por departamento con métrica IPS distintas y n igual a 3
- **THEN** devuelve como máximo 3 elementos ordenados de mayor a menor

#### Scenario: Tope de elementos
- **WHEN** se solicita un n mayor que 10
- **THEN** la tool devuelve como máximo 10 elementos e indica que el resultado fue acotado

### Requirement: Búsqueda por nombre con desambiguación
El sistema SHALL ofrecer `buscar_ips` que busque por nombre de prestador o de sede de forma insensible a tildes y mayúsculas usando las columnas `*_norm` con coincidencia aproximada y, cuando haya más de un candidato plausible, SHALL devolver la lista de candidatos para desambiguar con el usuario.

#### Scenario: Coincidencia única
- **WHEN** se busca un nombre con un único candidato plausible
- **THEN** la tool devuelve esa IPS con su departamento, municipio y naturaleza

#### Scenario: Insensibilidad a tildes y mayúsculas
- **WHEN** se busca "CLINICA SANTA MARIA" y el dato está como "Clínica Santa María"
- **THEN** la búsqueda encuentra la IPS

#### Scenario: Varios candidatos
- **WHEN** el nombre coincide con varias IPS
- **THEN** la tool devuelve estado `ambiguo` y hasta 10 candidatos para que el agente pregunte cuál

#### Scenario: Sin coincidencias
- **WHEN** ningún nombre supera el umbral de similitud
- **THEN** la tool devuelve estado `sin_resultados` y no inventa candidatos

### Requirement: Formato común de resultado
El sistema SHALL devolver en cada resultado de tool los campos `valor`, `filtros` aplicados, `filas_usadas`, `fecha_corte`, `origen` y `estado` (`ok`, `sin_resultados`, `no_encontrado`, `ambiguo` o `sin_cobertura`), más `incluye_distritos` cuando aplique, y SHALL acotar las listas a 10 elementos.

#### Scenario: Resultado completo
- **WHEN** una tool finaliza con éxito
- **THEN** el JSON incluye valor, filtros, filas usadas, fecha de corte 2022-11-05 y origen (`api` o `snapshot`)

#### Scenario: Resultado compacto
- **WHEN** se serializa un resultado
- **THEN** el JSON no contiene campos vacíos ni columnas no solicitadas, como correos o teléfonos

### Requirement: Lugares inexistentes
El sistema SHALL devolver estado `no_encontrado` con hasta 3 sugerencias por similitud, y SHALL NOT devolver cero, cuando el departamento o el municipio filtrado no exista en los datos.

#### Scenario: Municipio inexistente
- **WHEN** se invoca `count_ips` con un municipio que no existe en el dataset
- **THEN** devuelve `no_encontrado` con hasta 3 municipios similares y ningún valor numérico

#### Scenario: Lugar existente sin resultados
- **WHEN** el municipio existe pero los demás filtros no dejan filas
- **THEN** devuelve `sin_resultados` con valor 0 y los filtros aplicados

### Requirement: Cobertura de nivel de atención
El sistema SHALL devolver estado `sin_cobertura` cuando se filtre por `nivel_atencion` junto con naturaleza privada o mixta, indicando que el dato casi no está registrado en la fuente, en vez de devolver cero.

#### Scenario: Nivel de IPS privadas
- **WHEN** se invoca `count_ips` con naturaleza "Privada" y nivel_atencion 1
- **THEN** devuelve estado `sin_cobertura` y el conteo observado (1 IPS) junto con la nota de cobertura

### Requirement: Presupuesto de llamadas y latencia de tools
El sistema SHALL permitir como máximo dos llamadas a tools por turno de usuario y cada ejecución de tool SHALL completarse en 200 ms o menos en el percentil 95 con los datos en memoria (meta inicial, a validar).

#### Scenario: Pregunta compuesta
- **WHEN** el modelo intenta una tercera llamada en el mismo turno
- **THEN** el servidor la rechaza con un resultado que pide responder con la evidencia disponible

#### Scenario: Meta de latencia
- **WHEN** se ejecutan las preguntas de oro 20 veces sobre el snapshot cargado
- **THEN** el p95 de duración de cada tool es 200 ms o menos
