# Construir desde la raíz del repositorio:  docker build -f backend/Dockerfile -t lumi-backend .
FROM python:3.12-slim

RUN pip install --no-cache-dir uv==0.11.32
WORKDIR /app

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/app ./app
# Snapshot precargado: el backend arranca sin depender de la API SODA3.
COPY data/snapshot.parquet data/snapshot.meta.json ./data/

RUN useradd --create-home --uid 10001 lumi && chown -R lumi /app
USER lumi

ENV DATA_PATH=/app/data PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
EXPOSE 8000
# Detrás del proxy de la plataforma: confía en X-Forwarded-* para el esquema y la IP del cliente.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
