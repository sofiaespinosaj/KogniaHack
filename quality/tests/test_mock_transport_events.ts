// Contrato del MockTransport frente a ws-event-contract v1.0
// (openspec/changes/realtime-voice/specs/ws-event-contract/spec.md).
//
// Ejecutar desde la raíz del repo (Node 24, sin dependencias):
//   node --test --import ./quality/tests/ts/register.mjs quality/tests/test_mock_transport_events.ts
//
// Los relojes (setTimeout y Date) están simulados: las pruebas son deterministas y tardan milisegundos.
// Además se guarda la traza completa de eventos en quality/reports/mock_events_trace.json, que la suite de
// Python valida contra el JSON Schema publicado por el backend (backend/contract/ws-events.schema.json).
import assert from 'node:assert/strict'
import { mkdirSync, writeFileSync } from 'node:fs'
import { after, afterEach, beforeEach, describe, mock, test } from 'node:test'

import type { ServerEvent } from '../../frontend/src/api/types.ts'
import { MockTransport } from '../../frontend/src/services/mockTransport.ts'

type Ev = ServerEvent & Record<string, unknown>
type Session = { t: MockTransport; events: Ev[] }

const TRACE: Record<string, Ev[]> = {}

/** Avanza el reloj simulado en pasos pequeños dejando correr las promesas pendientes. */
async function advance(ms: number, step = 10): Promise<void> {
  for (let elapsed = 0; elapsed < ms; elapsed += step) {
    mock.timers.tick(step)
    await new Promise<void>((resolve) => setImmediate(resolve))
  }
}

async function open(name: string): Promise<Session> {
  const t = new MockTransport()
  const events: Ev[] = []
  t.on((e) => events.push(structuredClone(e) as Ev))
  TRACE[name] = events
  const connecting = t.connect()
  await advance(4000) // conexión (250 ms) + brief hablado (3,5 s)
  await connecting
  return { t, events }
}

const types = (events: Ev[]) => events.map((e) => e.type)
const states = (events: Ev[]) => events.filter((e) => e.type === 'session.state').map((e) => e.state)
const since = (events: Ev[], n: number) => events.slice(n)
const idx = (events: Ev[], pred: (e: Ev) => boolean) => events.findIndex(pred)

beforeEach(() => mock.timers.enable({ apis: ['setTimeout', 'Date'], now: 0 }))
afterEach(() => mock.timers.reset())
after(() => {
  const dir = new URL('../reports/', import.meta.url)
  mkdirSync(dir, { recursive: true })
  writeFileSync(new URL('mock_events_trace.json', dir), JSON.stringify(TRACE, null, 2) + '\n', 'utf8')
})

describe('Inicio de sesión y brief', () => {
  test('secuencia: conectando → listo → session.brief → audio del brief → escuchando', async () => {
    const { events, t } = await open('inicio')
    assert.deepEqual(types(events), [
      'session.state', 'session.state', 'session.brief', 'audio.start', 'session.state', 'audio.end', 'session.state',
    ])
    assert.deepEqual(states(events), ['conectando', 'listo', 'hablando', 'escuchando'])
    t.close()
  })

  test('session.state «listo» anuncia el protocolo 1.0', async () => {
    const { events, t } = await open('protocolo')
    const listo = events.find((e) => e.type === 'session.state' && e.state === 'listo')!
    assert.equal(listo.protocol, '1.0')
    t.close()
  })

  test('session.brief: turno t-0000, 3 a 5 preguntas, fecha de corte y origen', async () => {
    const { events, t } = await open('brief')
    const brief = events.find((e) => e.type === 'session.brief')!
    assert.equal(brief.turn_id, 't-0000')
    assert.ok(typeof brief.texto === 'string' && brief.texto.length > 0)
    const preguntas = brief.preguntas as string[]
    assert.ok(preguntas.length >= 3 && preguntas.length <= 5, `preguntas: ${preguntas.length}`)
    assert.equal(brief.fecha_corte, '2022-11-05')
    assert.ok(['snapshot', 'api'].includes(brief.origen as string))
    const audio = events.find((e) => e.type === 'audio.start')!
    assert.equal(audio.turn_id, 't-0000')
    assert.equal(audio.format, 'pcm16')
    assert.equal(audio.sample_rate, 24000)
    t.close()
  })
})

describe('Estructura de todos los mensajes', () => {
  test('cada mensaje lleva v = 1 y seq estrictamente creciente desde 1', async () => {
    const { events, t } = await open('estructura')
    t.sendAudio(new ArrayBuffer(1920))
    await advance(4000)
    events.forEach((e, i) => {
      assert.equal(e.v, 1)
      assert.equal(e.seq, i + 1)
    })
    t.close()
  })

  test('no existe un evento «insight»: el contrato v1.0 lo llama «sentiment»', async () => {
    const { events, t } = await open('sin-insight')
    t.sendAudio(new ArrayBuffer(1920))
    await advance(4000)
    assert.ok(!types(events).includes('insight' as Ev['type']))
    assert.ok(types(events).includes('sentiment'))
    t.close()
  })
})

