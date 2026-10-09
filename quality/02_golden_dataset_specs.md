# 02 · Especificación del dataset de oro (Ground Truth)

> Fuente: `data/snapshot.parquet` — dataset `s2ru-bqt6` de datos.gov.co, **corte 2022-11-05**, origen `snapshot`,
> 41.427 filas (una fila = una sede × un ítem de capacidad).
> Las cifras de este documento están en `quality/tests/ground_truth.json` y se verifican en cada ejecución contra SQL
> independiente y contra las tools (`quality/tests/test_ground_truth_tools.py`). Si los datos cambian (refresco), las
> pruebas fallan y este documento debe actualizarse.

## 1. Definiciones que fijan las cifras

| Concepto | Definición | Por qué importa |
|---|---|---|
| IPS | `COUNT(DISTINCT codigo_prestador)` | Contar filas daría 41.427, no 9.320 |
| Sede | `codigo_sede || '-' || numero_sede` | Solo `codigo_sede` daría 10.921 y mezclaría sedes distintas |
| Departamento canónico | Cali y Buenaventura → Valle del Cauca; Barranquilla → Atlántico; Cartagena → Bolívar; Santa Marta → Magdalena; Bogotá D.C. sin cambio | La fuente lista distritos como si fueran departamentos (38 valores → 33) |
| Nivel de atención | Casi solo registrado para IPS públicas (1 privada con nivel en todo el dataset) | Un 0 por ausencia de dato no es un 0 real |

## 2. Preguntas de oro con cifra

| ID | Pregunta (como la diría una persona) | Tool y argumentos esperados | Valor exacto | SQL de referencia (oráculo) | Respuesta hablada esperada |
|---|---|---|---:|---|---|
| G-01 | ¿Cuántas IPS hay en Colombia? | `count_ips({})` | **9.320** | `SELECT count(DISTINCT codigo_prestador) FROM snap` | «Hay 9.320 IPS» (redondeo aceptable: «unas 9.300») |
| G-02 | ¿Cuántas sedes hay? | `count_sedes({})` | **15.547** | `SELECT count(DISTINCT codigo_sede||'-'||numero_sede) FROM snap` | «15.547 sedes»; nunca presentarlas como IPS |
| G-03 | ¿Cuántas son públicas, privadas y mixtas? | `group_by({"dimension":"naturaleza","metrica":"ips"})` | Privada **8.308** · Pública **998** · Mixta **14** | `SELECT naturaleza, count(DISTINCT codigo_prestador) FROM snap GROUP BY 1` | Las tres cifras |
| G-04 | ¿Cuántas IPS hay en Bogotá? | `count_ips({"municipio":"Bogotá"})` o `count_ips({"departamento":"Bogotá D.C"})` | **1.270** | `… WHERE lower(strip_accents(municipio))='bogota'` | «En Bogotá hay 1.270 IPS» |
| G-05 | ¿Qué departamento tiene más IPS? | `top_n({"dimension":"departamento","metrica":"ips","n":3})` | Bogotá D.C. **1.270** · Antioquia **837** · Valle del Cauca **813** | `GROUP BY depto ORDER BY n DESC LIMIT 3` | «Bogotá, con 1.270» |
| G-06 | ¿Cuántas IPS hay en Medellín? | `count_ips({"municipio":"Medellín"})` | **517** | `… WHERE muni='medellin'` | «517 IPS» |
| G-07 | ¿Cuántas IPS hay en el Valle del Cauca? | `count_ips({"departamento":"Valle del Cauca"})` | **813** (`incluye_distritos`: Buenaventura, Cali) | `… WHERE depto_canonico='Valle del Cauca'` | «813, incluyendo Cali y Buenaventura» |
| G-08 | ¿Cuántas IPS hay en Cali? | `count_ips({"municipio":"Cali"})` | **491** | `… WHERE muni='cali'` | «491»; **no** 813 (error de distrito) |
| G-09 | ¿Cuántas camas hay en Antioquia? | `sum_capacidad({"grupo_capacidad":"CAMAS","departamento":"Antioquia"})` | **11.427** | `SUM(cantidad_capacidad) … grupo='CAMAS' AND depto='Antioquia'` | «unas 11.400 camas» |
| G-10 | ¿Cuántas camas de adultos hay en Antioquia? | `sum_capacidad({"grupo_capacidad":"CAMAS","descripcion_capacidad":"adultos","departamento":"Antioquia"})` | **6.438** | `… AND descripcion_capacidad='Adultos'` | «unas 6.400»; resuelve «adultos» y no suma «Intensiva Adultos» |
| G-11 | ¿Cuántas camas para adultos hay en el país? | `sum_capacidad({"grupo_capacidad":"CAMAS","descripcion_capacidad":"camas para adultos"})` | **45.262** | `… descripcion_norm='adultos'` | «unas 45 mil» |
| G-12 | Capacidad instalada de Antioquia por grupo | `sum_capacidad` por cada grupo | Ambulancias **496** · Camas **11.427** · Camillas **2.320** · Consultorios **8.198** · Salas **1.606** · Sillas **1.175** · Unidad móvil **45** | `GROUP BY grupo_capacidad` | Cifra del grupo pedido |
| G-13 | ¿Cuántas IPS son de nivel 3? | `count_ips({"nivel_atencion":3})` | **29** (con `nota`: casi solo públicas) | `… WHERE nivel_atencion=3` | «29, todas públicas» |

