import { useEffect, useRef, useState } from 'react'
import { MicVAD } from '@ricky0123/vad-web'
import InlineChart from './InlineChart'
import BizumConfirmModal from './BizumConfirmModal'
import InvestmentConfirmModal from './InvestmentConfirmModal'
import { apiStream, decideAction, readSSE } from '../services/api'
import { SentenceSplitter, SpeechQueue, transcribeSpeech } from '../services/voice'

// Modo conversación: el VAD (Silero, en el navegador) detecta cuándo empiezas y
// terminas de hablar, así que no hay que pulsar para parar. Tras cada respuesta el
// micro se vuelve a abrir solo, hasta cerrar el modal o pasar un rato en silencio.
//
//   listening ──(empiezas a hablar)──► hearing ──(700 ms de silencio)──► processing
//       ▲                                                                    │
//       └──────────────(termina de hablar el asistente)──── speaking ◄───────┘
//
// Mientras procesa y habla, el micro está en pausa para no captarse a sí mismo,
// salvo que se active "interrumpir hablando" (recomendable solo con auriculares).

const SILENCE_TIMEOUT_MS = 20000
const BARGE_IN_KEY = 'voice.bargeIn'

const PHASES = {
  loading: {
    label: 'Preparando micrófono...',
    hint: null,
    orbColor: '#444444',
    glowColor: 'rgba(68,68,68,0.35)',
    animation: 'orb-spin 1.2s linear infinite',
  },
  idle: {
    label: 'Conversación en pausa',
    hint: 'Toca para seguir hablando',
    orbColor: '#00A651',
    glowColor: 'rgba(0,166,81,0.45)',
    animation: 'orb-idle 2.4s ease-in-out infinite',
  },
  listening: {
    label: 'Te escucho',
    hint: 'Habla cuando quieras · Toca para pausar',
    orbColor: '#00A651',
    glowColor: 'rgba(0,166,81,0.45)',
    animation: 'none',
  },
  hearing: {
    label: 'Escuchando...',
    hint: 'Cuando termines, haz una pausa',
    orbColor: '#E53E3E',
    glowColor: 'rgba(229,62,62,0.45)',
    animation: 'none',
  },
  processing: {
    label: 'Pensando...',
    hint: null,
    orbColor: '#444444',
    glowColor: 'rgba(68,68,68,0.35)',
    animation: 'orb-spin 1.2s linear infinite',
  },
  speaking: {
    label: 'Respondiendo...',
    hint: 'Toca para interrumpir',
    orbColor: '#00A651',
    glowColor: 'rgba(0,166,81,0.45)',
    animation: 'orb-idle 0.9s ease-in-out infinite',
  },
  confirm: {
    label: 'Confirma la operación en pantalla',
    hint: null,
    orbColor: '#444444',
    glowColor: 'rgba(68,68,68,0.25)',
    animation: 'none',
  },
}

// destroy() falla si el VAD nunca llegó a arrancar (no hay stream que cerrar)
function destroyVAD(vad) {
  vad.destroy().catch(() => {})
}

function readBargeIn() {
  try { return localStorage.getItem(BARGE_IN_KEY) === '1' } catch { return false }
}

