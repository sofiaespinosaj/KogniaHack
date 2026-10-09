import { Mic } from 'lucide-react'
import { cn } from '@/lib/cn'

export default function App() {
  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center gap-4 px-4">
      <Mic className={cn('size-10', 'text-indigo-500')} aria-hidden />
      <h1 className="text-2xl font-semibold">Agente Vocal – IPS Colombia</h1>
      <p className="text-slate-500">Base del frontend lista (Sprint 1).</p>
    </main>
  )
}
