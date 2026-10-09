"""Contrato de eventos del WebSocket (versión 1.0).

Los modelos de este módulo son la fuente de verdad: de ellos se exporta el JSON Schema
(`backend/contract/ws-events.schema.json`) y los tipos TypeScript (`ws-events.ts`).

Reglas generales:
- Frames binarios = audio PCM16 mono 24 kHz little-endian, frames de 40 ms (1.920 bytes), en ambos sentidos.
- Frames de texto = JSON con `type` y `v` (versión mayor, 1). Los del servidor llevan además `seq`.
- `ts` y `ts_end` son milisegundos desde el inicio de la sesión.
"""
from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

PROTOCOL = "1.0"
SUPPORTED_PROTOCOLS = [PROTOCOL]
MAJOR = 1
AUDIO_FORMAT, SAMPLE_RATE, FRAME_MS, FRAME_BYTES = "pcm16", 24000, 40, 1920
MAX_AUDIO_FRAME_BYTES = SAMPLE_RATE * 2          # 1 s: tope por frame binario
MAX_TEXT_CHARS = 500

SessionStateName = Literal["conectando", "listo", "escuchando", "pensando", "hablando", "error"]
ErrorCode = Literal[
    "voice_disabled", "session_already_active", "session_limit", "unsupported_protocol", "invalid_message",
    "no_active_session", "origin_not_allowed", "session_expiring", "openai_unavailable", "deepgram_unavailable",
    "data_unavailable", "internal"]
Source = Literal["deepgram", "openai", "text"]


class _Msg(BaseModel):
    model_config = ConfigDict(extra="forbid")
    v: Literal[1] = MAJOR


# --------------------------------------------------------------------------- cliente -> servidor
class SessionStart(_Msg):
    type: Literal["session.start"] = "session.start"
    protocol: str = Field(pattern=r"^\d+\.\d+$", description="Versión del contrato, p. ej. '1.0'.")
    brief: Literal["speak", "skip"] = "speak"
    audio_out: bool = True


class SessionStop(_Msg):
    type: Literal["session.stop"] = "session.stop"


class TextMessage(_Msg):
    type: Literal["text.message"] = "text.message"
    text: str = Field(min_length=1, max_length=MAX_TEXT_CHARS)


class PlaybackPosition(_Msg):
    type: Literal["playback.position"] = "playback.position"
    turn_id: str
    played_ms: int = Field(ge=0)


ClientMessage = Annotated[Union[SessionStart, SessionStop, TextMessage, PlaybackPosition], Field(discriminator="type")]


# --------------------------------------------------------------------------- servidor -> cliente
class _ServerMsg(_Msg):
    seq: int = Field(ge=1, description="Entero estrictamente creciente por conexión.")


class SessionState(_ServerMsg):
    type: Literal["session.state"] = "session.state"
    state: SessionStateName
    protocol: str | None = None
    voice: Literal["enabled", "disabled"] | None = None
    detail: str | None = None


class SessionBrief(_ServerMsg):
    type: Literal["session.brief"] = "session.brief"
    turn_id: Literal["t-0000"] = "t-0000"
    texto: str
    preguntas: list[str]
    fecha_corte: str
    origen: str


class TranscriptPartial(_ServerMsg):
    type: Literal["transcript.partial"] = "transcript.partial"
    turn_id: str
    utt_id: str
    speaker: str = Field(description="'agent', 'user' (sin etiquetas) o 'speaker_N'.")
    ts: int = Field(ge=0)
    text: str
    source: Source
    degraded: bool = False


class TranscriptFinal(_ServerMsg):
    type: Literal["transcript.final"] = "transcript.final"
    turn_id: str
    utt_id: str
    speaker: str
    ts: int = Field(ge=0)
    ts_end: int = Field(ge=0)
    text: str
    source: Source
    degraded: bool = False


class AgentText(_ServerMsg):
    type: Literal["agent.text"] = "agent.text"
    turn_id: str
    text: str = Field(description="Texto acumulado hasta ese momento.")
    final: bool
    interrupted: bool = False


class AudioStart(_ServerMsg):
    type: Literal["audio.start"] = "audio.start"
    turn_id: str
    format: Literal["pcm16"] = AUDIO_FORMAT
    sample_rate: Literal[24000] = SAMPLE_RATE


class AudioEnd(_ServerMsg):
    type: Literal["audio.end"] = "audio.end"
    turn_id: str


class AudioClear(_ServerMsg):
    type: Literal["audio.clear"] = "audio.clear"
    turn_id: str


class ToolSummary(BaseModel):
    """Resumen de evidencia: sin SQL, sin claves y con listas de 10 elementos como máximo."""
    model_config = ConfigDict(extra="allow")
    valor: Any = None
    filtros: dict[str, Any] | None = None
    filas_usadas: int | None = None
    fecha_corte: str | None = None
    origen: str | None = None
    estado: str | None = None


class AgentTool(_ServerMsg):
    type: Literal["agent.tool"] = "agent.tool"
    turn_id: str
    call_id: str
    name: str
    args: dict[str, Any]
    status: Literal["running", "done", "error"]
    summary: ToolSummary | None = None


