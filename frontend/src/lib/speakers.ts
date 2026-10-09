import type { Speaker } from '@/api/types'

const PALETTE = ['text-violet-300', 'text-emerald-300', 'text-amber-300', 'text-rose-300']

export function speakerLabel(s: Speaker): string {
  if (s === 'agent') return 'Ivy'
  if (s === 'user') return 'Usuario'
  return `Hablante ${s.slice('speaker_'.length)}`
}

export function speakerColor(s: Speaker): string {
  if (s === 'agent') return 'text-cyan-300'
  if (s === 'user') return 'text-slate-300'
  const n = Number(s.slice('speaker_'.length))
  return PALETTE[(Number.isFinite(n) && n > 0 ? n - 1 : 0) % PALETTE.length] ?? 'text-violet-300'
}
