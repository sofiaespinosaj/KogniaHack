// Tipos del contrato Frontend <-> Backend.
// REST y tools: backend/README.md y openspec/changes/grounded-agent.
// WebSocket: openspec/changes/realtime-voice/specs/ws-event-contract/spec.md (protocolo "1.0").
// Cuando el backend publique backend/contract/ws-events.schema.json, la sección WebSocket debe
// sustituirse por tipos GENERADOS desde ese esquema (el contrato prohíbe mantenerlos a mano).

// ===================================================================== [VIGENTE] REST

// ---- GET /health ----
export type DataStatus = 'loading' | 'ready' | 'degraded' | 'unavailable'
export type DataSource = 'snapshot' | 'api'

export interface Provenance {
  dataset: string // "s2ru-bqt6"
  loaded_at: string | null // ISO 8601 UTC
  source: DataSource | null
  rows: number // 41427 en el corte actual
  fecha_corte: string | null // "YYYY-MM-DD" (2022-11-05)
  refresh_skipped_reason: string | null // p. ej. "SODA_APP_TOKEN no definido"
  conversion_failures: Record<string, number>
}

export interface Health {
  status: DataStatus
  error: string | null // nunca contiene secretos
  data: Provenance
}

// ---- 503 de /profile y /api/brief ----
export interface ApiUnavailable {
  error: string
  status: DataStatus
}

// ---- GET /api/brief ----
export interface Brief {
  texto: string // texto hablado (~20 s)
  preguntas: string[] // 3..5, todas respondibles con las tools
  fecha_corte: string // "2022-11-05"
  origen: DataSource
}

// ---- GET /profile ----
export interface ProfileValue {
  value: string | number
  count: number
}

export interface ProfileColumn {
  name: string
  type: string
  nulls: number
  null_pct: number
  distinct: number
  values?: ProfileValue[] // ausente en ids, contactos y *_norm
  values_complete?: boolean // true: todos los valores (<=50 distintos)
}

export interface DatasetProfile {
  grain: string
  definitions: { ips: string; sedes: string }
  counting_guidance: string
  rows: number
  ips_distintas: number
  sedes_distintas: number
  columns: ProfileColumn[]
  coverage: {
    nivel_atencion: {
      null_rows: number
      null_pct: number
      rows_with_level_publica: number
      rows_with_level_privada: number
    }
    notes: string[]
  }
  naturaleza: Record<string, number> // Pública / Privada / Mixta -> filas
  fecha_corte: string | null
  source: DataSource | null
}

// ===================================================================== [VIGENTE] Tools

// Enums: NO hardcodear. Se derivan de /profile (columns[name].values) porque cambian con el refresco.
export type Naturaleza = string
export type NivelAtencion = number
export type GrupoCapacidad = string
export type Departamento = string

export interface CommonFilters {
  departamento?: Departamento // se aplica sobre departamento_canonico
  municipio?: string // libre, con/sin tildes
  naturaleza?: Naturaleza
  nivel_atencion?: NivelAtencion
}

export type Metrica = 'ips' | 'sedes' | 'capacidad' // capacidad exige grupo_capacidad
export type Dimension =
  | 'departamento'
  | 'municipio'
  | 'naturaleza'
  | 'nivel_atencion'
  | 'grupo_capacidad'

export type ToolName =
  | 'count_ips'
  | 'count_sedes'
  | 'sum_capacidad'
  | 'top_n'
  | 'group_by'
  | 'buscar_ips'

export type ToolArgs =
  | { tool: 'count_ips' | 'count_sedes'; args: CommonFilters }
  | {
      tool: 'sum_capacidad'
      args: CommonFilters & { grupo_capacidad: GrupoCapacidad; descripcion_capacidad?: string }
    }
  | {
      tool: 'top_n'
      args: CommonFilters & {
        dimension: Dimension
        metrica: Metrica
        n?: number // >=1, tope 10
        grupo_capacidad?: GrupoCapacidad
        descripcion_capacidad?: string
      }
    }
  | {
      tool: 'group_by'
      args: CommonFilters & {
        dimension: Dimension
        metrica: Metrica
        grupo_capacidad?: GrupoCapacidad
        descripcion_capacidad?: string
      }
    }
  | {
      tool: 'buscar_ips'
      args: { nombre: string; departamento?: Departamento; municipio?: string } // nombre: 2..100
    }

export type ToolEstado =
  | 'ok'
  | 'sin_resultados'
  | 'no_encontrado'
  | 'ambiguo'
  | 'sin_cobertura'
  | 'error_validacion' // argumento fuera de esquema (solo estado + error)
  | 'limite_llamadas' // >2 llamadas por turno (estado + mensaje)

export interface RankingItem {
  nombre: string
  valor: number
}

export interface IpsCandidate {
  nombre: string
  naturaleza?: string
  departamento?: string
  municipio?: string
  sedes?: number
  sede?: string
}

// Envoltorio común. Los campos vacíos/nulos NO se envían: todo salvo `estado` es opcional.
export interface ToolResult {
  estado: ToolEstado
  // número: count_* / sum_capacidad · RankingItem[]: top_n / group_by · IpsCandidate[]: buscar_ips
  valor?: number | RankingItem[] | IpsCandidate[]
  filtros?: Record<string, string | number>
  filas_usadas?: number
  fecha_corte?: string // "2022-11-05"
  origen?: DataSource
  incluye_distritos?: string[] // p. ej. ["Cali", "Buenaventura"] con Valle del Cauca
  no_encontrado?: 'municipio' | 'descripcion_capacidad'
  sugerencias?: string[] // <=3, con no_encontrado
  candidatos?: string[] | IpsCandidate[] // con ambiguo (<=10)
  total_candidatos?: number // si hay más de 10
  acotado?: boolean // resultado recortado a 10
  nota?: string // p. ej. cobertura de nivel_atencion
  // solo en estados de error:
  error?: string
  permitidos?: Array<string | number>
  mensaje?: string
}


