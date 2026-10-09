import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from 'react'
import type { AgentTransport } from '@/services/transport'
import { initialSession, sessionReducer } from '@/state/session'

export type OrbState = 'listening' | 'thinking' | 'speaking' | 'paused'

/** Conecta un AgentTransport con la UI: estado de sesión derivado de los eventos del contrato. */
export function useAgentSession(transport: AgentTransport) {
  const [session, dispatch] = useReducer(sessionReducer, initialSession)
  const [paused, setPaused] = useState(false)
  const [handsFree, setHandsFree] = useState(true)
  const startedAt = useRef(0)

  useEffect(() => {
    dispatch({ type: 'reset' })
    startedAt.current = Date.now()
    const off = transport.on((event) => {
      // `ts` del servidor cuenta desde el inicio de la sesión: el reloj local se alinea con él.
      if (event.type === 'session.state' && event.state === 'conectando') startedAt.current = Date.now()
      dispatch({ type: 'event', event, at: Date.now() - startedAt.current })
    })
    void transport.connect()
    return () => {
      off()
      transport.close()
    }
  }, [transport])

  useEffect(() => {
    transport.setMicEnabled?.(handsFree && !paused)
  }, [transport, handsFree, paused])

  const sendText = useCallback((text: string) => transport.sendText(text), [transport])
  const interrupt = useCallback(() => transport.interrupt(), [transport])
  // Un chunk de PCM16 de 40 ms (1.920 bytes, silencio): lo usa el mock para simular que el usuario habla.
  const simulateSpeech = useCallback(() => transport.sendAudio(new ArrayBuffer(1920)), [transport])

  const togglePaused = useCallback(() => {
    if (paused) transport.resume()
    else transport.pause()
    setPaused(!paused)
  }, [paused, transport])

  const orb: OrbState = useMemo(() => {
    if (paused) return 'paused'
    switch (session.state) {
      case 'escuchando':
      case 'listo':
        return 'listening'
      case 'pensando':
      case 'conectando':
        return 'thinking'
      case 'hablando':
        return 'speaking'
      default:
        return 'paused'
    }
  }, [paused, session.state])

  return {
    session,
    orb,
    paused,
    handsFree,
    setHandsFree,
    togglePaused,
    sendText,
    interrupt,
    simulateSpeech,
  }
}
