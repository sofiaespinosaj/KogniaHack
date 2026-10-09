## Context

El dataset `s2ru-bqt6` tiene 41.427 filas (9.320 IPS y 15.547 sedes distintas) y es la única fuente del agente. La API SODA3 limita cada llamada a 1.000 filas y exige token de aplicación. El agente solo puede responder con resultados de tools, así que los datos deben estar disponibles localmente y rápido (la evaluación es en vivo, 10 minutos). El backend es FastAPI con asyncio; los secretos viven solo en variables de entorno.

Hallazgos confirmados con `scripts/snapshot.py` contra la API real:
- Todas las columnas llegan como texto. SODA omite las claves con valor nulo, por lo que hay que unificar el conjunto de claves antes de cargar.
- Consulta y paginación: `POST` a `.../views/s2ru-bqt6/query.json` con cuerpo `{"query": "SELECT * ORDER BY :id", "page": {"pageNumber": N, "pageSize": 1000}}`. Las páginas empiezan en 1. El total se obtiene con `{"query": "SELECT count(*) AS n"}`. Cada fila trae `:id`, usado como clave estable.
- Autenticación solo con la cabecera `X-App-Token`.
- Descarga completa: 42 páginas en 126,6 s con concurrencia 4.
- Definición de sede, decidida con datos sobre el snapshot (claves distintas / claves con más de un `nombre_sede`): `codigo_sede` = 10.921 / 1.567 conflictos; `codigo_sede` + `numero_sede` = 15.547 / 0 conflictos; `codigo_prestador` + `numero_sede` = 15.534 / 12 conflictos. La clave correcta es `codigo_sede` + `numero_sede`, sin conflictos de nombre y sin cruzar prestadores. `codigo_sede` por sí solo agrupa varias sedes físicas.
- Snapshot Parquet (ZSTD): 2,0 MB. Todas las filas tienen `fecha_corte` 2022-11-05.

## Goals / Non-Goals

**Goals:**
- Arranque snapshot-first: dataset en DuckDB en 5 s o menos, sin depender de la API.
- Refresco en segundo plano desde la API con swap atómico solo si el conteo coincide.
- Perfil del dataset que declare grano, cobertura por columna y antigüedad de los datos.
- Fallo de arranque claro cuando falta configuración obligatoria.

**Non-Goals:**
- Tools del agente y prompt (cambio `grounded-agent`).
- Contrato de eventos WebSocket (cambio `realtime-voice`).
- Cualquier otra fuente de datos distinta del dataset `s2ru-bqt6`.

## Decisions

1. **Snapshot-first.** El arranque carga `data/snapshot.parquet` en DuckDB (estado `ready`) y no espera a la API. Una tarea en segundo plano descarga el dataset completo y, solo si el conteo coincide con el total reportado y la validación de IDs pasa, reemplaza la tabla `ips` mediante un swap atómico (se construye una tabla nueva y se renombra). Alternativa: cargar desde la API al arrancar y bloquear sesiones; descartada porque la descarga tarda 126,6 s, muy por encima de un arranque aceptable.
2. **Paginación confirmada.** `ORDER BY :id` con `pageNumber` desde 1 y `pageSize` 1000; descarga en paralelo con concurrencia 4 tras obtener el total con `count(*)`. Validación posterior: filas descargadas igual al total e IDs únicos y no nulos.
3. **Autenticación y errores.** Solo `X-App-Token`, leído de `SODA_APP_TOKEN`; nunca se imprime ni se registra. 401/403 no se reintentan; 429 respeta `Retry-After`; errores de red y 5xx se reintentan con backoff exponencial y jitter.
4. **Esquema normalizado en `ips`.** Todo llega como texto; la limpieza se hace en DuckDB al construir `ips`: alias legibles (`codigo_prestador`, `direccion`, `telefono`, etc.), `nivel_atencion` y `cantidad_capacidad` como enteros con `TRY_CAST`, `fecha_corte` como `DATE` (con `fecha_corte_texto` original conservado) y columnas `*_norm` en minúsculas y sin tildes para búsqueda. Alternativa: tipado en el cliente; descartada para mantener el cliente simple y la lógica en SQL.
5. **Grano explícito.** Una fila es la combinación sede × ítem de capacidad. IPS = `COUNT(DISTINCT codigo_prestador)` y sedes = `COUNT(DISTINCT sede_id)`, donde `sede_id` es una columna derivada de `ips` (`codigo_sede || '-' || numero_sede`) definida en un único punto del módulo `datastore`; todos los consumidores (perfil, tools, brief y verificaciones) usan `sede_id` y ninguno reconstruye la clave. Contar filas como IPS es un error que el perfil debe prevenir.
6. **Configuración validada al arrancar.** Las variables de entorno se leen una vez en un módulo de configuración; si falta una obligatoria, el proceso termina con un mensaje que nombra la variable y nunca imprime valores. `.env.example` documenta todas con placeholders. `.env` y `data/_raw.ndjson` se excluyen con `.gitignore`.

## Risks / Trade-offs

- [El snapshot queda desactualizado (corte 2022-11-05)] → El estado y la procedencia lo declaran y el agente cita la fecha; el refresco en segundo plano lo actualiza cuando la API responde.
- [Refresco con datos incompletos] → Swap atómico solo si el conteo coincide con el total reportado e IDs válidos; en otro caso se conserva la tabla actual.
- [API lenta, rate limit o token inválido] → Las sesiones no dependen de la API; 401/403 sin reintento y 429 con `Retry-After`; mensajes sin exponer el token.
- [Variable obligatoria ausente en producción] → Falla al arrancar con mensaje claro en vez de degradarse en silencio.

## Open Questions

- Variables obligatorias exactas al arrancar: `SODA_APP_TOKEN` es opcional si hay snapshot (solo se omite el refresco); el resto de claves (LLM, STT, TTS) se fijan en sus cambios (TBD).
- Frecuencia del refresco más allá del arranque (TBD).
