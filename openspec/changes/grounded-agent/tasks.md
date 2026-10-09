## 1. Tools de consulta

- [x] 1.1 Crear el módulo `agent/tools` con la ejecución parametrizada sobre DuckDB (sin SQL libre) y el objeto común de filtros (departamento, municipio, naturaleza, nivel_atencion)
- [x] 1.2 Generar los enums de `naturaleza`, `nivel_atencion`, `grupo_capacidad` y `departamento` (valores de `departamento_canonico`) desde el perfil de `data-ingestion`; prueba de que cambian al cambiar el perfil
- [x] 1.3 Implementar `count_ips` (`COUNT DISTINCT codigo_prestador`), `count_sedes` (`COUNT DISTINCT sede_id`) y `sum_capacidad`
- [x] 1.4 Implementar `top_n` y `group_by` con dimensiones y métricas permitidas y tope de 10 elementos
- [x] 1.5 Implementar `buscar_ips` sobre `nombre_prestador_norm` y `nombre_sede_norm` con coincidencia aproximada y lista de candidatos para desambiguar
- [x] 1.6 Implementar el envoltorio común de resultado (`valor`, `filtros`, `filas_usadas`, `fecha_corte`, `origen`, `estado`) en JSON compacto sin campos vacíos ni contactos
- [x] 1.7a Filtrar y agrupar por `departamento_canonico` e incluir `incluye_distritos` en el resultado cuando el departamento absorba distritos; prueba con Valle del Cauca y con Antioquia
- [x] 1.7b Resolver `descripcion_capacidad` contra `descripcion_capacidad_norm` (exacta, luego aproximada) con `ambiguo` y `no_encontrado` con hasta 3 sugerencias; pruebas con "adultos", "cuidado intensivo adulto" (exacta), "cuidado intensivo" (ambigua) y una descripción inexistente
- [x] 1.7 Implementar `no_encontrado` con hasta 3 sugerencias para departamento o municipio inexistente, y `sin_resultados` con valor 0 cuando el lugar existe
- [x] 1.8 Implementar `sin_cobertura` al filtrar por nivel de atención con naturaleza privada o mixta
- [x] 1.9 Rechazar argumentos fuera del esquema con error de validación compacto y limitar a dos llamadas a tools por turno

## 2. Integración con la sesión Realtime

- [ ] 2.1 Registrar las seis tools como function tools de la sesión Realtime y devolver cada resultado como salida de la función (el contrato de eventos se toma de `realtime-voice`)
- [x] 2.2 Leer `OPENAI_REALTIME_MODEL` y `OPENAI_API_KEY` del entorno y añadirlas a `.env.example` con `OPENAI_REALTIME_MODEL=gpt-realtime-mini` como valor provisional (si falla alguna pregunta de oro, se cambia la variable al modelo completo y se registra); fallar al arrancar con mensaje claro si falta la clave con el módulo habilitado
- [x] 2.3 Redactar las instrucciones de sesión concisas (grounding, honestidad, nivel de atención, cita del corte, conteo por prestadores, estilo hablado, contacto solo si se pide) sin cifras del dataset
- [x] 2.4 Medir la duración de cada tool sobre el snapshot cargado y registrar el p95 frente a la meta de 200 ms (p95 sobre el snapshot con 20 repeticiones: count_ips 7,4 ms; count_sedes 5,0 ms; sum_capacidad 12,6 ms; top_n 8,1 ms; group_by 7,5 ms; buscar_ips 25,4 ms; meta cumplida)

## 3. Brief de sesión

- [x] 3.1 Construir el brief determinista desde el perfil (alcance, antigüedad, grano y cobertura de `nivel_atencion`)
- [x] 3.2 Definir 3 a 5 preguntas sugeridas y validar que cada una se resuelve con una o dos llamadas a tools con estado `ok`
- [ ] 3.3 Emitir el brief como respuesta inicial de la sesión y entregar texto y preguntas como datos estructurados al cliente
- [x] 3.4 Reconstruir el brief tras cada refresco de datos; prueba de que el mismo perfil produce el mismo brief
- [x] 3.5 Medir que el brief hablado dura 20 s o menos (estimado por palabras, 20,0 s con cifras largas contadas como 4 palabras; la medición con audio real se hace en `realtime-voice`)

## 4. Preguntas de oro

Valores calculados por SQL sobre `data/snapshot.parquet` (corte 2022-11-05). Se regeneran con un script que ejecuta el SQL, y las respuestas habladas se comparan después de redondear.

