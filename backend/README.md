# Backend

FastAPI (Python 3.12) que carga el dataset `s2ru-bqt6` (IPS de Colombia, datos.gov.co) en DuckDB y
lo expone al agente. Los datos salen de `data/snapshot.parquet` al arrancar y se refrescan en segundo
plano desde la API SODA3 si hay token.

## Ejecutar

```bash
cd backend
uv sync
cp .env.example .env        # completa los valores; .env no se versiona
uv run uvicorn app.main:app --port 8000
uv run pytest
```

## Configuración (variables de entorno)

| Variable | Por defecto | Notas |
|---|---|---|
| `SODA_APP_TOKEN` | — | Opcional si hay snapshot: sin él se omite el refresco. |
| `SODA_PAGE_SIZE` / `SODA_CONCURRENCY` / `SODA_MAX_TRIES` | 1000 / 4 / 5 | Descarga paginada desde SODA3. |
| `DATA_PATH` | `data` | Carpeta con `snapshot.parquet` y `snapshot.meta.json`. |
| `CORS_ORIGINS` | vacío | Orígenes permitidos, separados por comas. En desarrollo: `http://localhost:5173`. |
| `VOICE_ENABLED` | `false` | Con `true`, `OPENAI_API_KEY` y `DEEPGRAM_API_KEY` son obligatorias. |
| `OPENAI_REALTIME_MODEL` | `gpt-realtime-mini` | |

Si falta una variable obligatoria el proceso termina nombrándola, sin imprimir valores.

## Endpoints

Todos devuelven JSON. `/profile` y `/api/brief` responden `503` con `{"error", "status"}` mientras no
haya datos cargados.

### `GET /health`

| Campo | Descripción |
|---|---|
| `status` | `loading`, `ready`, `degraded` (datos servibles pero el conteo no coincide con `snapshot.meta.json`) o `unavailable` (sin snapshot y sin descarga posible). |
| `error` | Motivo legible del último problema, o `null`. Nunca contiene secretos. |
| `data.dataset` | Identificador del dataset (`s2ru-bqt6`). |
| `data.source` | Origen de los datos cargados: `snapshot` o `api`. |
| `data.loaded_at` | Fecha y hora de carga (UTC, ISO 8601). |
| `data.rows` | Filas de la tabla `ips` (una fila es una sede × ítem de capacidad). |
| `data.fecha_corte` | Fecha de corte de los datos (`2022-11-05` en el snapshot actual). |
| `data.refresh_skipped_reason` | Por qué no hay refresco (p. ej. falta `SODA_APP_TOKEN`), o `null`. |
| `data.conversion_failures` | Valores no convertibles por columna tipada (quedan nulos). |

### `GET /profile`

Perfil calculado una vez por carga o refresco y servido desde memoria.

| Campo | Descripción |
|---|---|
| `grain` | Qué representa una fila. |
| `definitions` | Cómo se cuentan `ips` (`COUNT(DISTINCT codigo_prestador)`) y `sedes` (`COUNT(DISTINCT sede_id)`). |
| `counting_guidance` | Aviso: las IPS se cuentan como prestadores distintos, nunca filas. |
| `rows`, `ips_distintas`, `sedes_distintas` | Conteos totales. |
| `columns[]` | Por columna: `name`, `type`, `nulls`, `null_pct`, `distinct` y, salvo identificadores, contactos y `*_norm`: `values` (`[{value, count}]`) y `values_complete`. Con 50 distintos o menos `values` trae todos los valores (`values_complete: true`); con más, solo los 10 principales (`false`). |
| `coverage.nivel_atencion` | `null_rows`, `null_pct`, `rows_with_level_publica`, `rows_with_level_privada`. |
| `coverage.notes[]` | Limitaciones de cobertura en texto. |
| `naturaleza` | Filas por naturaleza jurídica. |
| `fecha_corte`, `source` | Fecha de corte y origen (`api` o `snapshot`). |

### `GET /api/brief`

Brief inicial de la sesión, determinista: el mismo perfil produce el mismo brief y se reconstruye tras
cada refresco. Las preguntas se validan ejecutándolas contra las tools.

| Campo | Descripción |
|---|---|
| `texto` | Texto del brief (hablado, de unos 20 s): alcance, cifras, corte, grano y cobertura. |
| `preguntas` | De 3 a 5 preguntas sugeridas, todas respondibles con las tools. |
| `fecha_corte` | Fecha de corte de los datos. |
| `origen` | `snapshot` o `api`. |

## CORS

`CORS_ORIGINS` define los orígenes permitidos; otros orígenes no reciben cabeceras CORS. Para desarrollo
con Vite use `CORS_ORIGINS=http://localhost:5173` (ya es el valor de `.env.example`).
