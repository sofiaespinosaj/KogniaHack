import { useEffect, useState } from 'react'
import type { AgentTurn } from '@/state/session'
import type { AgentTransport } from '@/services/transport'

const TICK_MS = 100

/**
 * Texto del agente al ritmo de su voz. OpenAI entrega el texto y el audio más rápido que tiempo real,
 * así que se muestra la parte del texto proporcional al audio ya reproducido (cortada en una palabra).
 * Sin audio (mock, `audio_out` falso o turno interrumpido) se muestra el texto completo.
 */
export function useSpokenText(transport: AgentTransport, turn: AgentTurn | undefined): string {
  const [fraction, setFraction] = useState(1)
  const turnId = turn?.turnId

  useEffect(() => {
    if (!turnId || !transport.playbackProgress) return
    const tick = () => {
      const p = transport.playbackProgress?.()
      if (!p || p.turnId !== turnId || p.receivedMs <= 0) setFraction(1)
      else setFraction(Math.min(1, p.playedMs / p.receivedMs))
    }
    tick()
    const id = setInterval(tick, TICK_MS)
    return () => clearInterval(id)
  }, [transport, turnId])

  if (!turn) return ''
  if (turn.interrupted || fraction >= 1) return turn.text
  return cutAtWord(turn.text, Math.round(turn.text.length * fraction))
}

function cutAtWord(text: string, n: number): string {
  if (n >= text.length) return text
  const cut = text.lastIndexOf(' ', n)
  return cut > 0 ? text.slice(0, cut) : ''
}
