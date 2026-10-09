import { useEffect, useState } from 'react'
import type { AgentTurn } from '@/state/session'
import type { AgentTransport } from '@/services/transport'

const TICK_MS = 80
// La frase aparece un instante antes de sonar: leer y oír a la vez se siente natural.
const LEAD_MS = 250

/**
 * Texto del agente al ritmo de su voz, por frases completas: cada frase aparece entera cuando empieza a sonar
 * (el transporte sabe en qué punto del audio empieza cada una). El texto mostrado nunca retrocede, así que no
 * hay efecto de «escribir y borrar». Sin audio (mock, `audio_out` falso, turno interrumpido o ya terminado) se
 * muestra el texto completo.
 */
export function useSpokenText(
  transport: AgentTransport,
  turn: AgentTurn | undefined,
): { text: string; playing: boolean } {
  const [shown, setShown] = useState<{ turnId: string; chars: number; playing: boolean }>({
    turnId: '',
    chars: Infinity,
    playing: false,
  })
  const turnId = turn?.turnId

  useEffect(() => {
    if (!turnId || !transport.playbackProgress) return
    const tick = () => {
      const p = transport.playbackProgress?.()
      if (!p || p.turnId !== turnId || p.receivedMs <= 0 || p.marks.length === 0) {
        setShown((s) => (s.turnId === turnId && !s.playing ? s : { turnId, chars: Infinity, playing: false }))
        return
      }
      const at = p.playedMs + LEAD_MS
      let chars = 0
      for (const m of p.marks) if (m.ms <= at) chars = m.chars
      const playing = p.playedMs < p.receivedMs - 40
      setShown((s) => {
        const prev = s.turnId === turnId && Number.isFinite(s.chars) ? s.chars : 0
        const next = playing ? Math.max(prev, chars) : Infinity // nunca retrocede
        return s.turnId === turnId && s.chars === next && s.playing === playing ? s : { turnId, chars: next, playing }
      })
    }
    tick()
    const id = setInterval(tick, TICK_MS)
    return () => clearInterval(id)
  }, [transport, turnId])

  if (!turn) return { text: '', playing: false }
  if (turn.interrupted || shown.turnId !== turnId || !Number.isFinite(shown.chars)) {
    return { text: turn.text, playing: shown.turnId === turnId && shown.playing }
  }
  return { text: turn.text.slice(0, shown.chars).trimEnd(), playing: shown.playing }
}
