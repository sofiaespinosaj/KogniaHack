import {
  AUDIO_SAMPLE_RATE,
  PROTOCOL_VERSION,
  type ServerEvent,
  type Speaker,
  type ToolResult,
} from '@/api/types'
import type { AgentTransport } from '@/services/transport'

// Mock del servidor. Usa SOLO los payloads de ejemplo de
// openspec/changes/realtime-voice/specs/ws-event-contract/spec.md (v1.0):
//   session.state, session.brief, transcript.partial/final, agent.tool, audio.start/clear,
//   agent.text, sentiment y metrics. Lo único que se genera aquí es la numeración
//   (seq, turn_id, utt_id, call_id), `ts` (ms desde el inicio de la sesión) y el
//   troceado del texto del agente (agent.text es acumulado, según el contrato).
//
// Nota: `texto` del brief es el que produce GET /api/brief (el ejemplo del contrato está
// truncado con «…»); `preguntas`, `fecha_corte` y `origen` son los del ejemplo.

type Draft<T> = T extends unknown ? Omit<T, 'v' | 'seq'> : never
type ServerDraft = Draft<ServerEvent>

const EXAMPLE = {
  brief: {
    turn_id: 't-0000',
    texto:
      'Soy Lumi. Tengo datos de 9.320 IPS públicas y privadas de Colombia y 15.547 sedes, con corte al 5 de noviembre de 2022. ' +
      'Las IPS se cuentan como prestadores distintos, y el nivel de atención casi solo existe para las públicas. ' +
      '¿Qué quieres saber?',
    preguntas: [
      '¿Cuántas IPS hay en total?',
      '¿Qué departamento tiene más IPS?',
      '¿Cuántas camas hay en Antioquia?',
    ],
    fecha_corte: '2022-11-05',
    origen: 'snapshot',
  },
  partial: { speaker: 'speaker_1', text: 'cuántas IPS públicas', source: 'deepgram', degraded: false },
  final: {
    speaker: 'speaker_1',
    text: '¿Cuántas IPS públicas hay en Antioquia?',
    source: 'deepgram',
    degraded: false,
  },
  tool: {
    call_id: 'c-01',
    name: 'count_ips',
    args: { departamento: 'Antioquia' },
    summary: {
      valor: 837,
      filtros: { departamento: 'Antioquia' },
      filas_usadas: 4410,
      fecha_corte: '2022-11-05',
      origen: 'snapshot',
      estado: 'ok',
    } satisfies ToolResult,
  },
  agentText: 'En Antioquia hay unas 840 IPS',
  sentiment: { sentiment: 'neutro', emotion: 'curiosidad', score: 0.1 },
  metrics: { first_audio_ms: 1120, vad_silence_ms: 500, tool_ms: 85, total_ms: 4300 },
} as const

const BRIEF_SPEAK_MS = 3500
const CONNECT_MS = 250
const PARTIAL_TO_FINAL_MS = 900
const TOOL_RUNNING_MS = 450
const WORD_MS = 170
const SENTIMENT_DELAY_MS = 500

type Handler = (e: ServerEvent) => void
type Phase = 'idle' | 'thinking' | 'speaking'

export class MockTransport implements AgentTransport {
  private handlers = new Set<Handler>()
  private timers = new Set<ReturnType<typeof setTimeout>>()
  private seq = 0
  private turnCount = 0
  private uttCount = 0
  private callCount = 0
  private startedAt = 0
  private connected = false
  private paused = false
  private token = 0 // invalida el turno en curso al interrumpir o cerrar
  private phase: Phase = 'idle'
  private turnId = 't-0000'
  private turnStartedAt = 0
  private spoken = ''

  on(handler: Handler): () => void {
    this.handlers.add(handler)
    return () => {
      this.handlers.delete(handler)
    }
  }

  // Equivale a abrir el WS y enviar session.start { brief: "speak", audio_out: true }.
  async connect(): Promise<void> {
    if (this.connected) return
    this.connected = true
    this.seq = this.turnCount = this.uttCount = this.callCount = 0
    this.startedAt = Date.now()
    const token = ++this.token
    this.emit({ type: 'session.state', state: 'conectando' })
    if (!(await this.wait(CONNECT_MS, token))) return
    this.emit({ type: 'session.state', state: 'listo', protocol: PROTOCOL_VERSION, voice: 'enabled' })
    this.emit({ type: 'session.brief', ...EXAMPLE.brief, preguntas: [...EXAMPLE.brief.preguntas] })

    // El brief se habla bajo t-0000 sin esperar al usuario.
    this.turnId = EXAMPLE.brief.turn_id
    this.phase = 'speaking'
    this.emit({ type: 'audio.start', turn_id: this.turnId, format: 'pcm16', sample_rate: AUDIO_SAMPLE_RATE })
    this.emit({ type: 'session.state', state: 'hablando' })
    if (!(await this.wait(BRIEF_SPEAK_MS, token))) return
    this.emit({ type: 'audio.end', turn_id: this.turnId })
    this.phase = 'idle'
    this.emit({ type: 'session.state', state: 'escuchando', protocol: PROTOCOL_VERSION, voice: 'enabled' })
  }

  // text.message: turno del usuario sin STT (source "text", speaker "user").
  sendText(text: string): void {
    const q = text.trim()
    if (!this.canStartTurn() || !q) return
    void this.runTurn('text', q)
  }

  // Frames de micrófono: el primero de una ráfaga abre un turno de voz con el ejemplo del contrato.
  sendAudio(_chunk: ArrayBuffer): void {
    if (!this.canStartTurn()) return
    void this.runTurn('voice')
  }