describe('Turno por voz completo', () => {
  test('orden: partial → final → pensando → tool running/done → audio.start → hablando → texto final → audio.end → metrics → escuchando', async () => {
    const { events, t } = await open('turno-voz')
    const start = events.length
    t.sendAudio(new ArrayBuffer(1920))
    await advance(4000)
    const turn = since(events, start).filter((e) => e.type !== 'sentiment')
    const order = turn.map((e) => (e.type === 'session.state' ? `state:${e.state}` : e.type === 'agent.tool' ? `tool:${e.status}` : e.type))
    const compact = order.filter((x, i) => !(x === 'agent.text' && order[i + 1] === 'agent.text'))
    assert.deepEqual(compact, [
      'transcript.partial', 'transcript.final', 'state:pensando', 'tool:running', 'tool:done',
      'audio.start', 'state:hablando', 'agent.text', 'audio.end', 'metrics', 'state:escuchando',
    ])
    t.close()
  })

  test('parcial y final comparten turn_id y utt_id; ts_end ≥ ts; hablante diarizado', async () => {
    const { events, t } = await open('transcripcion')
    t.sendAudio(new ArrayBuffer(1920))
    await advance(4000)
    const partial = events.find((e) => e.type === 'transcript.partial')!
    const final = events.find((e) => e.type === 'transcript.final')!
    assert.equal(partial.turn_id, final.turn_id)
    assert.equal(partial.utt_id, final.utt_id)
    assert.ok((final.ts_end as number) >= (final.ts as number))
    assert.match(final.speaker as string, /^speaker_\d+$/)
    assert.equal(final.source, 'deepgram')
    assert.equal(final.degraded, false)
    t.close()
  })

  test('agent.tool «done» trae la evidencia: valor, filtros, filas_usadas, fecha_corte, origen y estado', async () => {
    const { events, t } = await open('evidencia')
    t.sendAudio(new ArrayBuffer(1920))
    await advance(4000)
    const tools = events.filter((e) => e.type === 'agent.tool')
    assert.deepEqual(tools.map((e) => e.status), ['running', 'done'])
    assert.equal(tools[0].call_id, tools[1].call_id)
    const summary = tools[1].summary as Record<string, unknown>
    for (const key of ['valor', 'filtros', 'filas_usadas', 'fecha_corte', 'origen', 'estado']) {
      assert.ok(key in summary, `falta ${key}`)
    }
    assert.ok(!JSON.stringify(tools).toLowerCase().includes('select'), 'el evento no expone SQL')
    t.close()
  })

  test('agent.text es acumulado y solo el último es final', async () => {
    const { events, t } = await open('texto-acumulado')
    t.sendAudio(new ArrayBuffer(1920))
    await advance(4000)
    const texts = events.filter((e) => e.type === 'agent.text')
    assert.ok(texts.length > 1)
    texts.slice(1).forEach((e, i) => assert.ok((e.text as string).startsWith(texts[i].text as string)))
    assert.deepEqual(texts.map((e) => e.final), [...Array(texts.length - 1).fill(false), true])
    assert.ok(texts.every((e) => e.interrupted === false))
    t.close()
  })

  test('metrics: latencia percibida = vad_silence_ms + first_audio_ms', async () => {
    const { events, t } = await open('metricas')
    t.sendAudio(new ArrayBuffer(1920))
    await advance(4000)
    const m = events.find((e) => e.type === 'metrics')!
    assert.equal((m.vad_silence_ms as number) + (m.first_audio_ms as number), 1620)
    assert.ok((m.total_ms as number) > 0)
    t.close()
  })

  test('sentiment llega después del transcript.final del mismo enunciado, con score en [-1, 1]', async () => {
    const { events, t } = await open('sentimiento')
    t.sendAudio(new ArrayBuffer(1920))
    await advance(4000)
    const final = idx(events, (e) => e.type === 'transcript.final')
    const sIdx = idx(events, (e) => e.type === 'sentiment')
    assert.ok(sIdx > final)
    const s = events[sIdx]
    assert.equal(s.utt_id, events[final].utt_id)
    assert.equal(s.turn_id, events[final].turn_id)
    assert.ok((s.score as number) >= -1 && (s.score as number) <= 1)
    t.close()
  })
})

