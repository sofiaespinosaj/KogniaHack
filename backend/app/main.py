from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.agent.brief import BriefCache
from app.agent.tools import AgentTools
from app.config import Settings, load_settings_or_exit
from app.datastore.loader import startup_load
from app.datastore.store import Store
from app.ws.handler import ConnectionHandler

logging.basicConfig(level=logging.INFO)


def create_app(settings: Settings | None = None, *, backend_factory=None) -> FastAPI:
    settings = settings or load_settings_or_exit()
    store = Store()
    brief = BriefCache(store, AgentTools(store))

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
        return {"status": store.state, "voice": "enabled" if settings.voice_enabled else "disabled",
                "error": store.last_error, "data": asdict(store.provenance)}

    @app.get("/profile")
    def profile():
        if store.profile is None:
            return JSONResponse({"error": "datos no disponibles", "status": store.state}, status_code=503)
        return store.profile

    @app.get("/api/brief")
    def get_brief():
        if store.profile is None:
            return JSONResponse({"error": "datos no disponibles", "status": store.state}, status_code=503)
        return brief.get()

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        handler = ConnectionHandler(
            websocket, voice_enabled=settings.voice_enabled, backend_factory=backend_factory,
            brief_provider=brief.get, data_ready=lambda: store.profile is not None)
        try:
            while True:
                msg = await websocket.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg.get("bytes") is not None:
                    await handler.on_binary(msg["bytes"])
                elif msg.get("text") is not None:
                    await handler.on_text(msg["text"])
        except WebSocketDisconnect:
            pass
        finally:
            await handler.cleanup()

    return app


def __getattr__(name: str):  # `uvicorn app.main:app` crea la app (y valida la config) al importar
    if name == "app":
        return create_app()
    raise AttributeError(name)
