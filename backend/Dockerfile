# Construir desde la raíz del repositorio:  docker build -f backend/Dockerfile -t kognia-backend .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/app ./app
# Snapshot precargado: el backend arranca sin depender de la API.
COPY data/snapshot.parquet data/snapshot.meta.json ./data/

ENV DATA_PATH=/app/data PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