class Sentiment(_ServerMsg):
    type: Literal["sentiment"] = "sentiment"
    turn_id: str
    utt_id: str
    speaker: str
    sentiment: str
    emotion: str
    score: float = Field(ge=-1, le=1)


class Metrics(_ServerMsg):
    type: Literal["metrics"] = "metrics"
    turn_id: str
    first_audio_ms: int | None = Field(None, ge=0, description="Fin de habla del VAD -> primer frame de audio.")
    vad_silence_ms: int | None = Field(None, ge=0, description="Silencio configurado del VAD; ausente con semantic_vad.")
    tool_ms: int | None = Field(None, ge=0)
    total_ms: int | None = Field(None, ge=0)
    interrupted: bool | None = None


class ErrorMsg(_ServerMsg):
    type: Literal["error"] = "error"
    code: ErrorCode
    message: str
    severity: Literal["warning", "fatal"]
    recoverable: bool
    detail: dict[str, Any] | None = Field(None, description="p. ej. {'reason': 'rate'} o {'seconds_left': 120}.")


ServerMessage = Annotated[Union[SessionState, SessionBrief, TranscriptPartial, TranscriptFinal, AgentText, AudioStart,
                                AudioEnd, AudioClear, AgentTool, Sentiment, Metrics, ErrorMsg],
                          Field(discriminator="type")]
AnyMessage = Annotated[Union[SessionStart, SessionStop, TextMessage, PlaybackPosition, SessionState, SessionBrief,
                             TranscriptPartial, TranscriptFinal, AgentText, AudioStart, AudioEnd, AudioClear,
                             AgentTool, Sentiment, Metrics, ErrorMsg], Field(discriminator="type")]

CLIENT_TYPES = [SessionStart, SessionStop, TextMessage, PlaybackPosition]
SERVER_TYPES = [SessionState, SessionBrief, TranscriptPartial, TranscriptFinal, AgentText, AudioStart, AudioEnd,
                AudioClear, AgentTool, Sentiment, Metrics, ErrorMsg]

_client_adapter: TypeAdapter = TypeAdapter(ClientMessage)

# Textos de error en español, sin detalles internos.
ERROR_TEXT: dict[str, tuple[str, str, bool]] = {
    # code: (message, severity, recoverable)
    "voice_disabled": ("La voz está apagada en este servidor.", "fatal", False),
    "session_already_active": ("Ya hay una sesión de voz activa en esta conexión.", "warning", True),
    "session_limit": ("Se alcanzó un límite de sesiones.", "fatal", True),
    "unsupported_protocol": ("La versión del protocolo no está soportada.", "fatal", False),
    "invalid_message": ("El mensaje no es válido.", "warning", True),
    "no_active_session": ("No hay una sesión activa; envía session.start primero.", "warning", True),
    "origin_not_allowed": ("El origen no está permitido.", "fatal", False),
    "session_expiring": ("La sesión está por terminar.", "warning", True),
    "openai_unavailable": ("El servicio de voz no está disponible; puedes reintentar con un nuevo session.start.",
                           "fatal", True),
    "deepgram_unavailable": ("La transcripción con hablantes no está disponible; se muestra una transcripción "
                             "sin etiquetas.", "warning", True),
    "data_unavailable": ("Los datos aún no están disponibles.", "fatal", True),
    "internal": ("Ocurrió un error interno.", "fatal", True),
}


def parse_client_message(data: Any) -> tuple[ClientMessage | None, dict | None]:
    """Valida un mensaje JSON del cliente. Devuelve (mensaje, None) o (None, detail del error)."""
    if not isinstance(data, dict):
        return None, {"reason": "el mensaje debe ser un objeto JSON"}
    if "type" not in data:
        return None, {"reason": "falta el campo type"}
    if data["type"] not in {c.model_fields["type"].default for c in CLIENT_TYPES}:
        return None, {"reason": "tipo de mensaje desconocido"}
    try:
        return _client_adapter.validate_python(data), None
    except Exception as e:  # noqa: BLE001 - ValidationError: solo se informa el campo, nunca el valor
        errs = getattr(e, "errors", lambda: [])()
        loc = ".".join(str(p) for p in errs[0]["loc"][1:]) if errs else ""
        return None, {"reason": "campo inválido", "field": loc} if loc else {"reason": "mensaje inválido"}


def protocol_supported(protocol: str) -> bool:
    try:
        return int(protocol.split(".")[0]) == MAJOR
    except (ValueError, IndexError):
        return False


class TurnIds:
    """Generador de `turn_id` (t-0001...) y `utt_id` (u-0001...). El brief usa t-0000."""

    BRIEF = "t-0000"

    def __init__(self) -> None:
        self._t = self._u = 0

    def next_turn(self) -> str:
        self._t += 1
        return f"t-{self._t:04d}"

    def next_utt(self) -> str:
        self._u += 1
        return f"u-{self._u:04d}"
