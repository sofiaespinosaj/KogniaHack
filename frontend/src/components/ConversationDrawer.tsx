import { useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, MessageSquare } from 'lucide-react'
import type { Speaker } from '@/api/types'
import { Drawer } from '@/components/Drawer'
import { cn } from '@/lib/cn'
import { formatClock } from '@/lib/format'
import { speakerColor, speakerLabel } from '@/lib/speakers'
import type { SessionView } from '@/state/session'

interface Props {
  open: boolean
  onClose: () => void
  session: SessionView
}

/** Historial: solo el flujo de transcripción diarizada (usuario y agente). */
export function ConversationDrawer({ open, onClose, session }: Props) {
  const scroller = useRef<HTMLDivElement>(null)
  const [pinned, setPinned] = useState(true) // sigue al final salvo que la persona suba
  const count = session.timeline.length
  const emotionOf = useMemo(
    () => Object.fromEntries(session.sentiments.map((x) => [x.utt_id, x.emotion])),
    [session.sentiments],
  )

  const lastText = useMemo(() => {
    const k = session.timeline[count - 1]
    if (!k) return ''
    return k.kind === 'utt' ? session.utterances[k.id]?.text : session.agentTurns[k.id]?.text
  }, [session, count])

  useEffect(() => {
    const el = scroller.current
    if (open && pinned && el) el.scrollTo({ top: el.scrollHeight, behavior: 'smooth' })
  }, [open, count, lastText, pinned])

  const onScroll = () => {
    const el = scroller.current
    if (el) setPinned(el.scrollHeight - el.scrollTop - el.clientHeight < 48)
  }

  return (
    <Drawer
      side="left"
      open={open}
      onClose={onClose}
      title="Historial de conversación"
      icon={<MessageSquare className="size-4 text-cyan-300" aria-hidden />}
    >
      <div className="relative flex min-h-0 flex-1 flex-col">
        <div
          ref={scroller}
          onScroll={onScroll}
          role="log"
          aria-live="polite"
          aria-label="Transcripción de la conversación"
          className="thin-scroll flex-1 space-y-3 overflow-y-auto px-5 pb-6 pt-1"
        >
          {count === 0 && (
            <p className="pt-8 text-center text-sm text-slate-400">
              Aún no hay conversación. Habla o elige una pregunta sugerida.
            </p>
          )}
          {session.timeline.map((k) => {
            if (k.kind === 'utt') {
              const u = session.utterances[k.id]
              if (!u) return null
              return (
                <Line
                  key={`u-${k.id}`}
                  speaker={u.speaker}
                  at={u.ts}
                  text={u.text}
                  pending={!u.final}
                  badges={[
                    emotionOf[u.uttId] ?? null,
                    u.source === 'text' ? 'texto' : null,
                    u.degraded ? 'degradado' : null,
                  ]}
                />
              )
            }
            const t = session.agentTurns[k.id]
            if (!t) return null
            return (
              <Line
                key={`a-${k.id}`}
                speaker="agent"
                at={t.at}
                text={t.text}
                pending={!t.final}
                badges={[t.interrupted ? 'interrumpido' : null]}
              />
            )
          })}
        </div>
        {!pinned && (
          <button
            type="button"
            onClick={() => setPinned(true)}
            className="glass glass-hover absolute bottom-4 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full px-3.5 py-1.5 text-xs text-slate-100 focus-visible:outline-2 focus-visible:outline-cyan-300"
          >
            <ArrowDown className="size-3.5" aria-hidden /> Ir al final
          </button>
        )}
      </div>
    </Drawer>
  )
}

function Line(props: {
  speaker: Speaker
  at: number
  text: string
  pending: boolean
  badges: Array<string | null>
}) {
  return (
    <article className="rounded-2xl border border-white/[0.06] bg-white/[0.04] px-3.5 py-3">
      <header className="mb-1 flex items-center gap-2 text-xs">
        <span className={cn('font-semibold', speakerColor(props.speaker))}>{speakerLabel(props.speaker)}</span>
        <time className="font-mono text-slate-500">{formatClock(props.at)}</time>
        {props.badges.filter(Boolean).map((b) => (
          <span key={b} className="rounded-full bg-white/10 px-2 py-0.5 text-[10px] uppercase tracking-wider text-slate-300">
            {b}
          </span>
        ))}
      </header>
      <p className={cn('text-[15px] leading-relaxed', props.pending ? 'text-slate-300' : 'text-slate-50')}>
        {props.text}
        {props.pending && <span aria-hidden> …</span>}
      </p>
    </article>
  )
}
