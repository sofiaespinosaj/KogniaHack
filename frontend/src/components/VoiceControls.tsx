import { useState, type FormEvent } from 'react'
import { AudioLines, Keyboard, Mic, MicOff, Pause, Play, Send, Square } from 'lucide-react'
import type { SessionView } from '@/state/session'
import { cn } from '@/lib/cn'

interface Props {
  state: SessionView['state']
  paused: boolean
  handsFree: boolean
  questions: string[]
  onToggleHandsFree: () => void
  onTogglePaused: () => void
  onInterrupt: () => void
  onSend: (text: string) => void
  /** Solo con el mock: envía un frame de audio para simular que el usuario habla. */
  onSimulateSpeech?: () => void
}

const base =
  'inline-flex items-center gap-2 rounded-full px-3.5 py-2 text-sm font-medium transition duration-300 ' +
  'focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 ' +
  'disabled:cursor-not-allowed disabled:opacity-35'
const ghost = 'text-slate-200 hover:bg-white/10'

export function VoiceControls({
  state,
  paused,
  handsFree,
  questions,
  onToggleHandsFree,
  onTogglePaused,
  onInterrupt,
  onSend,
  onSimulateSpeech,
}: Props) {
  const [typing, setTyping] = useState(false)
  const [draft, setDraft] = useState('')
  const live = state !== 'idle' && state !== 'conectando' && state !== 'error'
  const canTalk = live && !paused
  const speaking = state === 'hablando' && !paused
  const canInterrupt = (state === 'hablando' || state === 'pensando') && !paused

  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (!canTalk || !draft.trim()) return
    onSend(draft)
    setDraft('')
  }

  return (
    <section aria-label="Controles de conversación" className="flex w-full max-w-3xl flex-col items-center gap-3">
      {questions.length > 0 && (
        <ul aria-label="Preguntas sugeridas" className="flex flex-wrap justify-center gap-2">
          {questions.map((q) => (
            <li key={q}>
              <button
                type="button"
                disabled={!canTalk}
                onClick={() => onSend(q)}
                className={cn(
                  base,
                  'glass glass-hover px-3 py-1.5 text-[13px] font-normal text-cyan-50/90 shadow-lg',
                )}
              >
                {q}
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="flex max-w-full flex-wrap items-center justify-center gap-1 rounded-[1.75rem] border border-white/10 bg-white/[0.06] px-2.5 py-1.5 shadow-2xl shadow-indigo-950/30 backdrop-blur-xl sm:rounded-full">
        <button
          type="button"
          aria-pressed={handsFree}
          onClick={onToggleHandsFree}
          title="Manos libres: el micrófono queda abierto entre turnos"
          className={cn(base, handsFree ? 'bg-emerald-300/15 text-emerald-100' : ghost)}
        >
          {handsFree ? <Mic className="size-4" aria-hidden /> : <MicOff className="size-4" aria-hidden />}
          <span className="hidden sm:inline">Manos libres</span>
        </button>

        <button type="button" onClick={onTogglePaused} disabled={!live} className={cn(base, ghost)}>
          {paused ? <Play className="size-4" aria-hidden /> : <Pause className="size-4" aria-hidden />}
          {paused ? 'Reanudar' : 'Pausar'}
        </button>

        <button
          type="button"
          onClick={onInterrupt}
          disabled={!canInterrupt}
          className={cn(
            base,
            speaking
              ? 'bg-rose-300/20 text-rose-100 ring-1 ring-rose-300/50 shadow-[0_0_20px_rgb(251_113_133/0.25)]'
              : ghost,
          )}
        >
          <Square className="size-4" aria-hidden />
          Interrumpir
        </button>

        {onSimulateSpeech && (
          <button
            type="button"
            onClick={onSimulateSpeech}
            disabled={!canTalk || !handsFree}
            title="Demo: simula que hablas (el micrófono real se conecta con el WebSocket)"
            className={cn(base, 'bg-cyan-300/15 text-cyan-100 hover:bg-cyan-300/25')}
          >
            <AudioLines className="size-4" aria-hidden />
            Simular voz
          </button>
        )}

        <button
          type="button"
          aria-pressed={typing}
          aria-label="Escribir una pregunta"
          onClick={() => setTyping(!typing)}
          className={cn(base, 'px-3', typing ? 'bg-white/15 text-white' : ghost)}
        >
          <Keyboard className="size-4" aria-hidden />
        </button>

        {typing && (
          <form onSubmit={submit} className="flex min-w-0 basis-full items-center gap-1 sm:basis-auto">
            <label htmlFor="text-message" className="sr-only">
              Escribe una pregunta
            </label>
            <input
              id="text-message"
              autoFocus
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              disabled={!canTalk}
              maxLength={500}
              placeholder={paused ? 'Conversación en pausa' : 'Escribe tu pregunta…'}
              className="w-full min-w-0 rounded-full bg-white/[0.06] px-4 py-2 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:outline-2 focus-visible:outline-cyan-300 disabled:opacity-40 sm:w-56"
            />
            <button
              type="submit"
              disabled={!canTalk || !draft.trim()}
              aria-label="Enviar pregunta"
              className={cn(base, ghost, 'px-3')}
            >
              <Send className="size-4" aria-hidden />
            </button>
          </form>
        )}
      </div>
    </section>
  )
}
