import type { Brief, Sentiment, ServerEvent } from '@/api/types'
import type { AgentTransport } from '@/services/transport'

// Datos tomados de las specs (corte 2022-11-05; 9.320 IPS y 15.547 sedes) y de /api/brief.
const MOCK_BRIEF: Brief = {
  texto:
    'Tengo datos de IPS públicas y privadas de Colombia: 9.320 IPS y 15.547 sedes, con corte al 5 de noviembre de 2022. ' +
    'Las IPS se cuentan como prestadores distintos, y el nivel de atención casi solo existe para las públicas. ' +
    'Abajo tienes preguntas sugeridas.',
  preguntas: [
    '¿Cuántas IPS hay en total?',
    '¿Qué departamento tiene más IPS?',
    '¿Cuántas camas de adultos hay en Antioquia?',
    '¿Cuántas IPS públicas son de nivel 3?',
  ],
  fecha_corte: '2022-11-05',
  origen: 'snapshot',
}

const MOCK_ANSWERS: Record<string, string> = {
  '¿cuántas ips hay en total?':
    'Según el dataset, hay unas 9.320 IPS en total, con corte al 5 de noviembre de 2022.',
  '¿qué departamento tiene más ips?': 'Bogotá D.C. lidera con unas 1.270 IPS, seguida de Antioquia.',
  '¿cuántas camas de adultos hay en antioquia?': 'En Antioquia hay unas 6.400 camas de adultos.',
  '¿cuántas ips públicas son de nivel 3?': 'Hay 29 IPS públicas de nivel 3.',
}
const FALLBACK_ANSWER =
  'No tengo evidencia de eso en el dataset. Puedo contarte cuántas IPS hay por zona, naturaleza o capacidad instalada.'

const USER = 'Usuario'
const AGENT = 'Agente'
const CONNECT_DELAY_MS = 250
const THINK_DELAY_MS = 600
const WORD_DELAY_MS = 90
const INSIGHT_EVERY_MS = 4000
const EMOTIONS = ['confianza', 'curiosidad', 'interés', 'calma']
const SENTIMENTS: Sentiment[] = ['positivo', 'neutral', 'positivo', 'neutral', 'negativo']

type Handler = (e: ServerEvent) => void

export class MockTransport implements AgentTransport {
  private handlers = new Set<Handler>()
  private timers = new Set<ReturnType<typeof setTimeout>>()
  private insightTimer: ReturnType<typeof setInterval> | null = null
  private seq = 0
  private tick = 0
  private connected = false
  private paused = false
  private turn = 0 // invalida la respuesta en curso al interrumpir o cerrar

  on(handler: Handler): () => void {
    this.handlers.add(handler)
    return () => {
      this.handlers.delete(handler)
    }
  }

  async connect(): Promise<void> {
    if (this.connected) return
    this.emit({ type: 'agent.state', state: 'connecting' })
    await this.sleep(CONNECT_DELAY_MS)
    this.connected = true
    this.emit({ type: 'session.ready', model: 'mock' })
    this.emit({ type: 'agent.state', state: 'listening' })
    this.emit({ type: 'brief', ...MOCK_BRIEF })
    this.startInsights()
  }

  sendText(text: string): void {
    const question = text.trim()
    if (!this.connected || this.paused || !question) return
    const turn = ++this.turn
    this.emit({
      type: 'transcript.final',
      id: this.nextId('u'),
      speaker: USER,
      text: question,
      ts: Date.now(),
    })
    this.emit({ type: 'agent.state', state: 'thinking' })
    void this.sleep(THINK_DELAY_MS).then(() => this.streamAnswer(question, turn))
  }

  sendAudio(_chunk: ArrayBuffer): void {
    // El mock ignora el audio.
  }

  interrupt(): void {
    if (!this.connected) return
    this.turn++
    this.emit({ type: 'agent.state', state: 'listening' })
  }

  pause(): void {
    if (!this.connected || this.paused) return
    this.interrupt()
    this.paused = true
    this.stopInsights()
  }

  resume(): void {
    if (!this.connected || !this.paused) return
    this.paused = false
    this.startInsights()
  }

  close(): void {
    this.turn++
    this.stopInsights()
    this.timers.forEach(clearTimeout)
    this.timers.clear()
    this.connected = false
    this.paused = false
    this.emit({ type: 'agent.state', state: 'idle' })
  }

  // ---------------------------------------------------------------- internos
  private async streamAnswer(question: string, turn: number): Promise<void> {
    if (turn !== this.turn) return
    const answer = MOCK_ANSWERS[question.toLowerCase()] ?? FALLBACK_ANSWER
    const words = answer.split(' ')
    const id = this.nextId('a')
    this.emit({ type: 'agent.state', state: 'speaking' })
    for (let i = 1; i <= words.length; i++) {
      await this.sleep(WORD_DELAY_MS)
      if (turn !== this.turn) return // interrumpido: no se emite nada más
      this.emit({
        type: i < words.length ? 'transcript.partial' : 'transcript.final',
        id,
        speaker: AGENT,
        text: words.slice(0, i).join(' '),
        ts: Date.now(),
      })
    }
    this.emit({ type: 'agent.state', state: 'listening' })
  }

  private startInsights(): void {
    if (this.insightTimer) return
    this.insightTimer = setInterval(() => {
      const k = this.tick++
      const emotions: Record<string, number> = {}
      EMOTIONS.forEach((name, j) => {
        emotions[name] = Number((0.35 + 0.5 * Math.abs(Math.sin(k * 0.7 + j))).toFixed(2))
      })
      this.emit({
        type: 'insight',
        id: this.nextId('i'),
        sentiment: SENTIMENTS[k % SENTIMENTS.length],
        emotions,
      })
    }, INSIGHT_EVERY_MS)
  }

  private stopInsights(): void {
    if (this.insightTimer) clearInterval(this.insightTimer)
    this.insightTimer = null
  }

  private emit(e: ServerEvent): void {
    this.handlers.forEach((h) => h(e))
  }

  private nextId(prefix: string): string {
    return `${prefix}-${++this.seq}`
  }

  private sleep(ms: number): Promise<void> {
    return new Promise((resolve) => {
      const t = setTimeout(() => {
        this.timers.delete(t)
        resolve()
      }, ms)
      this.timers.add(t)
    })
  }
}
