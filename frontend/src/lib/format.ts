/** ms desde el inicio de la sesión -> "mm:ss". */
export function formatClock(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000))
  const m = String(Math.floor(total / 60)).padStart(2, '0')
  const s = String(total % 60).padStart(2, '0')
  return `${m}:${s}`
}

const nf = new Intl.NumberFormat('es-CO')
export const formatNumber = (n: number) => nf.format(n)

/** "2022-11-05" -> "5 de noviembre de 2022". */
export function formatDate(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number)
  return new Intl.DateTimeFormat('es-CO', { day: 'numeric', month: 'long', year: 'numeric' }).format(
    new Date(y, m - 1, d),
  )
}
