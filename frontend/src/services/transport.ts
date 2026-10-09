import type { ServerEvent } from '@/api/types'

/** Avance del audio del turno y en qué punto del audio empieza cada tramo de texto (para el subtítulo). */
export interface PlaybackProgress {
  turnId: string
  playedMs: number
  receivedMs: number
  /** `chars` de texto disponibles a partir de `ms` de audio del turno. */
  marks: Array<{ chars: number; ms: number }>
}

// Contrato único entre la UI y el canal con el agente. La UI depende de esta interfaz,
// no del WebSocket concreto (MockTransport para demos sin backend, WsTransport con el backend).
export interface AgentTransport {
  connect(): Promise<void>
  sendText(text: string): void
  sendAudio(chunk: ArrayBuffer): void
  interrupt(): void
  pause(): void
  resume(): void
  close(): void
  /** Manos libres: abre o cierra el micrófono (opcional; el mock no tiene micrófono). */
  setMicEnabled?(on: boolean): void
  /** Cuánto audio del turno actual sonó y cuánto llegó; sin audio real (mock) no existe. */
  playbackProgress?(): PlaybackProgress | null
  on(handler: (e: ServerEvent) => void): () => void
}