  // Barge-in: audio.clear, texto marcado como interrumpido y vuelta a «escuchando».
  interrupt(): void {
    if (!this.connected || this.phase === 'idle') return
    this.token++
    if (this.phase === 'speaking') {
      this.emit({ type: 'audio.clear', turn_id: this.turnId })
      if (this.turnId !== EXAMPLE.brief.turn_id) {
        this.emit({
          type: 'agent.text',
          turn_id: this.turnId,
          text: this.spoken,
          final: true,
          interrupted: true,
        })
      }
    } else {
      // Interrumpido antes del primer audio: metrics sin first_audio_ms e `interrupted`.
      this.emit({
        type: 'metrics',
        turn_id: this.turnId,
        total_ms: Date.now() - this.turnStartedAt,
        interrupted: true,
      })
    }
    this.phase = 'idle'
    this.emit({ type: 'session.state', state: 'escuchando', protocol: PROTOCOL_VERSION, voice: 'enabled' })
  }

  // Pausa de la conversación (decisión del cliente, no es un mensaje del contrato):
  // se corta lo que esté en curso y se deja de aceptar turnos.
  pause(): void {
    if (!this.connected || this.paused) return
    this.interrupt()
    this.paused = true
  }

  resume(): void {
    this.paused = false
  }

  // Equivale a session.stop y cierre del WS.
  close(): void {
    this.token++
    this.timers.forEach(clearTimeout)
    this.timers.clear()
    this.connected = false
    this.paused = false
    this.phase = 'idle'
  }

  // ---------------------------------------------------------------- internos
  private canStartTurn(): boolean {
    if (!this.connected || this.paused) return false
    if (this.phase !== 'idle') this.interrupt() // hablar o escribir encima del agente = barge-in
    return true
  }

  private async runTurn(kind: 'voice' | 'text', typed?: string): Promise<void> {
    const token = ++this.token
    const turnId = `t-${String(++this.turnCount).padStart(4, '0')}`
    const uttId = `u-${String(++this.uttCount).padStart(4, '0')}`
    this.turnId = turnId
    this.turnStartedAt = Date.now()
    this.spoken = ''
    this.phase = 'thinking'
    const ts = this.now()

    let speaker: Speaker
    let userText: string
    if (kind === 'voice') {
      speaker = EXAMPLE.final.speaker
      userText = EXAMPLE.final.text
      this.emit({ type: 'transcript.partial', turn_id: turnId, utt_id: uttId, ts, ...EXAMPLE.partial })
      if (!(await this.wait(PARTIAL_TO_FINAL_MS, token))) return
    } else {
      speaker = 'user'
      userText = typed ?? ''
    }
    this.emit({
      type: 'transcript.final',
      turn_id: turnId,
      utt_id: uttId,
      ts,
      ts_end: this.now(),
      ...(kind === 'voice'
        ? EXAMPLE.final
        : { speaker, text: userText, source: 'text' as const, degraded: false }),
    })
    this.emit({ type: 'session.state', state: 'pensando' })

    // El sentimiento llega de forma asíncrona, sin bloquear la respuesta.
    this.later(SENTIMENT_DELAY_MS, token, () =>
      this.emit({ type: 'sentiment', turn_id: turnId, utt_id: uttId, speaker, ...EXAMPLE.sentiment }),
    )

    const callId = `c-${String(++this.callCount).padStart(2, '0')}`
    const tool = { turn_id: turnId, call_id: callId, name: EXAMPLE.tool.name, args: { ...EXAMPLE.tool.args } }
    this.emit({ type: 'agent.tool', ...tool, status: 'running' })
    if (!(await this.wait(TOOL_RUNNING_MS, token))) return
    this.emit({ type: 'agent.tool', ...tool, status: 'done', summary: EXAMPLE.tool.summary })

    this.emit({ type: 'audio.start', turn_id: turnId, format: 'pcm16', sample_rate: AUDIO_SAMPLE_RATE })
    this.phase = 'speaking'
    this.emit({ type: 'session.state', state: 'hablando' })

    const words = EXAMPLE.agentText.split(' ')
    for (let i = 1; i <= words.length; i++) {
      if (!(await this.wait(WORD_MS, token))) return
      this.spoken = words.slice(0, i).join(' ')
      this.emit({
        type: 'agent.text',
        turn_id: turnId,
        text: this.spoken,
        final: i === words.length,
        interrupted: false,
      })
    }
    this.emit({ type: 'audio.end', turn_id: turnId })
    this.emit({ type: 'metrics', turn_id: turnId, ...EXAMPLE.metrics })
    this.phase = 'idle'
    this.emit({ type: 'session.state', state: 'escuchando', protocol: PROTOCOL_VERSION, voice: 'enabled' })
  }

  private now(): number {
    return Date.now() - this.startedAt
  }

  private emit(draft: ServerDraft): void {
    const e = { ...draft, v: 1, seq: ++this.seq } as ServerEvent
    this.handlers.forEach((h) => h(e))
  }

  /** Espera `ms`; devuelve false si el turno fue invalidado (interrupción o cierre). */
  private wait(ms: number, token: number): Promise<boolean> {
    return new Promise((resolve) => {
      const t = setTimeout(() => {
        this.timers.delete(t)
        resolve(token === this.token)
      }, ms)
      this.timers.add(t)
    })
  }

  private later(ms: number, token: number, fn: () => void): void {
    void this.wait(ms, token).then((ok) => {
      if (ok || this.connected) fn() // el sentimiento se emite aunque el turno se interrumpa
    })
  }
}
