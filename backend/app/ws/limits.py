"""Protección del WebSocket público: orígenes permitidos, sesiones simultáneas y sesiones nuevas por IP."""
from __future__ import annotations

import re
import time
from collections import defaultdict, deque

from starlette.requests import HTTPConnection


def origin_regex(origins: tuple[str, ...]) -> str | None:
    """Patrones con `*` (p. ej. `https://*.vercel.app`) para las vistas previas de Vercel."""
    pats = [re.escape(o).replace(r"\*", r"[a-z0-9-]+") for o in origins if "*" in o]
    return "^(" + "|".join(pats) + ")$" if pats else None


def origin_allowed(origin: str | None, origins: tuple[str, ...]) -> bool:
    """Sin `Origin` (clientes que no son navegador, p. ej. la prueba de humo) se permite."""
    if origin is None or not origins:
        return True
    if origin in origins:
        return True
    rx = origin_regex(origins)
    return bool(rx and re.match(rx, origin))


def client_ip(conn: HTTPConnection) -> str:
    """IP del cliente; detrás del proxy de la plataforma se toma la primera de X-Forwarded-For."""
    fwd = conn.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return conn.client.host if conn.client else "desconocida"


class SessionLimiter:
    def __init__(self, max_sessions: int, per_minute: int) -> None:
        self.max_sessions = max_sessions
        self.per_minute = per_minute
        self.active = 0
        self._starts: dict[str, deque[float]] = defaultdict(deque)

    def try_acquire(self, ip: str) -> str | None:
        """Reserva una sesión. Devuelve None si se concede o el motivo (`concurrent` o `rate`)."""
        now = time.monotonic()
        q = self._starts[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if self.active >= self.max_sessions:
            return "concurrent"
        if len(q) >= self.per_minute:
            return "rate"
        q.append(now)
        self.active += 1
        return None

    def release(self) -> None:
        self.active = max(0, self.active - 1)
