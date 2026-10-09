"""Mide un refresco completo contra la API real (meta: <= 180 s).

Uso (desde backend/):  SODA_APP_TOKEN=... uv run python scripts/measure_refresh.py
El token se lee solo del entorno y nunca se imprime.
"""
import asyncio
import sys
import time

from app.config import load_settings_or_exit
from app.datastore.store import Store
from app.ingestion.client import SodaClient
from app.ingestion.refresh import refresh_once

GOAL_S = 180


async def main() -> int:
    settings = load_settings_or_exit()
    if not settings.soda_app_token:
        print("Falta la variable de entorno SODA_APP_TOKEN", file=sys.stderr)
        return 2
    store, client = Store(), SodaClient(settings)
    t0 = time.monotonic()
    ok = await refresh_once(store, client)
    elapsed = time.monotonic() - t0
    await client.aclose()
    print(f"ok={ok} filas={store.provenance.rows} concurrencia={settings.soda_concurrency} "
          f"tiempo={elapsed:.1f}s meta={GOAL_S}s cumple={ok and elapsed <= GOAL_S}")
    return 0 if ok and elapsed <= GOAL_S else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
