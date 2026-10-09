import type { OrbState } from '@/hooks/useAgentSession'

export const ORB_LABELS: Record<OrbState, string> = {
  listening: 'Escuchando',
  thinking: 'Pensando',
  speaking: 'Hablando',
  paused: 'En pausa',
}
