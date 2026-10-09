from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from dataclasses import asdict

import anyio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.agent.brief import BriefCache
from app.agent.tools import AgentTools
from app.config import Settings, load_settings_or_exit
from app.datastore.loader import startup_load
from app.datastore.store import Store
from app.voice.cascade import CascadeVoice
from app.voice.relay import RealtimeRelay
from app.ws.handler import ConnectionHandler
from app.ws.limits import SessionLimiter, client_ip, origin_allowed, origin_regex

log = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)


def create_app(settings: Settings | None = None, *, backend_factory=None) -> FastAPI:
    settings = settings or load_settings_or_exit()
    store = Store()
    tools = AgentTools(store)
    brief = BriefCache(store, tools)
    limiter = SessionLimiter(settings.limits.max_sessions, settings.limits.sessions_per_minute)
    if backend_factory is None and settings.voice_enabled:
        def backend_factory():
            if settings.voice_provider == "groq":
                return CascadeVoice(settings, tools)
            return RealtimeRelay(settings, tools)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # No se espera: el servidor acepta sesiones mientras los datos cargan.
        task = asyncio.create_task(startup_load(store, settings))
        yield
        task.cancel()

    app = FastAPI(title="Kognia backend", lifespan=lifespan)
    app.state.store, app.state.settings = store, settings
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=[o for o in settings.cors_origins if "*" not in o],
                           allow_origin_regex=origin_regex(settings.cors_origins),
                           allow_methods=["*"], allow_headers=["*"])

    @app.get("/health")
    def health() -> dict:
        return {"status": store.state, "voice": "enabled" if settings.voice_enabled else "disabled",
                "voice_provider": settings.voice_provider if settings.voice_enabled else None,
                # presencia de las claves (nunca sus valores), para el checklist previo a la demo
                "voice_keys": {"groq": bool(settings.groq_api_key), "deepgram": bool(settings.deepgram_api_key),
                               "openai": bool(settings.openai_api_key)},
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
        origin = websocket.headers.get("origin")
        if not origin_allowed(origin, settings.cors_origins):
            log.warning("Origen rechazado en /ws: %s", origin[:100])
            await websocket.close(code=1008)      # antes de aceptar: el handshake responde HTTP 403
            return
        await websocket.accept()
        handler = ConnectionHandler(
            websocket, voice_enabled=settings.voice_enabled, backend_factory=backend_factory,
            brief_provider=brief.get, data_ready=lambda: store.profile is not None,
            limiter=limiter, limits=settings.limits, client_ip=client_ip(websocket))
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
            with anyio.CancelScope(shield=True):  # libera OpenAI y Deepgram aunque la tarea se cancele
                await handler.cleanup()

    return app


def __getattr__(name: str):  # `uvicorn app.main:app` crea la app (y valida la config) al importar
    if name == "app":
        app = create_app()
        globals()["app"] = app                    # uvicorn lee el atributo más de una vez: una sola app
        return app
    raise AttributeError(name)
