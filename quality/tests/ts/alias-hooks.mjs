// Resolución de módulos para ejecutar el código TypeScript del frontend con `node --test` sin dependencias:
// - el alias `@/` apunta a frontend/src/ (igual que vite.config.ts y tsconfig.app.json);
// - los imports sin extensión prueban `.ts` y `.tsx` (Node exige la extensión en ESM).
// Node 24 elimina los tipos de TypeScript de forma nativa.
import { existsSync } from 'node:fs'
import { fileURLToPath, pathToFileURL } from 'node:url'

const SRC = fileURLToPath(new URL('../../../frontend/src/', import.meta.url))

function withExtension(path) {
  for (const candidate of [path, `${path}.ts`, `${path}.tsx`, `${path}/index.ts`]) {
    if (existsSync(candidate)) return candidate
  }
  return null
}

export async function resolve(specifier, context, nextResolve) {
  if (specifier.startsWith('@/')) {
    const file = withExtension(SRC + specifier.slice(2))
    if (file) return { url: pathToFileURL(file).href, shortCircuit: true }
  }
  if ((specifier.startsWith('./') || specifier.startsWith('../')) && context.parentURL?.endsWith('.ts')) {
    const base = fileURLToPath(new URL(specifier, context.parentURL))
    const file = withExtension(base)
    if (file) return { url: pathToFileURL(file).href, shortCircuit: true }
  }
  return nextResolve(specifier, context)
}
