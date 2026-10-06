import { useEffect, useRef, useState } from 'react'
import InlineChart from './InlineChart'
import BizumConfirmModal from './BizumConfirmModal'
import InvestmentConfirmModal from './InvestmentConfirmModal'
import { apiFetch, apiStream, decideAction, readSSE } from '../services/api'

const PHASES = {
  idle: {
    label: 'Toca para hablar',
    hint: 'Voz española · Modelo local',
    orbColor: '#00A651',
    glowColor: 'rgba(0,166,81,0.45)',
    animation: 'orb-idle 2.4s ease-in-out infinite',
    clickable: true,
  },
  listening: {
    label: 'Escuchando...',
    hint: 'Toca de nuevo para enviar',
    orbColor: '#E53E3E',
    glowColor: 'rgba(229,62,62,0.45)',
    animation: 'none',
    clickable: true,
  },
  processing: {
    label: 'Procesando...',
    hint: null,
    orbColor: '#444444',
    glowColor: 'rgba(68,68,68,0.35)',
    animation: 'orb-spin 1.2s linear infinite',
    clickable: false,
  },
  speaking: {
    label: 'Respondiendo...',
    hint: null,
    orbColor: '#00A651',
    glowColor: 'rgba(0,166,81,0.45)',
    animation: 'orb-idle 0.9s ease-in-out infinite',
    clickable: false,
  },
}

