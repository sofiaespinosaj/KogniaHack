"""Backend de voz simulado: sigue el contrato sin OpenAI ni Deepgram."""
from __future__ import annotations

from app.ws import protocol as P


class FakeBackend:
    def __init__(self, fail: bool = False) -> None:
        self.fail, self.ctx = fail, None
        self.frames: list[bytes] = []
        self.texts: list[str] = []
        self.played: list[tuple[str, int]] = []
        self.stopped = False

    async def start(self, ctx) -> None:
        if self.fail:
            raise RuntimeError("fallo simulado con sk-secret-123")
        self.ctx = ctx

    async def begin(self, ctx) -> None:
        await ctx.set_state("escuchando")

    async def on_audio(self, frame: bytes) -> None:
        self.frames.append(frame)

    async def on_text(self, turn_id: str, text: str) -> None:
        """Turno completo con una tool: pensando -> tool -> hablando -> escuchando."""
        c = self.ctx
        await c.set_state("pensando")
        args = {"departamento": "Antioquia"}
        await c.emit(P.AgentTool, turn_id=turn_id, call_id="c-01", name="count_ips", args=args, status="running")
        await c.emit(P.AgentTool, turn_id=turn_id, call_id="c-01", name="count_ips", args=args, status="done",
                     summary={"valor": 837, "filtros": args, "filas_usadas": 4410, "fecha_corte": "2022-11-05",
                              "origen": "snapshot", "estado": "ok"})
        await c.set_state("hablando")
        await c.emit(P.AudioStart, turn_id=turn_id)
        await c.conn.send_audio(b"\0" * P.FRAME_BYTES)
        await c.emit(P.AgentText, turn_id=turn_id, text="En Antioquia hay unas 840 IPS", final=True, interrupted=False)
        await c.emit(P.AudioEnd, turn_id=turn_id)
        await c.emit(P.Metrics, turn_id=turn_id, first_audio_ms=900, tool_ms=12, total_ms=2100)
        await c.set_state("escuchando")
        self.texts.append(text)

    async def on_playback(self, turn_id: str, played_ms: int) -> None:
        self.played.append((turn_id, played_ms))

    async def stop(self) -> None:
        self.stopped = True
