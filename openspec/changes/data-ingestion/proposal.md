## Why

El agente solo puede responder con evidencia de sus tools, y su única fuente es el dataset `s2ru-bqt6` de la API SODA3 (+41.000 filas, máximo 1.000 por llamada). Hoy no existe ningún mecanismo para traerlo, tenerlo disponible con baja latencia en la evaluación en vivo, ni describirlo para generar el brief inicial.

## What Changes

- Cliente SODA3 para `https://www.datos.gov.co/api/v3/views/s2ru-bqt6/query.json` con paginación (`pageSize` 1000) y token de aplicación leído de una variable de entorno.
- Arranque snapshot-first: el backend carga `data/snapshot.parquet` en DuckDB en 5 s o menos y refresca desde la API en segundo plano con swap atómico solo si el conteo coincide.
- Snapshot Parquet del dataset (41.427 filas) incluido en la imagen Docker; si la API falla, los datos siguen disponibles.
- Tabla `ips` normalizada (alias limpios, tipos, columnas `*_norm`).
- Configuración por variables de entorno con validación al arrancar y `.env.example`.
- Perfil del dataset (grano, conteos, cobertura, naturaleza, fecha de corte) como insumo para el brief del agente.

## Capabilities

### New Capabilities
- `soda-dataset-ingestion`: cliente SODA3 paginado, carga snapshot-first a DuckDB, refresco en segundo plano, tabla `ips` normalizada, procedencia y configuración validada.
- `dataset-profile`: perfil estructural y estadístico del dataset (grano, cobertura, distribución y antigüedad) para generar el brief.

### Modified Capabilities

(ninguna)

## Impact

- Código nuevo en el backend FastAPI (`ingestion`, `datastore`, `profile`, `config`); sin cambios en el frontend.
- Dependencias nuevas: cliente HTTP, DuckDB.
- Variables de entorno nuevas, solo en el backend: `SODA_APP_TOKEN`, `SODA_PAGE_SIZE`, `SODA_CONCURRENCY`, `SODA_MAX_TRIES`, `DATA_PATH`, `CORS_ORIGINS` y claves de LLM, STT y TTS.
- Consumido por `grounded-agent` (tools sobre DuckDB) y por `deployment-readme` (precarga al arrancar).
