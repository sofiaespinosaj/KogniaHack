## 1. Configuración base

- [x] 1.1 Crear el módulo `ingestion` del backend y el módulo de configuración por variables de entorno
- [x] 1.2 Añadir dependencias (cliente HTTP, DuckDB) y verificar que el entorno instala limpio
- [x] 1.3 Inspeccionar la API con el token y documentar esquema, cuerpo de consulta y paginación en `design.md`
- [x] 1.4 Crear `.env.example` con `SODA_APP_TOKEN`, `SODA_PAGE_SIZE`, `SODA_CONCURRENCY`, `SODA_MAX_TRIES`, `DATA_PATH`, `CORS_ORIGINS` y placeholders de las claves de los módulos de voz (`OPENAI_API_KEY`, `OPENAI_REALTIME_MODEL`, `DEEPGRAM_API_KEY`)
- [x] 1.5 Confirmar que `.gitignore` excluye `.env` y `data/_raw.ndjson` (hoy no existe `.gitignore`; crearlo)
- [x] 1.6 Fallar al arrancar con un mensaje claro que nombre la variable obligatoria ausente, sin imprimir valores; prueba con variable ausente

## 2. Cliente SODA3 y refresco

- [ ] 2.1 Implementar el cliente SODA3 con `X-App-Token` desde el entorno y sin exponer el token en logs
- [ ] 2.2 Implementar la paginación con `ORDER BY :id`, `pageNumber` desde 1 y `pageSize` 1000; prueba que valida conteo igual al total e IDs únicos
- [ ] 2.3 Implementar el manejo de errores: sin reintento en 401/403, `Retry-After` en 429 y backoff en red/5xx; pruebas con respuestas simuladas
- [ ] 2.4 Implementar el refresco en segundo plano con swap atómico solo si el conteo coincide; prueba con descarga incompleta que conserva la tabla vigente
- [ ] 2.5 Medir el refresco completo y registrar el resultado frente a la meta de 180 s

## 3. Snapshot-first y procedencia

- [x] 3.1 Generar el snapshot Parquet y `snapshot.meta.json` (`scripts/snapshot.py`: 41.427 filas, 2,0 MB)
- [ ] 3.2 Cargar `data/snapshot.parquet` en DuckDB al arrancar sin bloquear sesiones; medir que `ready` ocurre en 5 s o menos; el swap atómico del refresco usa una conexión compartida con un cursor por petición y una transacción (crear `ips_new` y renombrar)
- [ ] 3.3 Construir la tabla `ips` con alias limpios, enteros, fecha y columnas `*_norm`; prueba de tipos y normalización
- [ ] 3.4 Manejar snapshot ausente o ilegible (descarga completa o estado `unavailable` en `/health`)
- [ ] 3.5 Exponer los metadatos de procedencia (dataset, fecha de carga, origen, filas, `fecha_corte`)
- [ ] 3.6 Incluir `data/snapshot.parquet` y `data/snapshot.meta.json` en la imagen Docker del backend
- [ ] 3.7 Verificar que el snapshot cargado cumple 41.427 filas y 10.921 sedes distintas, y que un conteo inconsistente deja el estado `degraded`
- [ ] 3.8 Crear la columna `departamento_canonico` con el mapeo fijo de distritos (Cali y Buenaventura a Valle del Cauca, Barranquilla a Atlántico, Cartagena a Bolívar, Santa Marta a Magdalena; Bogotá D.C. sin cambio); prueba de que todas las filas quedan mapeadas, que hay 33 valores y que Valle del Cauca suma 813 IPS distintas

## 4. Perfil de datos

- [ ] 4.1 Calcular el perfil una sola vez por carga o refresco: columnas, tipos, nulos, categorías principales
- [ ] 4.2 Incluir el grano (sede × ítem de capacidad) y las definiciones de IPS y sedes distintas
- [ ] 4.3 Incluir la cobertura por columna (`nivel_atencion` nulo en 25.266 filas, 61 %; prácticamente exclusivo de IPS públicas: 16.160 filas públicas con nivel y 1 privada con nivel 1), la distribución de naturaleza y la fecha de corte
- [ ] 4.4 Exponer el perfil como estructura serializable; prueba de consulta en menos de 50 ms

## 5. Verificación

- [x] 5.1 Confirmar con una consulta la cobertura de `nivel_atencion`: 25.266 filas nulas (61 %), 16.160 filas públicas con nivel y 1 fila privada con nivel 1
- [ ] 5.2 Confirmar que ningún secreto aparece en logs ni en el repositorio
