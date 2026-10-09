import type { ReactNode } from 'react'
import { Database, Gauge, HeartPulse, TriangleAlert, Zap } from 'lucide-react'
import { perceivedLatencyMs, type ToolResult } from '@/api/types'
import { Drawer } from '@/components/Drawer'
import { cn } from '@/lib/cn'
import { formatDate, formatNumber } from '@/lib/format'
import { speakerLabel } from '@/lib/speakers'
import type { SessionView, ToolCall } from '@/state/session'

interface Props {
  open: boolean
  onClose: () => void
  session: SessionView
}

/** Telemetría para el jurado: latencia de voz, sentimiento/emociones y evidencia de las tools. */
export function InsightsDrawer({ open, onClose, session }: Props) {
  const latest = session.sentiments.at(-1)
  const metrics = Object.values(session.metrics).at(-1)

  return (
    <Drawer
      side="right"
      open={open}
      onClose={onClose}
      title="Live Insights · Jurado"
      icon={<Zap className="size-4 text-cyan-300" aria-hidden />}
    >
      <div className="thin-scroll flex-1 space-y-4 overflow-y-auto px-5 pb-6 pt-1">
        <Card title="Latencia de voz · último turno" icon={<Gauge className="size-4" aria-hidden />}>
          {metrics ? (
            <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm">
              <Stat label="Primer audio" value={metrics.first_audio_ms} unit="ms" />
              <Stat label="Silencio VAD" value={metrics.vad_silence_ms} unit="ms" />
              <Stat label="Latencia percibida" value={perceivedLatencyMs(metrics) ?? undefined} unit="ms" strong />
              <Stat label="Tool" value={metrics.tool_ms} unit="ms" />
              <Stat label="Total del turno" value={metrics.total_ms} unit="ms" />
              {metrics.interrupted && <Stat label="Turno" text="interrumpido" />}
            </dl>
          ) : (
            <Empty>Se muestra al terminar el primer turno.</Empty>
          )}
        </Card>

        <Card title="Sentimiento y emoción" icon={<HeartPulse className="size-4" aria-hidden />}>
          {latest ? (
            <>
              <div className="flex items-baseline justify-between gap-3">
                <p className="text-2xl font-semibold capitalize text-white">{latest.emotion}</p>
                <p className="text-right text-xs text-slate-400">
                  {latest.sentiment} · {speakerLabel(latest.speaker)}
                </p>
              </div>
              <ScoreBar score={latest.score} />
              <Sparkline scores={session.sentiments.map((s) => s.score)} />
            </>
          ) : (
            <Empty>Llega tras cada enunciado final, sin bloquear la voz.</Empty>
          )}
        </Card>

        <Card title="Evidencia del dataset" icon={<Database className="size-4" aria-hidden />}>
          {session.tools.length === 0 ? (
            <Empty>Cuando el agente consulte DuckDB, verás aquí el resultado que respalda su respuesta.</Empty>
          ) : (
            <ul className="space-y-3">
              {[...session.tools].reverse().map((t) => (
                <li key={`${t.turn_id}-${t.call_id}`}>
                  <ToolCard call={t} />
                </li>
              ))}
            </ul>
          )}
        </Card>

        {session.issues.length > 0 && (
          <Card title="Avisos" icon={<TriangleAlert className="size-4" aria-hidden />}>
            <ul className="space-y-2 text-sm">
              {session.issues.map((i) => (
                <li key={i.seq} className={i.severity === 'fatal' ? 'text-rose-300' : 'text-amber-300'}>
                  {i.message}
                </li>
              ))}
            </ul>
          </Card>
        )}
      </div>
    </Drawer>
  )
}

function Card(props: { title: string; icon: ReactNode; children: ReactNode }) {
  return (
    <section className="rounded-2xl border border-white/[0.06] bg-white/[0.04] p-4">
      <h3 className="mb-3 flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-400">
        {props.icon}
        {props.title}
      </h3>
      <div className="space-y-3">{props.children}</div>
    </section>
  )
}

const Empty = ({ children }: { children: ReactNode }) => <p className="text-sm text-slate-400">{children}</p>