describe('Turno por texto', () => {
  test('text.message: sin parciales, transcript.final con source «text» y hablante «user»', async () => {
    const { events, t } = await open('turno-texto')
    const start = events.length
    t.sendText('¿Cuántas IPS hay en total?')
    await advance(4000)
    const turn = since(events, start)
    assert.ok(!types(turn).includes('transcript.partial'))
    const final = turn.find((e) => e.type === 'transcript.final')!
    assert.equal(final.source, 'text')
    assert.equal(final.speaker, 'user')
    assert.equal(final.text, '¿Cuántas IPS hay en total?')
    t.close()
  })

  test('los turnos se numeran t-0001, t-0002… y los enunciados u-0001, u-0002…', async () => {
    const { events, t } = await open('numeracion')
    t.sendText('primera')
    await advance(4000)
    t.sendText('segunda')
    await advance(4000)
    const finals = events.filter((e) => e.type === 'transcript.final')
    assert.deepEqual(finals.map((e) => e.turn_id), ['t-0001', 't-0002'])
    assert.deepEqual(finals.map((e) => e.utt_id), ['u-0001', 'u-0002'])
    t.close()
  })
})

describe('Interrupciones (barge-in)', () => {
  test('mientras habla: audio.clear → agent.text final interrumpido (prefijo de lo dicho) → escuchando', async () => {
    const { events, t } = await open('barge-in-hablando')
    t.sendAudio(new ArrayBuffer(1920))
    await advance(1700) // ya pasó la tool y empezó a hablar
    const before = events.length
    t.interrupt()
    const cut = since(events, before)
    assert.deepEqual(types(cut), ['audio.clear', 'agent.text', 'session.state'])
    const turnId = cut[0].turn_id
    assert.equal(cut[1].turn_id, turnId)
    assert.equal(cut[1].final, true)
    assert.equal(cut[1].interrupted, true)
    assert.ok('En Antioquia hay unas 840 IPS'.startsWith(cut[1].text as string))
    assert.equal(cut[2].state, 'escuchando')
    t.close()
  })

  test('después de audio.clear no llega más texto ni audio de ese turno', async () => {
    const { events, t } = await open('sin-audio-viejo')
    t.sendAudio(new ArrayBuffer(1920))
    await advance(1700)
    t.interrupt()
    const after = events.length
    await advance(4000)
    const late = since(events, after).filter((e) => e.type !== 'sentiment')
    assert.deepEqual(late, [], `eventos tardíos: ${types(late).join(', ')}`)
    t.close()
  })

  test('antes del primer audio: metrics con interrupted y sin first_audio_ms; sin audio.clear', async () => {
    const { events, t } = await open('barge-in-pensando')
    t.sendText('pregunta')
    await advance(100) // pensando, la tool aún no termina
    const before = events.length
    t.interrupt()
    const cut = since(events, before)
    assert.ok(!types(cut).includes('audio.clear'))
    const m = cut.find((e) => e.type === 'metrics')!
    assert.equal(m.interrupted, true)
    assert.ok(!('first_audio_ms' in m))
    t.close()
  })

  test('hablar encima del agente interrumpe y abre un turno nuevo', async () => {
    const { events, t } = await open('barge-in-por-voz')
    t.sendAudio(new ArrayBuffer(1920))
    await advance(1700)
    const before = events.length
    t.sendAudio(new ArrayBuffer(1920))
    await advance(4000)
    const cut = since(events, before)
    assert.equal(cut[0].type, 'audio.clear')
    const finals = cut.filter((e) => e.type === 'transcript.final')
    assert.equal(finals.length, 1)
    assert.notEqual(finals[0].turn_id, cut[0].turn_id)
    t.close()
  })

  test('interrumpir el brief corta su audio con audio.clear de t-0000', async () => {
    const t = new MockTransport()
    const events: Ev[] = []
    t.on((e) => events.push(e as Ev))
    const connecting = t.connect()
    await advance(1000) // el brief está sonando
    t.interrupt()
    await advance(4000)
    await connecting
    const clear = events.find((e) => e.type === 'audio.clear')!
    assert.equal(clear.turn_id, 't-0000')
    assert.ok(!types(events).includes('audio.end'), 'el brief interrumpido no termina con audio.end')
    t.close()
  })
})

describe('Pausa y cierre', () => {
  test('en pausa no se aceptan turnos; al reanudar sí', async () => {
    const { events, t } = await open('pausa')
    t.pause()
    const paused = events.length
    t.sendText('¿me escuchas?')
    t.sendAudio(new ArrayBuffer(1920))
    await advance(4000)
    assert.equal(events.length, paused)
    t.resume()
    t.sendText('¿y ahora?')
    await advance(4000)
    assert.ok(types(since(events, paused)).includes('transcript.final'))
    t.close()
  })

  test('después de close no se emite nada', async () => {
    const { events, t } = await open('cierre')
    t.sendAudio(new ArrayBuffer(1920))
    await advance(500)
    t.close()
    const closed = events.length
    await advance(5000)
    assert.equal(events.length, closed)
  })
})