export default function VoiceModal({ history, onClose, onComplete }) {
  const [phase, setPhaseState] = useState('loading')
  const [orbScale, setOrbScale] = useState(1)
  const [chartInfo, setChartInfo] = useState(null)
  const [transcript, setTranscript] = useState('')
  const [error, setError] = useState('')
  const [pendingBizum, setPendingBizum] = useState(null)
  const [pendingInvestment, setPendingInvestment] = useState(null)
  const [bargeIn, setBargeIn] = useState(readBargeIn)

  // Los callbacks del VAD se registran una sola vez: todo lo que leen va por refs
  const phaseRef = useRef('loading')
  const bargeInRef = useRef(bargeIn)
  const vadRef = useRef(null)
  const speechRef = useRef(null)        // SpeechQueue de la respuesta en curso
  const abortRef = useRef(null)         // AbortController del stream en curso
  const turnRef = useRef(0)             // se incrementa al interrumpir: invalida el turno anterior
  const silenceTimerRef = useRef(null)
  const closedRef = useRef(false)
  const historyRef = useRef(history || [])
  const pendingContextRef = useRef(null) // texto del usuario que originó la operación pendiente

  function setPhase(p) {
    phaseRef.current = p
    setPhaseState(p)
    if (p !== 'listening' && p !== 'hearing') setOrbScale(1)
  }

  // ── Ciclo de vida del VAD ───────────────────────────────────────────────────

  useEffect(() => {
    // En desarrollo, StrictMode monta, desmonta y vuelve a montar: los refs sobreviven
    let cancelled = false
    closedRef.current = false
    MicVAD.new({
      model: 'v5',
      baseAssetPath: '/vad/',
      onnxWASMBasePath: '/vad/',
      startOnLoad: false,
      positiveSpeechThreshold: 0.5,
      negativeSpeechThreshold: 0.35,
      redemptionMs: 700,      // silencio que marca el final del turno
      minSpeechMs: 300,       // más corto que esto es ruido (tos, golpe)
      preSpeechPadMs: 300,    // audio previo que se incluye para no cortar la primera sílaba
      // El micro se pide con cancelación de eco y supresión de ruido (valores por
      // defecto de la librería), lo que reduce que capte la voz del propio asistente
      onSpeechStart: () => handlers.current.onSpeechStart(),
      onSpeechEnd: audio => handlers.current.onSpeechEnd(audio),
      onVADMisfire: () => handlers.current.onMisfire(),
      onFrameProcessed: (_probs, frame) => handlers.current.onFrame(frame),
    })
      .then(vad => {
        if (cancelled) { destroyVAD(vad); return }
        vadRef.current = vad
        resumeListening()
      })
      .catch(err => {
        if (!cancelled) onMicError(err)
      })

    return () => {
      cancelled = true
      closedRef.current = true
      clearTimeout(silenceTimerRef.current)
      speechRef.current?.stop()
      abortRef.current?.abort()
      if (vadRef.current) destroyVAD(vadRef.current)
      vadRef.current = null
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function resumeListening() {
    if (closedRef.current || pendingContextRef.current || !vadRef.current) return
    setPhase('listening')
    // El primer start() es el que pide permiso de micrófono
    vadRef.current.start().catch(onMicError)
    armSilenceTimer()
  }

  function onMicError(err) {
    console.error('[VoiceModal] micrófono/VAD', err)
    clearTimeout(silenceTimerRef.current)
    setError('No se pudo acceder al micrófono. Revisa los permisos del navegador.')
    setPhase('idle')
  }

  function pauseConversation() {
    clearTimeout(silenceTimerRef.current)
    vadRef.current?.pause()
    setPhase('idle')
  }

  // Si nadie habla en un rato, se pausa la conversación (no deja el micro abierto)
  function armSilenceTimer() {
    clearTimeout(silenceTimerRef.current)
    silenceTimerRef.current = setTimeout(() => {
      if (phaseRef.current === 'listening') pauseConversation()
    }, SILENCE_TIMEOUT_MS)
  }

  // Corta la respuesta en curso (audio y stream) y deja que mande el nuevo turno
  function interrupt() {
    turnRef.current += 1
    speechRef.current?.stop()
    abortRef.current?.abort()
  }

  // ── Eventos del VAD ─────────────────────────────────────────────────────────

  const handlers = useRef({})
  handlers.current = {
    onSpeechStart() {
      const p = phaseRef.current
      if (p === 'speaking' || p === 'processing') {
        if (!bargeInRef.current) return
        interrupt()
      } else if (p !== 'listening') {
        return
      }
      clearTimeout(silenceTimerRef.current)
      setError('')
      setPhase('hearing')
    },
    onMisfire() {
      if (phaseRef.current === 'hearing') resumeListening()
    },
    onSpeechEnd(audio) {
      if (phaseRef.current !== 'hearing') return
      vadRef.current?.pause()
      setPhase('processing')
      runTurn(audio)
    },
    onFrame(frame) {
      const p = phaseRef.current
      if (p !== 'listening' && p !== 'hearing') return
      let sum = 0
      for (let i = 0; i < frame.length; i++) sum += frame[i] * frame[i]
      const rms = Math.sqrt(sum / frame.length)
      setOrbScale(1 + Math.min(rms * 8, 0.45))
    },
  }

  // ── Un turno: transcribir → agente → hablar ─────────────────────────────────

  async function runTurn(audio) {
    const turn = turnRef.current
    try {
      const userText = await transcribeSpeech(audio)
      if (turn !== turnRef.current) return
      if (!userText) { resumeListening(); return }
      setTranscript(userText)
      setChartInfo(null)

      const controller = new AbortController()
      abortRef.current = controller
      const res = await apiStream(
        '/chat/stream',
        { message: userText, history: historyRef.current, voice_mode: true },
        { signal: controller.signal },
      )
      if (!res.ok) throw new Error('Chat fallido')
      await speakResponse(res, userText, turn)
    } catch (err) {
      if (turn !== turnRef.current || err.name === 'AbortError') return
      console.error('[VoiceModal]', err)
      setError('Algo ha fallado. Prueba otra vez.')
      resumeListening()
    }
  }

  // Lee la respuesta en streaming y la va diciendo frase a frase mientras llega.
  // Si el agente propone una operación, en vez de hablar muestra la tarjeta.
  async function speakResponse(res, userText, turn) {
    const splitter = new SentenceSplitter()
    const queue = new SpeechQueue({
      onStart: () => {
        if (turn !== turnRef.current) return
        setPhase('speaking')
        // Con interrupción activada, el micro escucha mientras habla el asistente
        if (bargeInRef.current) vadRef.current?.start().catch(onMicError)
      },
    })
    speechRef.current = queue

    let text = ''
    let chart = null
    let pending = null
    try {
      await readSSE(res, ev => {
        if (ev.type === 'token') {
          text += ev.text
          splitter.push(ev.text).forEach(s => queue.push(s))
        } else if (ev.type === 'done') {
          pending = ev.pending_action
          if (ev.chart_type && ev.chart_data?.length) {
            chart = { type: ev.chart_type, data: ev.chart_data, title: ev.chart_title }
          }
        } else if (ev.type === 'error') {
          text = ev.text
          queue.push(ev.text)
        }
      })
    } catch (err) {
      if (err.name !== 'AbortError') throw err
    }
    queue.push(splitter.flush())
    queue.close()

    if (pending) {
      queue.stop()
      pendingContextRef.current = { userText }
      clearTimeout(silenceTimerRef.current)
      vadRef.current?.pause()
      if (pending.type === 'bizum_confirm') setPendingBizum(pending)
      else setPendingInvestment(pending)
      setPhase('confirm')
      return
    }

    // Se guarda el turno aunque se haya interrumpido: el asistente llegó a decirlo
    if (text.trim()) recordTurn(userText, text.trim(), chart)
    if (chart && turn === turnRef.current) setChartInfo(chart)

    await queue.done
    if (turn === turnRef.current && phaseRef.current !== 'hearing') resumeListening()
  }

  function recordTurn(userText, assistantText, chart) {
    historyRef.current = [
      ...historyRef.current,
      { role: 'user', content: userText },
      { role: 'assistant', content: assistantText },
    ]
    onComplete({
      userText,
      assistantText,
      chartType: chart?.type ?? null,
      chartData: chart?.data ?? null,
      chartTitle: chart?.title ?? null,
    })
  }

  // ── Tarjeta de confirmación ─────────────────────────────────────────────────

  // Aprobar o rechazar la operación propuesta. Va al backend con el action_id (nunca
  // por voz: una frase mal transcrita no puede aprobar un pago) y el agente responde
  // hablando con el resultado. Después se reanuda la conversación.
  async function handleActionDecision(action, decision) {
    // Guard de reentrancia: un segundo tap tras vaciar el ref (p.ej. doble clic en
    // confirmar/cancelar) ya no tiene contexto que leer — se ignora en vez de lanzar.
    if (!pendingContextRef.current) return
    const { userText } = pendingContextRef.current
    pendingContextRef.current = null
    setPendingBizum(null)
    setPendingInvestment(null)
    setPhase('processing')
    const turn = ++turnRef.current
    try {
      const controller = new AbortController()
      abortRef.current = controller
      const res = await decideAction(action.action_id, decision, { signal: controller.signal })
      if (res.ok) {
        await speakResponse(res, userText, turn)
      } else {
        const err = await res.json().catch(() => ({}))
        const msg = err.detail || 'No se ha podido procesar la operación.'
        const queue = new SpeechQueue({ onStart: () => setPhase('speaking') })
        speechRef.current = queue
        queue.push(msg)
        queue.close()
        recordTurn(userText, msg, null)
        await queue.done
        if (turn === turnRef.current) resumeListening()
      }
    } catch (err) {
      if (err.name === 'AbortError') return
      setError('Algo ha fallado. Prueba otra vez.')
      resumeListening()
    }
  }

  // ── Interacción ─────────────────────────────────────────────────────────────

  function handleOrbClick() {
    const p = phaseRef.current
    if (p === 'idle') {
      setError('')
      resumeListening()
    } else if (p === 'listening' || p === 'hearing') {
      pauseConversation()
    } else if (p === 'speaking') {
      interrupt()
      resumeListening()
    }
  }

  function toggleBargeIn() {
    const next = !bargeIn
    setBargeIn(next)
    bargeInRef.current = next
    try { localStorage.setItem(BARGE_IN_KEY, next ? '1' : '0') } catch {}
  }

  const cfg = PHASES[phase]
  const clickable = ['idle', 'listening', 'hearing', 'speaking'].includes(phase)
  const reactive = phase === 'listening' || phase === 'hearing'

  const orbStyle = {
    width: 160,
    height: 160,
    borderRadius: '50%',
    background: `radial-gradient(circle at 38% 36%, ${cfg.orbColor}bb 0%, ${cfg.orbColor} 40%, #003d1f 100%)`,
    boxShadow: `0 0 32px 8px ${cfg.glowColor}`,
    animation: cfg.animation,
    transform: reactive ? `scale(${orbScale})` : undefined,
    transition: reactive ? 'transform 0.08s linear' : 'transform 0.3s cubic-bezier(0.16,1,0.3,1)',
    border: 'none',
    outline: 'none',
    cursor: clickable ? 'pointer' : 'default',
  }

  return (
    <div
      className="absolute inset-0 z-50 flex flex-col items-center overflow-y-auto"
      style={{ background: 'rgba(251,251,250,0.95)', backdropFilter: 'blur(10px)' }}
    >
      {/* Confirmation modals — overlay inside the voice modal */}
      {pendingBizum && (
        <BizumConfirmModal
          recipient={pendingBizum.recipient}
          amount={pendingBizum.amount}
          concept={pendingBizum.concept}
          onConfirm={() => handleActionDecision(pendingBizum, 'approve')}
          onCancel={() => handleActionDecision(pendingBizum, 'reject')}
        />
      )}
      {pendingInvestment && (
        <InvestmentConfirmModal
          ticker={pendingInvestment.ticker}
          nombre={pendingInvestment.nombre}
          shares={pendingInvestment.shares}
          price={pendingInvestment.price}
          currency={pendingInvestment.currency}
          totalEur={pendingInvestment.total_eur}
          investmentType={pendingInvestment.investment_type}
          onConfirm={() => handleActionDecision(pendingInvestment, 'approve')}
          onCancel={() => handleActionDecision(pendingInvestment, 'reject')}
        />
      )}

      {/* Close */}
      <button
        onClick={onClose}
        className="absolute top-4 right-4 w-8 h-8 rounded-full border border-[#EAEAEA]
          flex items-center justify-center text-[#787774]
          hover:border-[#111111] hover:text-[#111111] transition-all duration-200"
      >
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
        </svg>
      </button>

      {/* Orb + status */}
      <div className={`flex flex-col items-center px-6 ${chartInfo ? 'pt-12' : 'flex-1 justify-center'}`}>
        <button style={orbStyle} onClick={handleOrbClick} disabled={!clickable} aria-label={cfg.label} />

        <p className="mt-8 text-sm font-medium text-[#111111]">{cfg.label}</p>

        <div className="mt-2 h-5 flex items-center gap-1.5">
          {phase === 'hearing' && (
            <span
              className="w-1.5 h-1.5 rounded-full bg-[#E53E3E]"
              style={{ animation: 'dot-bounce 1.2s ease-in-out infinite' }}
            />
          )}
          {cfg.hint && (
            <span className="text-xs text-[#AAAAAA]">{cfg.hint}</span>
          )}
        </div>

        {/* Lo último que se ha entendido, para que se vea qué ha transcrito */}
        {transcript && !error && (
          <p className="mt-4 max-w-sm text-center text-xs text-[#787774] italic">«{transcript}»</p>
        )}
        {error && (
          <p className="mt-4 max-w-sm text-center text-xs text-[#E53E3E]">{error}</p>
        )}
      </div>

      {/* Chart — aparece debajo del orbe cuando hay datos */}
      {chartInfo && (
        <div className="w-full px-4 pt-6 bubble-animate">
          <InlineChart
            chartType={chartInfo.type}
            chartData={chartInfo.data}
            chartTitle={chartInfo.title}
          />
        </div>
      )}

      {/* Interrumpir hablando: con altavoces el micro puede captar la propia respuesta */}
      <label className="mt-auto mb-6 pt-6 flex items-center gap-2 text-xs text-[#787774] cursor-pointer select-none">
        <input type="checkbox" checked={bargeIn} onChange={toggleBargeIn} className="accent-[#00A651]" />
        Interrumpir hablando (mejor con auriculares)
      </label>
    </div>
  )
}
