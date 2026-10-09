import type {
  AgentToolEvent,
  Brief,
  ErrorEvent,
  MetricsEvent,
  SentimentEvent,
  ServerEvent,
  SessionStateName,
  Speaker,
  TranscriptSource,
} from '@/api/types'

// Vista derivada del flujo de eventos del contrato (ws-event-contract v1.0).
// Reglas aplicadas: transcript.final reemplaza a las parciales con el mismo utt_id;
// agent.text es acumulado; sentiment/metrics se asocian por turn_id (+ utt_id) aunque lleguen tarde.

export interface Utterance {
  uttId: string
  turnId: string
  speaker: Speaker
  ts: number
  tsEnd?: number
  text: string
  final: boolean
  source: TranscriptSource
  degraded: boolean
}

export interface AgentTurn {
  turnId: string
  text: string
  final: boolean
  interrupted: boolean
  at: number // ms desde el inicio de la sesión (hora de llegada; agent.text no trae ts)
}

export type ToolCall = Pick<
  AgentToolEvent,
  'turn_id' | 'call_id' | 'name' | 'args' | 'status' | 'summary'
>

export type TimelineKey = { kind: 'utt'; id: string } | { kind: 'agent'; id: string }

export interface SessionView {
  state: SessionStateName | 'idle'
  voice?: 'enabled' | 'disabled'
  brief: (Brief & { turnId: string }) | null
  utterances: Record<string, Utterance>
  agentTurns: Record<string, AgentTurn>
  timeline: TimelineKey[]
  tools: ToolCall[]
  sentiments: SentimentEvent[]
  metrics: Record<string, MetricsEvent>
  issues: ErrorEvent[]
  audioActive: boolean
}

export const initialSession: SessionView = {
  state: 'idle',
  brief: null,
  utterances: {},
  agentTurns: {},
  timeline: [],
  tools: [],
  sentiments: [],
  metrics: {},
  issues: [],
  audioActive: false,
}

export type SessionAction = { type: 'reset' } | { type: 'event'; event: ServerEvent; at: number }

export function sessionReducer(s: SessionView, a: SessionAction): SessionView {
  if (a.type === 'reset') return initialSession
  const e = a.event
  switch (e.type) {
    case 'session.state':
      return { ...s, state: e.state, voice: e.voice ?? s.voice }
    case 'session.brief':
      return {
        ...s,
        brief: {
          turnId: e.turn_id,
          texto: e.texto,
          preguntas: e.preguntas,
          fecha_corte: e.fecha_corte,
          origen: e.origen,
        },
      }
    case 'transcript.partial':
    case 'transcript.final': {
      const prev = s.utterances[e.utt_id]
      if (prev?.final) return s // una parcial tardía no pisa a la final
      const isFinal = e.type === 'transcript.final'
      const utt: Utterance = {
        uttId: e.utt_id,
        turnId: e.turn_id,
        speaker: e.speaker,
        ts: e.ts,
        tsEnd: isFinal ? e.ts_end : undefined,
        text: e.text,
        final: isFinal,
        source: e.source,
        degraded: e.degraded,
      }
      return {
        ...s,
        utterances: { ...s.utterances, [e.utt_id]: utt },
        timeline: prev ? s.timeline : [...s.timeline, { kind: 'utt', id: e.utt_id }],
      }
    }
    case 'agent.text': {
      const prev = s.agentTurns[e.turn_id]
      const turn: AgentTurn = {
        turnId: e.turn_id,
        text: e.text,
        final: e.final,
        interrupted: e.interrupted,
        at: prev?.at ?? a.at,
      }
      return {
        ...s,
        agentTurns: { ...s.agentTurns, [e.turn_id]: turn },
        timeline: prev ? s.timeline : [...s.timeline, { kind: 'agent', id: e.turn_id }],
      }
    }
    case 'audio.start':
      return { ...s, audioActive: true }
    case 'audio.end':
    case 'audio.clear':
      return { ...s, audioActive: false }
    case 'agent.tool': {
      const call: ToolCall = {
        turn_id: e.turn_id,
        call_id: e.call_id,
        name: e.name,
        args: e.args,
        status: e.status,
        summary: e.summary,
      }
      const i = s.tools.findIndex((t) => t.turn_id === e.turn_id && t.call_id === e.call_id)
      const tools = i < 0 ? [...s.tools, call] : s.tools.map((t, j) => (j === i ? call : t))
      return { ...s, tools }
    }
    case 'sentiment':
      return { ...s, sentiments: [...s.sentiments, e] }
    case 'metrics':
      return { ...s, metrics: { ...s.metrics, [e.turn_id]: e } }
    case 'error':
      return { ...s, issues: [...s.issues, e], state: e.severity === 'fatal' ? 'error' : s.state }
    default:
      return s
  }
}
