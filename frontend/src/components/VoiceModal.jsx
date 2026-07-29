import { useEffect, useRef, useState } from 'react'
import InlineChart from './InlineChart'
import BizumConfirmModal from './BizumConfirmModal'
import InvestmentConfirmModal from './InvestmentConfirmModal'

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
  // Stores context needed to complete the confirmation flow
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
      const txRes = await fetch('/voice/transcribe', { method: 'POST', body: form })
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
    const chatRes = await fetch('/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: userText, user_id: 1, history: currentHistory, voice_mode: true }),
    })
    if (!chatRes.ok) throw new Error('Chat fallido')

    const reader = chatRes.body.getReader()
    const decoder = new TextDecoder()
    let assistantText = ''
    let chartType = null, chartData = null, chartTitle = null
    let buf = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      const lines = buf.split('\n')
      buf = lines.pop() ?? ''
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const ev = JSON.parse(line.slice(6).trim())
          if (ev.type === 'token') {
            assistantText += ev.text
          } else if (ev.type === 'done') {
            if (ev.pending_action?.type === 'bizum_confirm') {
              pendingContextRef.current = {
                userText,
                updatedHistory: [...currentHistory, { role: 'user', content: userText }],
              }
              setPendingBizum(ev.pending_action)
              setPhase('idle')
              return
            }
            if (ev.pending_action?.type === 'investment_confirm') {
              pendingContextRef.current = {
                userText,
                updatedHistory: [...currentHistory, { role: 'user', content: userText }],
              }
              setPendingInvestment(ev.pending_action)
              setPhase('idle')
              return
            }
            if (ev.chart_type && ev.chart_data?.length) {
              chartType = ev.chart_type
              chartData = ev.chart_data
              chartTitle = ev.chart_title
              setChartInfo({ type: chartType, data: chartData, title: chartTitle })
            }
          }
        } catch {}
      }
    }

    onComplete({ userText, assistantText: assistantText.trim(), chartType, chartData, chartTitle })
    await speakText(assistantText.trim())
  }

  async function speakText(text) {
    setPhase('speaking')
    try {
      const ttsRes = await fetch('/voice/synthesize', {
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

  async function handleBizumConfirm() {
    const { recipient, amount, concept } = pendingBizum
    const { userText, updatedHistory } = pendingContextRef.current
    setPendingBizum(null)
    setPhase('processing')
    try {
      const confirmText = `Sí, confirma el Bizum de ${amount}€ a ${recipient} por ${concept}`
      const chatRes = await fetch('/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: confirmText, user_id: 1, history: updatedHistory, voice_mode: true }),
      })
      const reader = chatRes.body.getReader()
      const decoder = new TextDecoder()
      let confirmResponse = ''
      let buf = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const ev = JSON.parse(line.slice(6).trim())
            if (ev.type === 'token') confirmResponse += ev.text
          } catch {}
        }
      }
      onComplete({ userText, assistantText: confirmResponse.trim() })
      await speakText(confirmResponse.trim())
    } catch {
      setPhase('idle')
    }
  }

  async function handleBizumCancel() {
    const { userText } = pendingContextRef.current
    setPendingBizum(null)
    onComplete({ userText, assistantText: 'Bizum cancelado.' })
    await speakText('Bizum cancelado.')
  }

  async function handleInvestmentConfirm() {
    const { ticker, shares, avg_purchase_price } = pendingInvestment
    const { userText, updatedHistory } = pendingContextRef.current
    setPendingInvestment(null)
    setPhase('processing')
    try {
      const confirmText = `Sí, confirma la compra de ${shares} acciones de ${ticker} a ${avg_purchase_price} por acción`
      const chatRes = await fetch('/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: confirmText, user_id: 1, history: updatedHistory, voice_mode: true }),
      })
      const reader = chatRes.body.getReader()
      const decoder = new TextDecoder()
      let confirmResponse = ''
      let buf = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const ev = JSON.parse(line.slice(6).trim())
            if (ev.type === 'token') confirmResponse += ev.text
          } catch {}
        }
      }
      onComplete({ userText, assistantText: confirmResponse.trim() })
      await speakText(confirmResponse.trim())
    } catch {
      setPhase('idle')
    }
  }

  async function handleInvestmentCancel() {
    const { userText } = pendingContextRef.current
    setPendingInvestment(null)
    onComplete({ userText, assistantText: 'Compra cancelada.' })
    await speakText('Compra cancelada.')
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
          onConfirm={handleBizumConfirm}
          onCancel={handleBizumCancel}
        />
      )}
      {pendingInvestment && (
        <InvestmentConfirmModal
          ticker={pendingInvestment.ticker}
          nombre={pendingInvestment.nombre}
          shares={pendingInvestment.shares}
          avgPrice={pendingInvestment.avg_purchase_price}
          investmentType={pendingInvestment.investment_type}
          onConfirm={handleInvestmentConfirm}
          onCancel={handleInvestmentCancel}
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
