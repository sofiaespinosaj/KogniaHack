import { useCallback, useState } from 'react'
import { MessageSquare, Zap } from 'lucide-react'
import { ConversationDrawer } from '@/components/ConversationDrawer'
import { InsightsDrawer } from '@/components/InsightsDrawer'
import { VoiceControls } from '@/components/VoiceControls'
import { WaterRipplesOrb } from '@/components/WaterRipplesOrb'
import { useAgentSession } from '@/hooks/useAgentSession'
import { cn } from '@/lib/cn'
import { formatDate } from '@/lib/format'
import { ORB_LABELS } from '@/lib/orb'
import { MockTransport } from '@/services/mockTransport'

// Hasta que exista el WsTransport (conexión al backend), toda la UI corre sobre el mock.
const transport = new MockTransport()

type Panel = 'conversation' | 'insights' | null

const pill =
  'glass glass-hover inline-flex items-center gap-2 rounded-full px-3.5 py-2 text-sm text-slate-100 ' +
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300'

export default function App() {
  const s = useAgentSession(transport)
  const [panel, setPanel] = useState<Panel>(null)
  const closePanel = useCallback(() => setPanel(null), [])
  const { session } = s

  // Lo que se muestra en la cápsula: la última respuesta del agente o, al inicio, el brief.
  const lastAgentKey = [...session.timeline].reverse().find((k) => k.kind === 'agent')
  const lastAgent = lastAgentKey ? session.agentTurns[lastAgentKey.id] : undefined
  const caption = lastAgent?.text ?? session.brief?.texto ?? ''
  const warning = session.issues.at(-1)

  const connected = session.state !== 'idle' && session.state !== 'conectando' && session.state !== 'error'
  const mic = s.paused ? 'En pausa' : s.handsFree ? 'Micrófono abierto' : 'Micrófono cerrado'

  return (
    <div className="flex h-screen max-h-screen flex-col overflow-hidden bg-gradient-to-b from-slate-950 via-[#0b1329] to-slate-950">
      <header className="flex shrink-0 items-center justify-between gap-3 px-4 py-3 sm:px-8 sm:py-4">
        <div className="min-w-0">
          <h1 className="truncate text-sm font-semibold tracking-[0.08em] text-slate-100 sm:text-base">
            Kognia Vocal · IPS Colombia
          </h1>
          <p className="mt-0.5 flex items-center gap-2 truncate text-xs text-slate-400">
            <span
              aria-hidden
              className={cn(
                'size-1.5 shrink-0 rounded-full',
                session.state === 'error' ? 'bg-rose-400' : connected ? 'bg-emerald-300' : 'bg-slate-500',
              )}
            />
            <span>{session.state === 'error' ? 'Error' : connected ? 'Conectado' : 'Conectando'}</span>
            <span aria-hidden>·</span>
            <span>{mic}</span>
            <span className="rounded-full bg-white/10 px-1.5 py-px text-[10px] uppercase tracking-wider">mock</span>
            {session.brief && (
              <span className="hidden truncate md:inline">
                · corte {formatDate(session.brief.fecha_corte)} · {session.brief.origen}
              </span>
            )}
          </p>
        </div>

        <nav aria-label="Paneles" className="flex shrink-0 gap-2">
          <button type="button" onClick={() => setPanel('conversation')} className={pill} aria-label="Historial de conversación">
            <MessageSquare className="size-4 text-cyan-300" aria-hidden />
            <span className="hidden sm:inline">Historial de Conversación</span>
          </button>
          <button type="button" onClick={() => setPanel('insights')} className={pill} aria-label="Live Insights (Jurado)">
            <Zap className="size-4 text-cyan-300" aria-hidden />
            <span className="hidden sm:inline">Live Insights (Jurado)</span>
          </button>
        </nav>
      </header>

      <main className="flex min-h-0 flex-1 flex-col items-center justify-between gap-3 px-4 pb-5 sm:px-8 sm:pb-7">
        <div className="flex min-h-0 w-full flex-1 flex-col items-center justify-center gap-3">
          <WaterRipplesOrb state={s.orb} className="h-[min(46vh,30rem)] shrink" />

          <div className="flex shrink-0 flex-col items-center gap-2.5">
            <p role="status" aria-live="polite" className="text-xs font-medium uppercase tracking-[0.28em] text-cyan-100/70">
              {ORB_LABELS[s.orb]}
            </p>
            {caption && (
              <p
                aria-live="polite"
                className={cn(
                  'glass mx-auto max-w-xl px-6 py-2.5 text-center text-sm leading-relaxed text-slate-100 shadow-lg backdrop-blur-md sm:text-[15px]',
                  'bg-white/[0.05] border-white/10',
                  caption.length > 70 ? 'rounded-3xl' : 'rounded-full',
                )}
              >
                <span className="line-clamp-4">{caption}</span>
              </p>
            )}
            {warning && (
              <p
                role="alert"
                className={cn(
                  'rounded-full border px-4 py-1.5 text-xs',
                  warning.severity === 'fatal'
                    ? 'border-rose-300/30 bg-rose-400/10 text-rose-100'
                    : 'border-amber-300/30 bg-amber-400/10 text-amber-100',
                )}
              >
                {warning.message}
              </p>
            )}
          </div>
        </div>

        <VoiceControls
          state={session.state}
          paused={s.paused}
          handsFree={s.handsFree}
          questions={session.brief?.preguntas ?? []}
          onToggleHandsFree={() => s.setHandsFree(!s.handsFree)}
          onTogglePaused={s.togglePaused}
          onInterrupt={s.interrupt}
          onSend={s.sendText}
          onSimulateSpeech={s.simulateSpeech}
        />
      </main>

      <ConversationDrawer open={panel === 'conversation'} onClose={closePanel} session={session} />
      <InsightsDrawer open={panel === 'insights'} onClose={closePanel} session={session} />
    </div>
  )
}