function Stat(props: { label: string; value?: number; unit?: string; text?: string; strong?: boolean }) {
  const shown = props.text ?? (props.value === undefined ? '—' : `${formatNumber(props.value)} ${props.unit ?? ''}`)
  return (
    <div className="min-w-0">
      <dt className="text-xs text-slate-500">{props.label}</dt>
      <dd className={cn('truncate font-mono', props.strong ? 'text-cyan-300' : 'text-slate-200')}>{shown}</dd>
    </div>
  )
}

/** Puntaje -1..1 sobre una barra negativo ← → positivo. */
function ScoreBar({ score }: { score: number }) {
  const pct = ((Math.max(-1, Math.min(1, score)) + 1) / 2) * 100
  return (
    <div>
      <div
        role="meter"
        aria-label="Puntaje de sentimiento"
        aria-valuemin={-1}
        aria-valuemax={1}
        aria-valuenow={score}
        className="relative h-2 rounded-full bg-gradient-to-r from-rose-400/40 via-slate-400/30 to-emerald-400/50"
      >
        <span
          className="absolute top-1/2 size-3.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white bg-slate-900 transition-[left] duration-700"
          style={{ left: `${pct}%` }}
        />
      </div>
      <div className="mt-1.5 flex justify-between text-[10px] text-slate-500">
        <span>negativo</span>
        <span className="font-mono text-slate-300">{score.toFixed(2)}</span>
        <span>positivo</span>
      </div>
    </div>
  )
}

function Sparkline({ scores }: { scores: number[] }) {
  if (scores.length < 2) return null
  const w = 240
  const h = 36
  const pts = scores
    .map((s, i) => `${(i / (scores.length - 1)) * w},${h / 2 - (Math.max(-1, Math.min(1, s)) * (h - 6)) / 2}`)
    .join(' ')
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-9 w-full" role="img" aria-label="Evolución del sentimiento">
      <line x1="0" x2={w} y1={h / 2} y2={h / 2} className="stroke-white/10" strokeDasharray="3 3" />
      <polyline points={pts} fill="none" className="stroke-cyan-300" strokeWidth="2" strokeLinejoin="round" />
    </svg>
  )
}

function ToolCard({ call }: { call: ToolCall }) {
  const r: ToolResult | undefined = call.summary
  const valor = typeof r?.valor === 'number' ? formatNumber(r.valor) : undefined
  const estado = call.status === 'done' ? (r?.estado ?? 'ok') : call.status === 'running' ? 'consultando' : 'error'
  return (
    <div className="rounded-xl border border-white/[0.08] bg-slate-950/40 p-3 text-sm">
      <div className="mb-2 flex items-center justify-between gap-2">
        <code className="font-mono text-cyan-300">{call.name}</code>
        <span
          className={cn(
            'rounded-full px-2 py-0.5 text-[10px] uppercase tracking-wider',
            estado === 'ok' && 'bg-emerald-400/15 text-emerald-200',
            estado === 'consultando' && 'animate-pulse bg-indigo-400/15 text-indigo-200',
            estado === 'error' && 'bg-rose-400/15 text-rose-200',
            !['ok', 'consultando', 'error'].includes(estado) && 'bg-amber-400/15 text-amber-200',
          )}
        >
          {estado}
        </span>
      </div>
      <p className="break-all font-mono text-xs text-slate-400">{JSON.stringify(call.args)}</p>
      {r && (
        <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-2 text-xs">
          {valor && <Stat label="Valor" text={valor} strong />}
          {r.filas_usadas !== undefined && <Stat label="Filas usadas" text={formatNumber(r.filas_usadas)} />}
          {r.fecha_corte && <Stat label="Fecha de corte" text={formatDate(r.fecha_corte)} />}
          {r.origen && <Stat label="Origen" text={r.origen} />}
          {r.filtros && (
            <Stat label="Filtros" text={Object.entries(r.filtros).map(([k, v]) => `${k}: ${v}`).join(', ')} />
          )}
        </dl>
      )}
      {r?.nota && <p className="mt-2 text-xs text-amber-300">{r.nota}</p>}
    </div>
  )
}
