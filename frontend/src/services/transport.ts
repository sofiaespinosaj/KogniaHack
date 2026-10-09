import type { ServerEvent } from '@/api/types'

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
  on(handler: (e: ServerEvent) => void): () => void
}