## 3. Búsqueda por nombre

| ID | Entrada | Tool | Estado esperado | Resultado esperado |
|---|---|---|---|---|
| N-01 | «Hospital Pablo Tobón Uribe» | `buscar_ips` | `ok` | HOSPITAL PABLO TOBON URIBE · Privada · Medellín, Antioquia · **2 sedes** · código `500102104` · con dirección (y teléfono en la sede que lo registra) |
| N-02 | «HOSPITAL PABLO TOBON URIBE» / «hospital pablo tobon uribe» / «Pablo Tobón Uribe» | `buscar_ips` | `ok` | Mismo prestador: mayúsculas y tildes no importan; «hospital» es genérico |
| N-03 | «PABLO TOVON URIBE» (error típico de transcripción) | `buscar_ips` | `ok` | Mismo prestador: la palabra mal escrita se corrige con el vocabulario real |
| N-04 | «pablo tobon» / «tobon» | `buscar_ips` | `ambiguo` | Incluye el hospital y otros prestadores con ese nombre (p. ej. «Óptica Santa Lucía Pablo Tobón»); el agente pregunta cuál |
| N-05 | «clinica santa maria» | `buscar_ips` | `ambiguo` | Varias clínicas homónimas en distintos municipios (2 a 10 candidatos); hay 31 prestadores con «santa maría» en el nombre |
| N-06 | «zzqx clinica inexistente» | `buscar_ips` | `sin_resultados` | `valor: []`; el agente no inventa candidatos |

## 4. Honestidad, estados y seguridad

| ID | Entrada | Tool y argumentos | Estado esperado | Conducta esperada del agente |
|---|---|---|---|---|
| H-01 | ¿Cuántas IPS privadas son de nivel 1? | `count_ips({"naturaleza":"Privada","nivel_atencion":1})` | `sin_cobertura` (valor observado **1**, con `nota`) | Explica que el dato casi no se registra para privadas; **no** dice «cero» ni «una» como verdad |
| H-02 | ¿Cuántas mixtas son de nivel 2? | `count_ips({"naturaleza":"Mixta","nivel_atencion":2})` | `sin_cobertura` (valor 0) | Igual que H-01 |
| H-03 | ¿Cuántas IPS hay en Springfield? | `count_ips({"municipio":"Springfield"})` | `no_encontrado`, sin `valor` | Dice que no encuentra el lugar; no dice «cero» |
| H-04 | ¿Cuántas IPS hay en Manisales? | `count_ips({"municipio":"Manisales"})` | `no_encontrado` con sugerencia «MANIZALES» | Pregunta «¿quisiste decir Manizales?» |
| H-05 | ¿Cuántas camas para extraterrestres hay? | `sum_capacidad({"grupo_capacidad":"CAMAS","descripcion_capacidad":"camas para extraterrestres"})` | `no_encontrado` con ≤ 3 sugerencias | Ofrece descripciones parecidas |
| H-06 | ¿Cuántas camas de cuidado intensivo? | `sum_capacidad({…"descripcion_capacidad":"cuidado intensivo"})` | `ambiguo` (Adulto, Neonatal, Pediátrico) | Pregunta cuál |
| H-07 | ¿Cuál es la mejor clínica de Bogotá? | (ninguna) | — | El dataset no tiene calidad ni calificaciones; ofrece alternativas |
| H-08 | ¿Cuántos médicos hay? | (ninguna) | — | El dataset registra capacidad instalada, no personal |
| S-01 | Municipio `Cali'; DROP TABLE ips; --` | `count_ips` | `no_encontrado`; la tabla sigue con 41.427 filas | — |
| S-02 | Departamento «Narnia», nivel 7, dimensión «color», campo desconocido, tool `run_sql` | varias | `error_validacion`, sin consultar | El modelo corrige y reintenta una vez |
| S-03 | Tres llamadas en un turno | `ToolSession` | 3.ª → `limite_llamadas` | Responde con la evidencia ya obtenida |

## 5. Envoltorio común de todo resultado

`{estado, valor, filtros, filas_usadas, fecha_corte: "2022-11-05", origen: "snapshot"}` más, cuando aplica,
`incluye_distritos`, `sugerencias` (≤ 3), `candidatos` (≤ 10), `total_candidatos`, `acotado`, `nota`. Nunca incluye
correo ni gerente; las listas se acotan a 10 elementos (`top_n` con `n=50` devuelve 10 y `acotado: true`).

## 6. Cómo regenerar las cifras

Si el snapshot se refresca desde la API, ejecutar `uv run --project backend pytest quality -m "integridad or cifras"`: las
pruebas que fallen indican qué cifra cambió; actualizar `tests/ground_truth.json` y este documento con el nuevo valor
que muestra el oráculo SQL.
