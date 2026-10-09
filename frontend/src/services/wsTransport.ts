import { PROTOCOL_VERSION, type ClientMessage, type ErrorEvent, type ServerEvent } from '@/api/types'
import { AudioPlayer, MicCapture } from '@/services/audio'
import type { AgentTransport } from '@/services/transport'

// Transporte real: un WebSocket con el backend (contrato ws v1.0).
// Frames binarios = audio PCM16 24 kHz (micrófono hacia el servidor, voz del agente hacia el cliente);
// frames de texto = JSON. Tras `audio.clear` se descartan los binarios hasta el siguiente `audio.start`.

const POSITION_EVERY_MS = 200
const RETRY_MS = 2000
const MAX_RETRIES = 3

type Handler = (e: ServerEvent) => void

/** URL del WebSocket: VITE_WS_URL o, por defecto, /ws en el mismo host (proxy de Vite en desarrollo). */
export function defaultWsUrl(): string {
  const env = import.meta.env.VITE_WS_URL as string | undefined
  if (env) return env
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${proto}//${location.host}/ws`
}

export class WsTransport implements AgentTransport {
  private ws: WebSocket | null = null
  private handlers = new Set<Handler>()
  private mic = new MicCapture()
  private player = new AudioPlayer()
  private discard = false
  private paused = false
  private closed = false
  private retries = 0
  private briefDone = false
  private timer: ReturnType<typeof setInterval> | null = null
  private localSeq = 0
  private micStarted = false
  private active = false // hay sesión de voz: solo entonces se envía audio del micrófono
  private readonly url: string

  constructor(url: string = defaultWsUrl()) {
    this.url = url
    const unlock = () => {
      // Política de autoplay: el audio arranca con el primer gesto del usuario.
      this.player.resume()
      this.mic.resume()
    }
    window.addEventListener('pointerdown', unlock)
    window.addEventListener('keydown', unlock)
  }

  on(handler: Handler): () => void {
    this.handlers.add(handler)
    return () => {
      this.handlers.delete(handler)
    }
  }

  async connect(): Promise<void> {
    this.closed = false
    this.open()
    if (!this.micStarted) {
      this.micStarted = true
      try {
        await this.mic.start((frame) => this.sendAudio(frame))
      } catch {
        this.local('No se pudo abrir el micrófono; puedes escribir tus preguntas con el teclado.')
      }
    }
  }

  private open(): void {
    const ws = new WebSocket(this.url)
    ws.binaryType = 'arraybuffer'
    this.ws = ws
    ws.onopen = () => {
      this.send({
        type: 'session.start',
        v: 1,
        protocol: PROTOCOL_VERSION,
        brief: this.briefDone ? 'skip' : 'speak', // al reconectar no se repite el brief
        audio_out: true,
      })
    }
    ws.onmessage = (e: MessageEvent<ArrayBuffer | string>) => {
      if (typeof e.data !== 'string') {
        if (!this.discard) this.player.push(e.data)
        return
      }
      this.onEvent(JSON.parse(e.data) as ServerEvent)
    }
    ws.onclose = () => {
      if (this.ws !== ws || this.closed) return
      this.ws = null
      this.active = false
      this.emit({ type: 'session.state', v: 1, seq: 0, state: 'error', detail: 'conexión perdida' })
      this.retry()
    }
  }

  private retry(): void {
    if (this.closed || this.retries >= MAX_RETRIES) return
    this.retries++
    setTimeout(() => {
      if (!this.closed && !this.ws) this.open()
    }, RETRY_MS)
  }

  private onEvent(e: ServerEvent): void {
    switch (e.type) {
      case 'session.brief':
        this.briefDone = true
        break
      case 'session.state':
        if (e.state === 'escuchando') this.retries = 0
        this.active = e.state !== 'error' && e.state !== 'conectando'
        break
      case 'audio.start':
        this.discard = false
        this.player.muted = this.paused
        this.player.beginTurn(e.turn_id)
        this.startPositions()
        break
      case 'audio.end':
        break
      case 'audio.clear':
        this.discard = true
        this.player.clear()
        this.stopPositions()
        break
      case 'error':
        if (e.severity === 'fatal') this.active = false
        // La voz falló (OpenAI): el WebSocket sigue abierto y se reintenta con un nuevo session.start.
        if (e.code === 'openai_unavailable' && e.recoverable && this.retries < MAX_RETRIES) {
          this.retries++
          setTimeout(() => this.send({
            type: 'session.start', v: 1, protocol: PROTOCOL_VERSION, brief: 'skip', audio_out: true,
          }), RETRY_MS)
        }
        break
    }
    this.emit(e)
  }

  private startPositions(): void {
    this.stopPositions()
    this.timer = setInterval(() => {
      const turnId = this.player.turnId
      if (!turnId) return
      this.send({ type: 'playback.position', v: 1, turn_id: turnId, played_ms: this.player.playedMs() })
      if (!this.player.playing && this.discard) this.stopPositions()
    }, POSITION_EVERY_MS)
  }

  private stopPositions(): void {
    if (this.timer) clearInterval(this.timer)
    this.timer = null
  }

  sendText(text: string): void {
    const q = text.trim()
    if (!q || this.paused) return
    this.send({ type: 'text.message', v: 1, text: q.slice(0, 500) })
  }

  sendAudio(chunk: ArrayBuffer): void {
    if (this.paused || !this.active || !this.ws || this.ws.readyState !== WebSocket.OPEN) return
    this.ws.send(chunk)
  }

  /** Silencia en el cliente lo que queda del turno; el corte en el servidor llega hablando encima (barge-in). */
  interrupt(): void {
    const turnId = this.player.turnId
    if (turnId) this.send({ type: 'playback.position', v: 1, turn_id: turnId, played_ms: this.player.playedMs() })
    this.discard = true
    this.player.clear()
  }

  /** Micrófono abierto o cerrado (manos libres). */
  setMicEnabled(on: boolean): void {
    this.mic.enabled = on
  }

  pause(): void {
    this.paused = true
    this.interrupt()
  }

  resume(): void {
    this.paused = false
  }

  close(): void {
    this.closed = true
    this.stopPositions()
    if (this.ws?.readyState === WebSocket.OPEN) this.send({ type: 'session.stop', v: 1 })
    this.ws?.close()
    this.ws = null
    this.mic.stop()
    this.micStarted = false
    this.player.close()
    this.player = new AudioPlayer()
  }

  /** Para diagnóstico y pruebas de extremo a extremo. */
  get stats(): { framesPlayed: number } {
    return { framesPlayed: this.player.framesPlayed }
  }

  private send(msg: ClientMessage): void {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg))
  }

  private local(message: string): void {
    const e: ErrorEvent = {
      type: 'error', v: 1, seq: --this.localSeq, code: 'internal', message, severity: 'warning', recoverable: true,
    }
    this.emit(e)
  }

  private emit(e: ServerEvent): void {
    this.handlers.forEach((h) => h(e))
  }
}
