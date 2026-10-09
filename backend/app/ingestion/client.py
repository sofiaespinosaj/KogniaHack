"""Cliente SODA3 (datos.gov.co) con paginación, reintentos y token solo por cabecera."""
from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable

import httpx

from app.config import SODA_URL, Settings

log = logging.getLogger(__name__)

Sleep = Callable[[float], Awaitable[None]]


class SodaAuthError(RuntimeError):
    """401/403: token inválido o sin permisos. No se reintenta."""


class SodaError(RuntimeError):
    """Fallo de la API tras agotar reintentos, o descarga inválida."""


class SodaClient:
    def __init__(self, settings: Settings, *, transport: httpx.AsyncBaseTransport | None = None,
                 sleep: Sleep = asyncio.sleep, url: str = SODA_URL) -> None:
        self._s = settings
        self._url = url
        self._sleep = sleep
        headers = {"Content-Type": "application/json"}
        if settings.soda_app_token:
            headers["X-App-Token"] = settings.soda_app_token
        self._http = httpx.AsyncClient(headers=headers, timeout=30.0, transport=transport)

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _post(self, body: dict) -> list[dict]:
        """POST con reintentos. Los mensajes de error nunca incluyen el token."""
        last = "desconocido"
        for attempt in range(self._s.soda_max_tries):
            wait = 2 ** attempt + random.random()
            try:
                r = await self._http.post(self._url, json=body)
            except httpx.TransportError as e:
                last = type(e).__name__
            else:
                if r.status_code in (401, 403):
                    raise SodaAuthError(f"HTTP {r.status_code}: token inválido o sin permisos")
                if r.status_code == 200:
                    try:
                        return r.json()
                    except ValueError:
                        last = "JSONDecodeError"
                elif r.status_code == 429:
                    last = "HTTP 429"
                    try:
                        wait = float(r.headers.get("Retry-After", wait))
                    except ValueError:
                        pass
                elif r.status_code >= 500:
                    last = f"HTTP {r.status_code}"
                else:
                    raise SodaError(f"HTTP {r.status_code} no reintentable")
            if attempt + 1 < self._s.soda_max_tries:
                log.warning("SODA reintento %d/%d (%s); espero %.1fs",
                            attempt + 1, self._s.soda_max_tries, last, wait)
                await self._sleep(wait)
        raise SodaError(f"API no disponible tras {self._s.soda_max_tries} intentos ({last})")

    async def total(self) -> int:
        return int((await self._post({"query": "SELECT count(*) AS n"}))[0]["n"])

    async def _page(self, number: int) -> list[dict]:
        return await self._post({"query": "SELECT * ORDER BY :id",
                                 "page": {"pageNumber": number, "pageSize": self._s.soda_page_size}})

    async def fetch_all(self) -> tuple[list[dict], int]:
        """Descarga completa y validada: filas == total e `:id` únicos y no nulos."""
        total = await self.total()
        pages = -(-total // self._s.soda_page_size)
        sem = asyncio.Semaphore(self._s.soda_concurrency)

        async def one(p: int) -> list[dict]:
            async with sem:
                return await self._page(p)

        chunks = await asyncio.gather(*(one(p) for p in range(1, pages + 1)))
        rows = [r for c in chunks for r in c]
        validate_download(rows, total)
        return rows, total


def validate_download(rows: list[dict], total: int) -> None:
    if len(rows) != total:
        raise SodaError(f"Descarga incompleta: {len(rows)} de {total} filas")
    ids = {r.get(":id") for r in rows}
    if None in ids or len(ids) != total:
        raise SodaError(f"IDs duplicados o nulos: {len(ids)} únicos de {total}")
