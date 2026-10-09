import type { ServerEvent } from '@/api/types'

// Contrato único entre la UI y el canal con el agente. La UI depende de esta interfaz,
// no del WebSocket concreto (MockTransport hoy, WsTransport cuando exista `realtime-voice`).
export interface AgentTransport {
  connect(): Promise<void>
  sendText(text: string): void
  sendAudio(chunk: ArrayBuffer): void
  interrupt(): void
  pause(): void
  resume(): void
  close(): void
  on(handler: (e: ServerEvent) => void): () => void
}
