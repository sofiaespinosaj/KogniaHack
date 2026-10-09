import { useEffect, useRef, type ReactNode } from 'react'
import { X } from 'lucide-react'
import { cn } from '@/lib/cn'

interface Props {
  side: 'left' | 'right'
  open: boolean
  onClose: () => void
  title: string
  icon: ReactNode
  children: ReactNode
}

/** Slide-over de vidrio. Se cierra con la X, con Escape o con un clic fuera. */
export function Drawer({ side, open, onClose, title, icon, children }: Props) {
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    if (!open) return
    closeRef.current?.focus()
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  return (
    <>
      <div
        aria-hidden
        onClick={onClose}
        className={cn(
          'fixed inset-0 z-30 bg-slate-950/40 backdrop-blur-[2px] transition-opacity duration-300 motion-reduce:transition-none',
          open ? 'opacity-100' : 'pointer-events-none opacity-0',
        )}
      />
      <aside
        role="dialog"
        aria-label={title}
        aria-hidden={!open}
        inert={!open}
        className={cn(
          'glass fixed inset-y-0 z-40 flex w-[min(26rem,92vw)] flex-col bg-slate-900/70 transition-transform duration-300 ease-out motion-reduce:transition-none',
          side === 'left' ? 'left-0 rounded-r-3xl border-l-0' : 'right-0 rounded-l-3xl border-r-0',
          open ? 'translate-x-0' : side === 'left' ? '-translate-x-full' : 'translate-x-full',
        )}
      >
        <header className="flex shrink-0 items-center justify-between gap-3 px-5 pb-3 pt-5">
          <h2 className="flex items-center gap-2 text-sm font-semibold tracking-wide text-slate-100">
            {icon}
            {title}
          </h2>
          <button
            ref={closeRef}
            type="button"
            onClick={onClose}
            aria-label={`Cerrar ${title}`}
            className="glass glass-hover grid size-8 place-items-center rounded-full text-slate-300 focus-visible:outline-2 focus-visible:outline-cyan-300"
          >
            <X className="size-4" aria-hidden />
          </button>
        </header>
        <div className="flex min-h-0 flex-1 flex-col">{children}</div>
      </aside>
    </>
  )
}
