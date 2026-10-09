import { useEffect, useRef } from 'react'
import { cn } from '@/lib/cn'
import { speakerColor, speakerLabel } from '@/lib/speakers'
import type { SessionView } from '@/state/session'

interface Props {
  session: SessionView
  /** Texto del agente al ritmo de su voz (para el turno que está sonando). */
  spokenText: string
  spokenTurnId?: string
}

const SHOWN = 4 // últimas intervenciones visibles en la pantalla principal

/** Transcripción en vivo bajo el orbe: lo último que dijo cada parte, completo y legible. */
export function LiveTranscript({ session, spokenText, spokenTurnId }: Props) {
  const scroller = useRef<HTMLDivElement>(null)
  const keys = session.timeline.slice(-SHOWN)
  const emotionOf = Object.fromEntries(session.sentiments.map((x) => [x.utt_id, x.emotion]))
  const last = keys.at(-1)
  const lastText = last
    ? last.kind === 'utt'
      ? session.utterances[last.id]?.text
      : last.id === spokenTurnId
        ? spokenText
        : session.agentTurns[last.id]?.text
    : ''

  const newEntry = keys.length
  useEffect(() => {
    // salto inmediato mientras el texto crece (sin tirones); suave solo cuando entra una intervención nueva
    const el = scroller.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'auto' })
  }, [lastText])
  useEffect(() => {
    const el = scroller.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [newEntry])

  if (keys.length === 0) {
    const brief = session.brief?.texto
    return brief ? (
      <p className="mx-auto max-w-2xl px-2 text-center text-base leading-relaxed text-slate-200 sm:text-lg">{brief}</p>
    ) : null
  }

  return (
    <div
      ref={scroller}
      role="log"
      aria-live="polite"
      aria-label="Transcripción en vivo"
      className="thin-scroll mx-auto max-h-[32vh] w-full max-w-2xl space-y-2.5 overflow-y-auto px-1 pt-3"
      style={{ maskImage: 'linear-gradient(to bottom, transparent 0, black 24px)' }}
    >
      {keys.map((k) => {
        if (k.kind === 'utt') {
          const u = session.utterances[k.id]
          if (!u) return null
          return (
            <Entry
              key={`u-${k.id}`}
              who={speakerLabel(u.speaker) + (emotionOf[u.uttId] ? ` · ${emotionOf[u.uttId]}` : '')}
              color={speakerColor(u.speaker)}
              text={u.text}
              pending={!u.final}
              align="right"
            />
          )
        }
        const t = session.agentTurns[k.id]
        if (!t) return null
        const text = k.id === spokenTurnId ? spokenText : t.text
        if (!text) return null
        return (
          <Entry
            key={`a-${k.id}`}
            who="Lumi"
            color={speakerColor('agent')}
            text={text + (t.interrupted ? ' —' : '')}
            pending={!t.final}
            align="left"
          />
        )
      })}
    </div>
  )
}

function Entry(props: { who: string; color: string; text: string; pending: boolean; align: 'left' | 'right' }) {
  return (
    <div className={cn('flex', props.align === 'right' ? 'justify-end' : 'justify-start')}>
      <div
        className={cn(
          'max-w-[92%] rounded-2xl border px-4 py-2.5 shadow-lg backdrop-blur-md',
          props.align === 'right' ? 'border-white/10 bg-white/[0.07]' : 'border-cyan-200/10 bg-cyan-300/[0.06]',
        )}
      >
        <p className={cn('mb-0.5 text-[11px] font-semibold uppercase tracking-wider', props.color)}>{props.who}</p>
        <p
          className={cn(
            'text-base leading-relaxed transition-colors duration-200 sm:text-[17px]',
            props.pending ? 'text-slate-200' : 'text-slate-50',
          )}
        >
          {props.text}
          {props.pending && <span className="ml-1 inline-block animate-pulse text-cyan-200/60" aria-hidden>●</span>}
        </p>
      </div>
    </div>
  )
}
