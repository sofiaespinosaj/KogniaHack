import type { CSSProperties } from 'react'
import type { OrbState } from '@/hooks/useAgentSession'
import { cn } from '@/lib/cn'
import { ORB_LABELS } from '@/lib/orb'

const RIPPLES = [0, 1, 2, 3]

interface Props {
  state: OrbState
  className?: string
}

/**
 * Presencia líquida: un núcleo de agua que cambia de forma lentamente y ondas de estanque
 * que se desvanecen. Cian en calma, índigo al pensar, jade al hablar, apagado en pausa.
 */
export function WaterRipplesOrb({ state, className }: Props) {
  return (
    <div
      role="img"
      aria-label={`Agente: ${ORB_LABELS[state].toLowerCase()}`}
      data-state={state}
      className={cn('orb relative aspect-square select-none', className)}
    >
      {RIPPLES.map((i) => (
        <span key={i} className="orb-ripple" style={{ '--i': i } as CSSProperties} />
      ))}
      <div className="orb-water" />
      <div className="orb-water orb-water--b" />
    </div>
  )
}
