"""Refresco en segundo plano: descarga completa y swap atómico solo si el conteo coincide."""
from __future__ import annotations

import asyncio
import logging
import time

from app.datastore.store import Store
from app.ingestion.client import SodaAuthError, SodaClient

log = logging.getLogger(__name__)


async def refresh_once(store: Store, client: SodaClient) -> bool:
    """Devuelve True si reemplazó la tabla. Ante cualquier fallo conserva la vigente."""
    t0 = time.monotonic()
    try:
        rows, total = await client.fetch_all()
        # La construcción de la tabla es CPU/IO de DuckDB: fuera del event loop.
        await asyncio.to_thread(store.replace_from_rows, rows, total, "api")
    except SodaAuthError as e:
        log.error("Refresco omitido por error de autenticación: %s", e)
        return False
    except Exception as e:  # noqa: BLE001 - el refresco nunca debe tumbar el servicio
        log.error("Refresco fallido, se conserva la tabla vigente: %s", e)
        return False
    log.info("Refresco completado en %.1fs (%d filas)", time.monotonic() - t0, total)
    return True
