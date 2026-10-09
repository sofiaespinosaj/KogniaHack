// Prueba de extremo a extremo: navegador (micrófono falso) -> frontend -> backend -> OpenAI/Deepgram simulados.
// Se ejecuta con scripts/e2e_local.sh, que levanta los servicios y genera el audio del micrófono.
const { chromium } = require('playwright')
const OUT = process.env.E2E_OUT || '.'
const MIC = process.env.E2E_MIC_WAV
const BASE = process.env.E2E_URL || 'http://localhost:5173/'
;(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || undefined,
    args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream',
      `--use-file-for-fake-audio-capture=${MIC}`, '--autoplay-policy=no-user-gesture-required'],
  })
  const page = await browser.newPage()
  const ws = [], sent = [], sockets = []
  page.on('websocket', (s) => {
    const mine = []; sockets.push(mine)
    s.on('framereceived', (f) => { if (typeof f.payload === 'string') { const m = JSON.parse(f.payload); ws.push(m); mine.push(m.seq) } })
    s.on('framesent', (f) => { if (typeof f.payload === 'string') sent.push(JSON.parse(f.payload)) })
  })
  page.on('console', (m) => { if (m.type() === 'error') console.log('console:', m.text()) })
  await page.goto(BASE)
  const ok = (c, msg) => { if (!c) { throw new Error('FALLA: ' + msg) } console.log('OK  ', msg) }
  await page.waitForFunction(() => document.body.innerText.includes('9.320 IPS'), null, { timeout: 15000 })
  ok(true, 'brief visible en la UI')
  await page.waitForFunction(() => window.__kogniaTransport.stats.framesPlayed > 10, null, { timeout: 15000 })
  ok(true, 'audio del brief reproducido: ' + (await page.evaluate(() => window.__kogniaTransport.stats.framesPlayed)) + ' frames')
  await page.waitForFunction(() => /escuch/i.test(document.body.innerText), null, { timeout: 20000 })
  await page.screenshot({ path: `${OUT}/e2e-1-brief.png` })
  // pregunta sugerida (text.message)
  await page.getByRole('button', { name: '¿Cuántas IPS hay en total?' }).first().click()
  await page.waitForFunction(() => document.body.innerText.includes('Según el dataset hay'), null, { timeout: 15000 })
  ok(true, 'respuesta del agente a la pregunta sugerida')
  const tool = ws.find((m) => m.type === 'agent.tool' && m.status === 'done')
  ok(tool && tool.summary.valor === 9320, 'agent.tool count_ips = 9320')
  await page.waitForTimeout(1500)
  // metrics llega al terminar el turno
  ok(ws.some((m) => m.type === 'metrics' && m.first_audio_ms != null), 'metrics con first_audio_ms')
  // voz por el micrófono falso: Deepgram simulado etiqueta speaker_1
  const t0 = Date.now()
  while (!ws.some((m) => m.type === 'transcript.final' && m.source === 'deepgram') && Date.now() - t0 < 25000) await page.waitForTimeout(250)
  const fin = ws.find((m) => m.type === 'transcript.final' && m.source === 'deepgram')
  ok(fin && fin.speaker === 'speaker_1', 'transcripción por voz con hablante: ' + (fin && fin.speaker) + ' «' + (fin && fin.text) + '»')
  while (!ws.some((m) => m.type === 'metrics' && m.vad_silence_ms === 500) && Date.now() - t0 < 30000) await page.waitForTimeout(250)
  ok(ws.some((m) => m.type === 'metrics' && m.vad_silence_ms === 500), 'turno de voz completo con metrics (vad_silence_ms=500)')
  ok(sent.some((m) => m.type === 'playback.position'), 'playback.position enviado')
  await page.getByRole('button', { name: /Historial de conversación/i }).click()
  await page.waitForTimeout(500)
  const txt = await page.innerText('body')
  ok(/Hablante 1/.test(txt), 'historial muestra «Hablante 1»')
  await page.screenshot({ path: `${OUT}/e2e-2-historial.png` })
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: /Live Insights/i }).click()
  await page.waitForTimeout(500)
  await page.screenshot({ path: `${OUT}/e2e-3-insights.png` })
  const live = sockets.filter((x) => x.length).at(-1)
  ok(live.every((s, i) => i === 0 || s > live[i - 1]), 'seq estrictamente creciente en la conexión (' + live.length + ' eventos, ' + sockets.length + ' sockets)')
  await browser.close()
})().catch((e) => { console.error(e.message); process.exit(1) })
