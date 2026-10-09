import { useEffect, useState } from 'react'
import type { AgentTurn } from '@/state/session'
import type { AgentTransport } from '@/services/transport'

const TICK_MS = 50
// El subtítulo va un poco por delante de la voz: leer y oír a la vez se siente natural, ir detrás se siente lento.
const LEAD_MS = 700

/**
 * Texto del agente al ritmo de su voz. OpenAI entrega el texto y el audio más rápido que tiempo real,
 * así que se muestra la parte del texto proporcional al audio ya reproducido (cortada en una palabra).
 * Sin audio (mock, `audio_out` falso o turno interrumpido) se muestra el texto completo.
 */
export function useSpokenText(
  transport: AgentTransport,
  turn: AgentTurn | undefined,
): { text: string; playing: boolean } {
  const [fraction, setFraction] = useState(1)
  const turnId = turn?.turnId

  useEffect(() => {
    if (!turnId || !transport.playbackProgress) return
    const tick = () => {
      const p = transport.playbackProgress?.()
      if (!p || p.turnId !== turnId || p.receivedMs <= 0) setFraction(1)
      else setFraction(Math.min(1, (p.playedMs + LEAD_MS) / p.receivedMs))
    }
    tick()
    const id = setInterval(tick, TICK_MS)
    return () => clearInterval(id)
  }, [transport, turnId])

  if (!turn) return { text: '', playing: false }
  if (turn.interrupted || fraction >= 1) return { text: turn.text, playing: false }
  return { text: cutAtWord(turn.text, Math.round(turn.text.length * fraction)), playing: true }
}

/** Corta en la palabra siguiente (no en la anterior): el texto nunca se queda atrás de lo que suena. */
function cutAtWord(text: string, n: number): string {
  if (n >= text.length) return text
  const next = text.indexOf(' ', n)
  return next < 0 ? text : text.slice(0, next)
}