Resumen:
- [x] 4.1 "¿Cuántas IPS hay en total?" → 9.320. SQL: `SELECT count(DISTINCT codigo_prestador) FROM ips`
- [x] 4.2 "¿Cuántas son públicas, privadas y mixtas?" → públicas 998, privadas 8.308, mixtas 14. SQL: `SELECT naturaleza, count(DISTINCT codigo_prestador) FROM ips GROUP BY 1`
- [x] 4.3 "¿Cuántas sedes hay?" → 15.547. SQL: `SELECT count(DISTINCT codigo_sede || '-' || numero_sede) FROM ips` (equivale a `sede_id`; `codigo_sede` solo daría 10.921 y mezcla sedes distintas)

Detalle fino:
- [x] 4.4 "¿Qué departamento tiene más IPS?" → Bogotá D.C con 1.270 (sin cambio al usar la columna canónica; el segundo es Antioquia con 837 y el tercero Valle del Cauca con 813). SQL: `SELECT departamento_canonico, count(DISTINCT codigo_prestador) n FROM ips GROUP BY 1 ORDER BY n DESC LIMIT 1`
- [x] 4.5 "¿Cuántas IPS hay en Medellín?" → 517. SQL: `SELECT count(DISTINCT codigo_prestador) FROM ips WHERE municipio_norm = 'medellin'`
- [x] 4.6 "¿Cuántas camas de adultos hay en Antioquia?" → 6.438. SQL: `SELECT sum(cantidad_capacidad) FROM ips WHERE grupo_capacidad = 'CAMAS' AND descripcion_capacidad = 'Adultos' AND departamento_norm = 'antioquia'`
- [x] 4.7 "¿Cuántas IPS son de nivel 3?" → 29, todas públicas. SQL: `SELECT count(DISTINCT codigo_prestador) FROM ips WHERE nivel_atencion = 3`
- [x] 4.7b "¿Cuántas IPS hay en el Valle del Cauca?" → 813, incluyendo Cali y Buenaventura (solo con el filtro literal de departamento darían 285). El agente puede mencionar que incluye esos distritos. SQL: `SELECT count(DISTINCT codigo_prestador) FROM ips WHERE departamento_canonico = 'Valle del Cauca'`
- [x] 4.7c "¿Cuántas camas para adultos hay?" (descripción coloquial) → 45.262, resuelta a la descripción "Adultos" del grupo CAMAS. SQL: `SELECT sum(cantidad_capacidad) FROM ips WHERE grupo_capacidad = 'CAMAS' AND descripcion_capacidad_norm = 'adultos'`
- [x] 4.8 "¿Cuántas IPS privadas son de nivel 1?" → el agente dice que el dato casi no está registrado para privadas (solo 1 registrada) y no responde cero. SQL: `SELECT count(DISTINCT codigo_prestador) FROM ips WHERE naturaleza = 'Privada' AND nivel_atencion IS NOT NULL`

Fuera de la fuente y casos límite:
- [x] 4.9 "¿Cuál es la mejor clínica de Bogotá?" → el agente dice que el dataset no tiene calidad ni calificaciones y ofrece alternativas
- [x] 4.10 "¿Cuántos médicos trabajan en las IPS?" → el agente dice que el dataset registra capacidad instalada, no personal
- [x] 4.11 "¿Cuántas IPS hay en Springfield?" → `no_encontrado`; el agente pide aclaración y no responde cero
- [x] 4.12 Una pregunta con nombre ambiguo de IPS → el agente lista candidatos y pregunta cuál
- [x] 4.12b "¿Cuántas camas para extraterrestres hay?" → `no_encontrado`; el agente ofrece descripciones similares y no responde cero

Criterio:
- [x] 4.13 Script de evaluación que ejecuta el SQL de oro y compara con la respuesta del agente, enviando las preguntas en texto contra la misma sesión y las mismas tools; criterio de aceptación de 100 % de coincidencia en las preguntas con cifra (4.1 a 4.7c) y comportamiento esperado en las de honestidad (4.8 a 4.12b). La prueba por voz de las mismas preguntas se hace en `realtime-voice` (implementado en `app/agent/gold.py` y `text_agent.py`; modo tools ejecutado: 15/15 coinciden con el SQL; el modo `--agent` está probado con transporte simulado y pendiente de ejecutar con el modelo)

## 5. Verificación

- [x] 5.1 Pruebas unitarias de cada tool con casos felices, enums inválidos, lugares inexistentes y tope de 10 elementos
- [ ] 5.2 Confirmar que ninguna respuesta del agente en las preguntas de oro contiene cifras que no vengan de un resultado de tool (el verificador `ungrounded_numbers` está implementado y probado; falta ejecutarlo con el modelo: `python -m app.agent.gold --agent`)
- [x] 5.3 Confirmar que la clave de OpenAI no aparece en logs, respuestas ni repositorio
