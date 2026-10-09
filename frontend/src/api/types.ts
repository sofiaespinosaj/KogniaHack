// Tipos del contrato Frontend <-> Backend.
// Fuente: docs/FRONTEND_INTEGRATION_SPEC.md (sección 4).
// [VIGENTE] = respaldado por el backend (REST y tools). [PROPUESTA] = WebSocket, aún sin
// change `realtime-voice`: no es contractual hasta que el backend lo formalice.

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

// ===================================================================== [PROPUESTA] WebSocket
// Ruta sugerida: ws://localhost:8000/ws (un WS por sesión). NO existe en el backend todavía.

export type AgentState = 'idle' | 'connecting' | 'listening' | 'thinking' | 'speaking' | 'error'

export type Sentiment = 'positivo' | 'neutral' | 'negativo'

export type ServerEvent =
  | { type: 'session.ready'; model?: string }
  | ({ type: 'brief' } & Brief) // mismo shape que Brief
  | { type: 'agent.state'; state: AgentState }
  | { type: 'transcript.partial'; id: string; speaker: string; text: string; ts: number }
  | { type: 'transcript.final'; id: string; speaker: string; text: string; ts: number }
  | { type: 'agent.text.delta'; id: string; delta: string }
  | { type: 'agent.audio' } // chunk de audio: formato por definir
  | { type: 'tool.call'; id: string; name: ToolName; args: Record<string, unknown> }
  | { type: 'tool.result'; id: string; name: ToolName; result: ToolResult }
  | { type: 'insight'; id: string; sentiment?: Sentiment; emotions?: Record<string, number> }
  | { type: 'error'; code: string; message: string }

export type ClientEvent =
  | { type: 'audio.chunk' } // PCM/opus: formato por definir
  | { type: 'text.question'; text: string } // preguntas sugeridas / modo teclado
  | { type: 'interrupt' } // barge-in
  | { type: 'session.end' }
