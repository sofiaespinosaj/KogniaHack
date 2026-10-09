// GENERADO desde backend/app/ws/protocol.py — no editar a mano.
// Regenerar: uv run python -m app.ws.export all (desde backend/).
// Protocolo 1.0. Los frames binarios son audio PCM16 mono 24 kHz (1.920 bytes por 40 ms).

export const PROTOCOL_VERSION = "1.0";

export interface AgentText {
  v: 1;
  /** Entero estrictamente creciente por conexión. */
  seq: number;
  type: "agent.text";
  turn_id: string;
  /** Texto acumulado hasta ese momento. */
  text: string;
  final: boolean;
  interrupted?: boolean;
}

export interface AgentTool {
  v: 1;
  /** Entero estrictamente creciente por conexión. */
  seq: number;
  type: "agent.tool";
  turn_id: string;
  call_id: string;
  name: string;
  args: Record<string, unknown>;
  status: "running" | "done" | "error";
  summary?: ToolSummary | null;
}

export interface AudioClear {
  v: 1;
  /** Entero estrictamente creciente por conexión. */
  seq: number;
  type: "audio.clear";
  turn_id: string;
}

export interface AudioEnd {
  v: 1;
  /** Entero estrictamente creciente por conexión. */
  seq: number;
  type: "audio.end";
  turn_id: string;
}

export interface AudioStart {
  v: 1;
  /** Entero estrictamente creciente por conexión. */
  seq: number;
  type: "audio.start";
  turn_id: string;
  format?: "pcm16";
  sample_rate?: 24000;
}

export interface ErrorMsg {
  v: 1;
  /** Entero estrictamente creciente por conexión. */
  seq: number;
  type: "error";
  code: "voice_disabled" | "session_already_active" | "session_limit" | "unsupported_protocol" | "invalid_message" | "no_active_session" | "origin_not_allowed" | "session_expiring" | "openai_unavailable" | "deepgram_unavailable" | "data_unavailable" | "internal";
  message: string;
  severity: "warning" | "fatal";
  recoverable: boolean;
  /** p. ej. {'reason': 'rate'} o {'seconds_left': 120}. */
  detail?: Record<string, unknown> | null;
}

export interface Metrics {
  v: 1;
  /** Entero estrictamente creciente por conexión. */
  seq: number;
  type: "metrics";
  turn_id: string;
  /** Fin de habla del VAD -> primer frame de audio. */
  first_audio_ms?: number | null;
  /** Silencio configurado del VAD; ausente con semantic_vad. */
  vad_silence_ms?: number | null;
  tool_ms?: number | null;
  total_ms?: number | null;
  interrupted?: boolean | null;
}

export interface PlaybackPosition {
  v: 1;
  type: "playback.position";
  turn_id: string;
  played_ms: number;
}

export interface Sentiment {
  v: 1;
  /** Entero estrictamente creciente por conexión. */
  seq: number;
  type: "sentiment";
  turn_id: string;
  utt_id: string;
  speaker: string;
  sentiment: string;
  emotion: string;
  score: number;
}

export interface SessionBrief {
  v: 1;
  /** Entero estrictamente creciente por conexión. */
  seq: number;
  type: "session.brief";
  turn_id?: "t-0000";
  texto: string;
  preguntas: string[];
  fecha_corte: string;
  origen: string;
}

export interface SessionStart {
  v: 1;
  type: "session.start";
  /** Versión del contrato, p. ej. '1.0'. */
  protocol: string;
  brief?: "speak" | "skip";
  audio_out?: boolean;
}

export interface SessionState {
  v: 1;
  /** Entero estrictamente creciente por conexión. */
  seq: number;
  type: "session.state";
  state: "conectando" | "listo" | "escuchando" | "pensando" | "hablando" | "error";
  protocol?: string | null;
  voice?: "enabled" | "disabled" | null;
  detail?: string | null;
}

export interface SessionStop {
  v: 1;
  type: "session.stop";
}

export interface TextMessage {
  v: 1;
  type: "text.message";
  text: string;
}

/** Resumen de evidencia: sin SQL, sin claves y con listas de 10 elementos como máximo. */
export interface ToolSummary {
  valor?: unknown;
  filtros?: Record<string, unknown> | null;
  filas_usadas?: number | null;
  fecha_corte?: string | null;
  origen?: string | null;
  estado?: string | null;
}

export interface TranscriptFinal {
  v: 1;
  /** Entero estrictamente creciente por conexión. */
  seq: number;
  type: "transcript.final";
  turn_id: string;
  utt_id: string;
  speaker: string;
  ts: number;
  ts_end: number;
  text: string;
  source: "deepgram" | "openai" | "text";
  degraded?: boolean;
}

export interface TranscriptPartial {
  v: 1;
  /** Entero estrictamente creciente por conexión. */
  seq: number;
  type: "transcript.partial";
  turn_id: string;
  utt_id: string;
  /** 'agent', 'user' (sin etiquetas) o 'speaker_N'. */
  speaker: string;
  ts: number;
  text: string;
  source: "deepgram" | "openai" | "text";
  degraded?: boolean;
}

export type ClientMessage = SessionStart | SessionStop | TextMessage | PlaybackPosition;
export type ServerMessage = SessionState | SessionBrief | TranscriptPartial | TranscriptFinal | AgentText | AudioStart | AudioEnd | AudioClear | AgentTool | Sentiment | Metrics | ErrorMsg;
export type WsMessage = ClientMessage | ServerMessage;

/** Discriminante `type` de todos los mensajes JSON. */
export type MessageType = WsMessage["type"];