export default function VoiceModal({ history, onClose, onComplete }) {
  const [phase, setPhase] = useState('idle')
  const [orbScale, setOrbScale] = useState(1)
  const [chartInfo, setChartInfo] = useState(null)
  const [pendingBizum, setPendingBizum] = useState(null)
  const [pendingInvestment, setPendingInvestment] = useState(null)

  const mediaRecorderRef = useRef(null)
  const audioChunksRef   = useRef([])
  const streamRef        = useRef(null)
  const audioCtxRef      = useRef(null)
  const animFrameRef     = useRef(null)
  // Texto del usuario que originó la operación pendiente (para el historial)
  const pendingContextRef = useRef(null)

  useEffect(() => {
    return () => {
      if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current)
      if (streamRef.current) streamRef.current.getTracks().forEach(t => t.stop())
      if (audioCtxRef.current) audioCtxRef.current.close().catch(() => {})
    }
  }, [])

  function startAmplitudeLoop(analyser) {
    const data = new Uint8Array(analyser.frequencyBinCount)
    function tick() {
      analyser.getByteFrequencyData(data)
      const avg = data.reduce((s, v) => s + v, 0) / data.length
      setOrbScale(1 + (avg / 255) * 0.45)
      animFrameRef.current = requestAnimationFrame(tick)
    }
    tick()
  }

  async function startListening() {
    setChartInfo(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream

      const ctx = new AudioContext()
      audioCtxRef.current = ctx
      const source = ctx.createMediaStreamSource(stream)
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 256
      source.connect(analyser)
      startAmplitudeLoop(analyser)

      const mr = new MediaRecorder(stream)
      audioChunksRef.current = []
      mr.ondataavailable = e => { if (e.data.size > 0) audioChunksRef.current.push(e.data) }
      mr.start()
      mediaRecorderRef.current = mr
      setPhase('listening')
    } catch {
      alert('No se pudo acceder al micrófono. Revisa los permisos del navegador.')
    }
  }

  async function stopListening() {
    if (animFrameRef.current) cancelAnimationFrame(animFrameRef.current)
    setOrbScale(1)

    const mr = mediaRecorderRef.current
    if (!mr) return

    const blob = await new Promise(resolve => {
      mr.onstop = () => resolve(new Blob(audioChunksRef.current, { type: 'audio/webm' }))
      mr.stop()
    })

    streamRef.current?.getTracks().forEach(t => t.stop())
    if (audioCtxRef.current) {
      await audioCtxRef.current.close().catch(() => {})
      audioCtxRef.current = null
    }

    setPhase('processing')
    processAudio(blob)
  }

  async function processAudio(audioBlob) {
    try {
      const form = new FormData()
      form.append('file', audioBlob, 'audio.webm')
      const txRes = await apiFetch('/voice/transcribe', { method: 'POST', body: form })
      if (!txRes.ok) throw new Error('Transcripción fallida')
      const { text: userText } = await txRes.json()
      if (!userText.trim()) { setPhase('idle'); return }

      await sendToAgent(userText, history || [])
    } catch (err) {
      console.error('[VoiceModal]', err)
      setPhase('idle')
    }
  }

  async function sendToAgent(userText, currentHistory) {
    const chatRes = await apiStream('/chat/stream', { message: userText, history: currentHistory, voice_mode: true })
    if (!chatRes.ok) throw new Error('Chat fallido')

    let assistantText = ''
    let chartType = null, chartData = null, chartTitle = null
    let pending = null

    await readSSE(chatRes, ev => {
      if (ev.type === 'token') {
        assistantText += ev.text
      } else if (ev.type === 'done') {
        if (ev.pending_action) {
          pending = ev.pending_action
        } else if (ev.chart_type && ev.chart_data?.length) {
          chartType = ev.chart_type
          chartData = ev.chart_data
          chartTitle = ev.chart_title
          setChartInfo({ type: chartType, data: chartData, title: chartTitle })
        }
      }
    })

    if (pending) {
      // El agente ha propuesto una operación: se para aquí hasta que el usuario
      // la apruebe o rechace en el modal (handleActionDecision)
      pendingContextRef.current = { userText }
      if (pending.type === 'bizum_confirm') setPendingBizum(pending)
      else setPendingInvestment(pending)
      setPhase('idle')
      return
    }

    onComplete({ userText, assistantText: assistantText.trim(), chartType, chartData, chartTitle })
    await speakText(assistantText.trim())
  }

  async function speakText(text) {
    setPhase('speaking')
    try {
      const ttsRes = await apiFetch('/voice/synthesize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })
      if (!ttsRes.ok) { setPhase('idle'); return }
      const audioData = await ttsRes.arrayBuffer()
      const audioUrl = URL.createObjectURL(new Blob([audioData], { type: 'audio/wav' }))
      const audio = new Audio(audioUrl)
      audio.onended = () => { URL.revokeObjectURL(audioUrl); setPhase('idle') }
      audio.onerror = () => { URL.revokeObjectURL(audioUrl); setPhase('idle') }
      audio.play()
    } catch {
      setPhase('idle')
    }
  }

  // Aprobar o rechazar la operación propuesta. Va al backend con el action_id; el
  // agente responde (por voz) con el resultado de la ejecución o la cancelación.
  async function handleActionDecision(action, decision) {
    const { userText } = pendingContextRef.current
    setPendingBizum(null)
    setPendingInvestment(null)
    setPhase('processing')
    try {
      const res = await decideAction(action.action_id, decision)
      let responseText = ''
      if (res.ok) {
        await readSSE(res, ev => {
          if (ev.type === 'token') responseText += ev.text
          else if (ev.type === 'error') responseText = ev.text
        })
      } else {
        const err = await res.json().catch(() => ({}))
        responseText = err.detail || 'No se ha podido procesar la operación.'
      }
      onComplete({ userText, assistantText: responseText.trim() })
      await speakText(responseText.trim())
    } catch {
      setPhase('idle')
    }
  }

  function handleOrbClick() {
    if (phase === 'idle') startListening()
    else if (phase === 'listening') stopListening()
  }

  const cfg = PHASES[phase]

  const orbStyle = {
    width: 160,
    height: 160,
    borderRadius: '50%',
    background: `radial-gradient(circle at 38% 36%, ${cfg.orbColor}bb 0%, ${cfg.orbColor} 40%, #003d1f 100%)`,
    boxShadow: `0 0 32px 8px ${cfg.glowColor}`,
    animation: cfg.animation,
    transform: phase === 'listening' ? `scale(${orbScale})` : undefined,
    transition: phase === 'listening' ? 'none' : 'transform 0.3s cubic-bezier(0.16,1,0.3,1)',
    border: 'none',
    outline: 'none',
    cursor: cfg.clickable ? 'pointer' : 'default',
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
      <div className={`flex flex-col items-center ${chartInfo ? 'pt-12' : 'flex-1 justify-center'}`}>
        <button style={orbStyle} onClick={handleOrbClick} disabled={!cfg.clickable} />

        <p className="mt-8 text-sm font-medium text-[#111111]">{cfg.label}</p>

        <div className="mt-2 h-5 flex items-center gap-1.5">
          {phase === 'listening' && (
            <span
              className="w-1.5 h-1.5 rounded-full bg-[#E53E3E]"
              style={{ animation: 'dot-bounce 1.2s ease-in-out infinite' }}
            />
          )}
          {cfg.hint && (
            <span className="text-xs text-[#AAAAAA]">{cfg.hint}</span>
          )}
        </div>
      </div>

      {/* Chart — aparece debajo del orbe cuando hay datos */}
      {chartInfo && (
        <div className="w-full px-4 pb-8 pt-6 bubble-animate">
          <InlineChart
            chartType={chartInfo.type}
            chartData={chartInfo.data}
            chartTitle={chartInfo.title}
          />
        </div>
      )}
    </div>
  )
}
