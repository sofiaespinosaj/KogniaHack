// Verificación en compilación: los tipos de la UI (types.ts) siguen al contrato GENERADO desde el
// backend (ws-events.gen.ts, copia de backend/contract/ws-events.ts; regenerar con `npm run contract`).
// Si el backend añade, quita o renombra un mensaje o un campo, `npm run build` falla aquí.
import type * as Gen from '@/api/ws-events.gen'
import type * as Ui from '@/api/types'

type Eq<A, B> = [A] extends [B] ? ([B] extends [A] ? true : false) : false
type Keys<T> = T extends unknown ? keyof T : never
type ByType<U, K> = Extract<U, { type: K }>
type SameKeys<K extends string> = Eq<Keys<ByType<Gen.ServerMessage, K>>, Keys<ByType<Ui.ServerEvent, K>>>

export const contractChecks: {
  serverTypes: Eq<Gen.ServerMessage['type'], Ui.ServerEvent['type']>
  clientTypes: Eq<Gen.ClientMessage['type'], Ui.ClientMessage['type']>
  protocol: Eq<typeof Gen.PROTOCOL_VERSION, '1.0'>
  fields: { [K in Ui.ServerEvent['type']]: SameKeys<K> }
} = {
  serverTypes: true,
  clientTypes: true,
  protocol: true,
  fields: {
    'session.state': true,
    'session.brief': true,
    'transcript.partial': true,
    'transcript.final': true,
    'agent.text': true,
    'audio.start': true,
    'audio.end': true,
    'audio.clear': true,
    'agent.tool': true,
    sentiment: true,
    metrics: true,
    error: true,
  },
}
