import { AUDIO_FRAME_BYTES, AUDIO_SAMPLE_RATE } from '@/api/types'

// Audio del contrato: PCM16 mono 24 kHz little-endian en frames de 40 ms (1.920 bytes).

const CAPTURE_WORKLET = `
class Pcm16Capture extends AudioWorkletProcessor {
  constructor() { super(); this.buf = new Int16Array(${AUDIO_FRAME_BYTES / 2}); this.n = 0 }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0]
    if (!ch) return true
    for (let i = 0; i < ch.length; i++) {
      const s = Math.max(-1, Math.min(1, ch[i]))
      this.buf[this.n++] = s < 0 ? s * 0x8000 : s * 0x7fff
      if (this.n === this.buf.length) {
        this.port.postMessage(this.buf.buffer.slice(0))
        this.n = 0
      }
    }
    return true
  }
}
registerProcessor('pcm16-capture', Pcm16Capture)
`

/** Micrófono -> frames PCM16 de 40 ms. El navegador remuestrea a 24 kHz y cancela el eco. */
export class MicCapture {
  private ctx: AudioContext | null = null
  private stream: MediaStream | null = null
  private gen = 0
  enabled = true

  async start(onFrame: (frame: ArrayBuffer) => void): Promise<void> {
    // Si stop() llega mientras se esperan permisos o el worklet, esta captura se descarta.
    const gen = ++this.gen
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    })
    if (gen !== this.gen) {
      stream.getTracks().forEach((t) => t.stop())
      return
    }
    const ctx = new AudioContext({ sampleRate: AUDIO_SAMPLE_RATE })
    this.stream = stream
    this.ctx = ctx
    const url = URL.createObjectURL(new Blob([CAPTURE_WORKLET], { type: 'application/javascript' }))
    await ctx.audioWorklet.addModule(url)
    URL.revokeObjectURL(url)
    if (gen !== this.gen) return
    const src = ctx.createMediaStreamSource(stream)
    const node = new AudioWorkletNode(ctx, 'pcm16-capture')
    node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
      if (this.enabled && gen === this.gen) onFrame(e.data)
    }
    src.connect(node)
    // Sin conexión al destino el grafo no siempre se procesa: se conecta con ganancia 0.
    const mute = ctx.createGain()
    mute.gain.value = 0
    node.connect(mute).connect(ctx.destination)
    if (ctx.state === 'suspended') await ctx.resume().catch(() => undefined)
  }

  resume(): void {
    if (this.ctx?.state === 'suspended') void this.ctx.resume()
  }

  stop(): void {
    this.gen++
    this.stream?.getTracks().forEach((t) => t.stop())
    void this.ctx?.close()
    this.ctx = null
    this.stream = null
  }
}

/** Reproduce los frames del agente en orden y sabe cuánto del turno se ha escuchado. */
export class AudioPlayer {
  private ctx: AudioContext | null = null
  private sources = new Set<AudioBufferSourceNode>()
  private nextAt = 0
  private turnStartAt: number | null = null
  private scheduledMs = 0
  turnId: string | null = null
  muted = false
  /** Frames recibidos de verdad reproducidos (para pruebas y diagnóstico). */
  framesPlayed = 0

  private context(): AudioContext {
    if (!this.ctx) this.ctx = new AudioContext({ sampleRate: AUDIO_SAMPLE_RATE })
    if (this.ctx.state === 'suspended') void this.ctx.resume().catch(() => undefined)
    return this.ctx
  }

  resume(): void {
    this.context()
  }

  beginTurn(turnId: string): void {
    this.turnId = turnId
    this.turnStartAt = null
    this.scheduledMs = 0
  }

  push(frame: ArrayBuffer): void {
    if (this.muted) return
    const ctx = this.context()
    const pcm = new Int16Array(frame)
    const buf = ctx.createBuffer(1, pcm.length, AUDIO_SAMPLE_RATE)
    const ch = buf.getChannelData(0)
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 0x8000
    const src = ctx.createBufferSource()
    src.buffer = buf
    src.connect(ctx.destination)
    const at = Math.max(ctx.currentTime + 0.02, this.nextAt)
    if (this.turnStartAt === null) this.turnStartAt = at
    src.start(at)
    this.nextAt = at + buf.duration
    this.scheduledMs += buf.duration * 1000
    this.framesPlayed++
    this.sources.add(src)
    src.onended = () => this.sources.delete(src)
  }

  /** Milisegundos del turno actual que ya sonaron. */
  playedMs(): number {
    if (!this.ctx || this.turnStartAt === null) return 0
    const ms = (this.ctx.currentTime - this.turnStartAt) * 1000
    return Math.round(Math.max(0, Math.min(ms, this.scheduledMs)))
  }

  get playing(): boolean {
    return this.sources.size > 0
  }

  /** Vacía la cola: lo pendiente no suena. */
  clear(): void {
    this.sources.forEach((s) => {
      try {
        s.stop()
      } catch {
        /* ya terminó */
      }
    })
    this.sources.clear()
    this.nextAt = 0
  }

  close(): void {
    this.clear()
    void this.ctx?.close()
    this.ctx = null
  }
}
