from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import Settings, load_settings_or_exit
from app.datastore.loader import startup_load
from app.datastore.store import Store

logging.basicConfig(level=logging.INFO)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings_or_exit()
    store = Store()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # No se espera: el servidor acepta sesiones mientras los datos cargan.
        task = asyncio.create_task(startup_load(store, settings))
        yield
        task.cancel()

    app = FastAPI(title="Kognia backend", lifespan=lifespan)
    app.state.store, app.state.settings = store, settings
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins),
                           allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    def health() -> dict:
        return {"status": store.state, "error": store.last_error, "data": asdict(store.provenance)}

    @app.get("/profile")
    def profile():
        if store.profile is None:
            return JSONResponse({"error": "datos no disponibles", "status": store.state}, status_code=503)
        return store.profile

    return app


def __getattr__(name: str):  # `uvicorn app.main:app` crea la app (y valida la config) al importar
    if name == "app":
        return create_app()
    raise AttributeError(name)
