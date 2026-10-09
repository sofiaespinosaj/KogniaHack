"""Arranque snapshot-first: carga el Parquet sin esperar a la API."""
from __future__ import annotations

import json
import logging

from app.config import Settings
from app.datastore.store import Store
from app.ingestion.client import SodaClient
from app.ingestion.refresh import refresh_once

log = logging.getLogger(__name__)


def load_snapshot(store: Store, settings: Settings) -> bool:
    """Carga data/snapshot.parquet. Devuelve False si falta o no se puede leer.

    Si el conteo no coincide con snapshot.meta.json, los datos quedan servibles
    pero el estado pasa a `degraded`.
    """
    path = settings.snapshot_path
    if not path.is_file():
        store.last_error = "snapshot ausente"
        log.warning("Snapshot ausente en %s", path.resolve())
        return False
    meta: dict = {}
    try:
        if settings.snapshot_meta_path.is_file():
            meta = json.loads(settings.snapshot_meta_path.read_text(encoding="utf-8"))
        stats = meta.get("stats", {})
        failures = {"cantidad_capacidad": stats.get("cantidad_no_convertible", 0),
                    "fecha_corte": stats.get("fecha_corte_no_parseada", 0)}
        store.load_parquet(path, failures, source="snapshot")
    except Exception as e:  # noqa: BLE001 - archivo corrupto o ilegible
        store._drop("ips_new")
        store.last_error = "snapshot ilegible"
        log.error("Snapshot ilegible: %s", type(e).__name__)
        return False
    expected = meta.get("rows")
    if expected is not None and store.provenance.rows != expected:
        store.state = "degraded"
        store.last_error = f"conteo {store.provenance.rows} distinto de snapshot.meta.json ({expected})"
        log.error("Snapshot inconsistente: %s", store.last_error)
    return True


async def startup_load(store: Store, settings: Settings) -> None:
    """Carga inicial y, si procede, refresco en segundo plano.

    Las sesiones no esperan a la API: con snapshot, `ready` ocurre tras leer el Parquet.
    """
    import asyncio

    ok = await asyncio.to_thread(load_snapshot, store, settings)
    client = SodaClient(settings) if settings.soda_app_token else None
    try:
        if ok:
            if client is None:
                store.provenance.refresh_skipped_reason = "SODA_APP_TOKEN no definido"
                log.warning("Refresco omitido: SODA_APP_TOKEN no definido")
            else:
                await refresh_once(store, client)
        else:
            if client is None:
                store.state = "unavailable"
                store.last_error = "sin snapshot y sin SODA_APP_TOKEN para descargar"
            elif not await refresh_once(store, client):
                store.state = "unavailable"
                store.last_error = "sin snapshot y la descarga desde la API falló"
    finally:
        if client:
            await client.aclose()