// ===================================================================== WebSocket (ws-event-contract v1.0)
// Un WebSocket por sesión. Frames de texto = JSON con `type` y `v`; frames binarios = SIEMPRE audio
// PCM16 mono 24 kHz little-endian en frames de 40 ms (1.920 bytes), en ambos sentidos.
// `ts` / `ts_end` son milisegundos desde el inicio de la sesión.
// La ruta del endpoint (p. ej. /ws) todavía no está fijada en el contrato.

export const PROTOCOL_VERSION = '1.0'
export const AUDIO_SAMPLE_RATE = 24000
export const AUDIO_FRAME_BYTES = 1920

export type SessionStateName =
  | 'conectando'
  | 'listo'
  | 'escuchando'
  | 'pensando'
  | 'hablando'
  | 'error'

// `agent` = agente; `speaker_1`, `speaker_2`… con diarización; `user` sin etiquetas (degradado o texto).
export type Speaker = 'agent' | 'user' | `speaker_${number}`
export type TranscriptSource = 'deepgram' | 'openai' | 'text'

// ---- Cliente -> servidor (JSON) ----
export type ClientMessage =
  | { type: 'session.start'; v: 1; protocol: string; brief: 'speak' | 'skip'; audio_out: boolean }
  | { type: 'session.stop'; v: 1 }
  | { type: 'text.message'; v: 1; text: string }
  | { type: 'playback.position'; v: 1; turn_id: string; played_ms: number }

// ---- Servidor -> cliente (JSON). Todo mensaje lleva `v` y `seq` (creciente por sesión). ----
interface ServerBase {
  v: 1
  seq: number
}

export type SessionStateEvent = ServerBase & {
  type: 'session.state'
  state: SessionStateName
  protocol?: string // "1.0"
  voice?: 'enabled' | 'disabled'
  detail?: string | Record<string, unknown>
}

// turn_id siempre "t-0000".
export type SessionBriefEvent = ServerBase & {
  type: 'session.brief'
  turn_id: string
} & Brief

export type TranscriptPartialEvent = ServerBase & {
  type: 'transcript.partial'
  turn_id: string
  utt_id: string
  speaker: Speaker
  ts: number
  text: string
  source: TranscriptSource
  degraded: boolean
}

// Reemplaza a las parciales con el mismo utt_id.
export type TranscriptFinalEvent = ServerBase & {
  type: 'transcript.final'
  turn_id: string
  utt_id: string
  speaker: Speaker
  ts: number
  ts_end: number
  text: string
  source: TranscriptSource
  degraded: boolean
}

// `text` es el acumulado hasta ese momento.
export type AgentTextEvent = ServerBase & {
  type: 'agent.text'
  turn_id: string
  text: string
  final: boolean
  interrupted: boolean
}

export type AudioStartEvent = ServerBase & {
  type: 'audio.start'
  turn_id: string
  format: 'pcm16'
  sample_rate: number
}
export type AudioEndEvent = ServerBase & { type: 'audio.end'; turn_id: string }
// Tras audio.clear se descartan TODOS los frames binarios hasta el siguiente audio.start.
export type AudioClearEvent = ServerBase & { type: 'audio.clear'; turn_id: string }

export type AgentToolEvent = ServerBase & {
  type: 'agent.tool'
  turn_id: string
  call_id: string
  name: ToolName
  args: Record<string, unknown>
  status: 'running' | 'done' | 'error'
  summary?: ToolResult // al terminar: valor, filtros, filas_usadas, fecha_corte, origen, estado
}

export type SentimentEvent = ServerBase & {
  type: 'sentiment'
  turn_id: string
  utt_id: string
  speaker: Speaker
  sentiment: string // valores permitidos: change `sentiment-emotion` (aún sin spec)
  emotion: string // idem
  score: number // -1..1
}

export type MetricsEvent = ServerBase & {
  type: 'metrics'
  turn_id: string
  first_audio_ms?: number // ausente si el turno se interrumpió antes del primer audio
  vad_silence_ms?: number // ausente con semantic_vad
  tool_ms?: number // solo si hubo tools
  total_ms: number
  interrupted?: boolean
}

export type ErrorCode =
  | 'voice_disabled'
  | 'session_already_active'
  | 'session_limit'
  | 'unsupported_protocol'
  | 'invalid_message'
  | 'no_active_session'
  | 'origin_not_allowed'
  | 'session_expiring'
  | 'openai_unavailable'
  | 'deepgram_unavailable'
  | 'data_unavailable'
  | 'internal'

export type ErrorEvent = ServerBase & {
  type: 'error'
  code: ErrorCode
  message: string // en español
  severity: 'warning' | 'fatal'
  recoverable: boolean
  detail?: Record<string, unknown> // p. ej. { reason } o { seconds_left }
}

export type ServerEvent =
  | SessionStateEvent
  | SessionBriefEvent
  | TranscriptPartialEvent
  | TranscriptFinalEvent
  | AgentTextEvent
  | AudioStartEvent
  | AudioEndEvent
  | AudioClearEvent
  | AgentToolEvent
  | SentimentEvent
  | MetricsEvent
  | ErrorEvent

export type ServerEventType = ServerEvent['type']

/** Latencia percibida = silencio del VAD + primer audio (ambos medidos en el servidor). */
export function perceivedLatencyMs(m: Pick<MetricsEvent, 'first_audio_ms' | 'vad_silence_ms'>): number | null {
  return m.first_audio_ms === undefined ? null : (m.vad_silence_ms ?? 0) + m.first_audio_ms
}
