import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

function TypewriterText({ text, active }) {
  // Mensajes históricos (active=false desde el primer render) se muestran al instante
  const [displayed, setDisplayed] = useState(active ? '' : text)
  const posRef   = useRef(active ? 0 : text.length)
  const textRef  = useRef(text)
  const timerRef = useRef(null)

  useEffect(() => {
    textRef.current = text

    // Ya alcanzamos o superamos el texto actual — nada que animar
    if (posRef.current >= text.length) {
      setDisplayed(text)
      return
    }

    // Limpiar timer anterior (necesario para Strict Mode y cambios de text)
    if (timerRef.current) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }

    timerRef.current = setInterval(() => {
      if (posRef.current >= textRef.current.length) {
        clearInterval(timerRef.current)
        timerRef.current = null
        return
      }
      posRef.current += 1
      setDisplayed(textRef.current.slice(0, posRef.current))
    }, 12)

    return () => {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [text])

  const showCursor = active && displayed.length < text.length

  return (
    <>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{displayed || ' '}</ReactMarkdown>
      {showCursor && (
        <span
          className="inline-block w-px h-3.5 bg-[#787774] ml-0.5 align-middle"
          style={{ animation: 'cursor-blink 0.7s step-end infinite' }}
        />
      )}
    </>
  )
}
import InlineChart from './InlineChart'
import BizumConfirmModal from './BizumConfirmModal'
import InvestmentConfirmModal from './InvestmentConfirmModal'
import VoiceModal from './VoiceModal'

const SUGGESTIONS = [
  '¿Cuál es mi saldo actual?',
  '¿Cuánto gasté en restaurantes?',
  '¿En qué categorías gasto más?',
  'Evolución mensual de gastos',
]

export default function ChatBox() {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      text: '¡Hola! Soy tu asistente financiero personal. Puedes preguntarme sobre tus gastos, ingresos o saldo. ¿En qué puedo ayudarte hoy?',
    },
  ])
  const [history, setHistory] = useState([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [streamingMsgIdx, setStreamingMsgIdx] = useState(-1)
  const [pendingBizum, setPendingBizum] = useState(null)
  const [pendingInvestment, setPendingInvestment] = useState(null)
  const [voiceOpen, setVoiceOpen] = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  async function handleSend(text) {
    const message = text || input.trim()
    if (!message || loading) return

    setMessages(prev => [...prev, { role: 'user', text: message }])
    setInput('')
    setLoading(true)

    const updatedHistory = [...history, { role: 'user', content: message }]

    try {
      const res = await fetch('/chat/stream', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message, user_id: 1, history: updatedHistory }),
      })

      if (!res.ok) throw new Error('Server error')

      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let streamingText = ''
      let assistantAdded = false
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() ?? ''

        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          const raw = line.slice(6).trim()
          if (!raw) continue

          let event
          try { event = JSON.parse(raw) } catch { continue }

          if (event.type === 'token') {
            streamingText += event.text
            if (!assistantAdded) {
              setMessages(prev => {
                setStreamingMsgIdx(prev.length)
                return [...prev, { role: 'assistant', text: streamingText }]
              })
              assistantAdded = true
              setLoading(false)
            } else {
              setMessages(prev => {
                const updated = [...prev]
                updated[updated.length - 1] = { role: 'assistant', text: streamingText }
                return updated
              })
            }

          } else if (event.type === 'done') {
            if (event.pending_action?.type === 'bizum_confirm') {
              if (assistantAdded) setMessages(prev => prev.slice(0, -1))
              setStreamingMsgIdx(-1)
              setPendingBizum(event.pending_action)
              setHistory(updatedHistory)
              return
            }
            if (event.pending_action?.type === 'investment_confirm') {
              if (assistantAdded) setMessages(prev => prev.slice(0, -1))
              setStreamingMsgIdx(-1)
              setPendingInvestment(event.pending_action)
              setHistory(updatedHistory)
              return
            }

            if (!assistantAdded && streamingText) {
              setMessages(prev => [...prev, { role: 'assistant', text: streamingText }])
            }

            if (event.chart_type && event.chart_data?.length) {
              setMessages(prev => [...prev, {
                role: 'chart',
                chart: {
                  type: event.chart_type,
                  data: event.chart_data,
                  title: event.chart_title,
                },
              }])
            }

            setHistory([...updatedHistory, { role: 'assistant', content: streamingText }])

          } else if (event.type === 'error') {
            setMessages(prev => [...prev, { role: 'assistant', text: event.text }])
          }
        }
      }
    } catch {
      setMessages(prev => [
        ...prev,
        { role: 'assistant', text: 'Lo siento, ha ocurrido un error. ¿Puedes intentarlo de nuevo?' },
      ])
    } finally {
      setLoading(false)
      setStreamingMsgIdx(-1)
    }
  }

  function handleBizumConfirm() {
    const { recipient, amount, concept } = pendingBizum
    setPendingBizum(null)
    handleSend(`Sí, confirma el Bizum de ${amount}€ a ${recipient} por ${concept}`)
  }

  function handleBizumCancel() {
    setPendingBizum(null)
    setMessages(prev => [...prev, { role: 'assistant', text: 'Bizum cancelado.' }])
  }

  function handleInvestmentConfirm() {
    const { ticker, shares, avg_purchase_price } = pendingInvestment
    setPendingInvestment(null)
    handleSend(`Sí, confirma la compra de ${shares} acciones de ${ticker} a ${avg_purchase_price} por acción`)
  }

  function handleInvestmentCancel() {
    setPendingInvestment(null)
    setMessages(prev => [...prev, { role: 'assistant', text: 'Compra cancelada.' }])
  }

  function handleVoiceComplete({ userText, assistantText, chartType, chartData, chartTitle }) {
    const newMessages = [
      { role: 'user', text: userText },
      { role: 'assistant', text: assistantText },
    ]
    if (chartType && chartData?.length) {
      newMessages.push({ role: 'chart', chart: { type: chartType, data: chartData, title: chartTitle } })
    }
    setMessages(prev => [...prev, ...newMessages])
    setHistory(prev => [
      ...prev,
      { role: 'user', content: userText },
      { role: 'assistant', content: assistantText },
    ])
  }

  return (
    <div className="flex flex-col h-full bg-[#FBFBFA] relative">
      {pendingBizum && (
        <BizumConfirmModal
          recipient={pendingBizum.recipient}
          amount={pendingBizum.amount}
          concept={pendingBizum.concept}
          onConfirm={handleBizumConfirm}
          onCancel={handleBizumCancel}
        />
      )}
      {voiceOpen && (
        <VoiceModal
          history={history}
          onClose={() => setVoiceOpen(false)}
          onComplete={handleVoiceComplete}
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

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-6 flex flex-col gap-4">
        {messages.map((msg, i) => {
          if (msg.role === 'chart') {
            return (
              <div key={i} className="flex justify-start pl-9">
                <InlineChart
                  chartType={msg.chart.type}
                  chartData={msg.chart.data}
                  chartTitle={msg.chart.title}
                />
              </div>
            )
          }

          return (
            <div key={i} className={`flex gap-3 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {msg.role === 'assistant' && (
                <div className="w-7 h-7 rounded-[6px] bg-[#EDF3EC] border border-[#C6DEC5]
                  flex items-center justify-center flex-none mt-0.5
                  text-[10px] font-semibold text-[#346538] tracking-tight">
                  AI
                </div>
              )}
              {msg.role === 'user' ? (
                <div className="max-w-[72%] px-4 py-2.5 text-sm leading-relaxed bubble-animate
                  bg-[#111111] text-white rounded-[10px] rounded-br-[4px]">
                  {msg.text}
                </div>
              ) : (
                <div className="max-w-[72%] px-4 py-2.5 text-sm leading-relaxed bubble-animate
                  bg-white border border-[#EAEAEA] rounded-[10px] rounded-bl-[4px]
                  text-[#111111] prose-chat
                  transition-shadow duration-200 hover:shadow-[0_2px_8px_rgba(0,0,0,0.04)]">
                  <TypewriterText
                    text={msg.text}
                    active={i === streamingMsgIdx}
                  />
                </div>
              )}
            </div>
          )
        })}

        {/* Loading dots */}
        {loading && (
          <div className="flex gap-3 justify-start">
            <div className="w-7 h-7 rounded-[6px] bg-[#EDF3EC] border border-[#C6DEC5]
              flex items-center justify-center flex-none
              text-[10px] font-semibold text-[#346538]">
              AI
            </div>
            <div className="bg-white border border-[#EAEAEA] rounded-[10px] rounded-bl-[4px]
              px-4 py-3 flex gap-1.5 items-center bubble-animate">
              <span className="w-1.5 h-1.5 rounded-full bg-[#111111]" style={{ animation: 'dot-bounce 1.2s 0ms cubic-bezier(0.16,1,0.3,1) infinite' }} />
              <span className="w-1.5 h-1.5 rounded-full bg-[#111111]" style={{ animation: 'dot-bounce 1.2s 150ms cubic-bezier(0.16,1,0.3,1) infinite' }} />
              <span className="w-1.5 h-1.5 rounded-full bg-[#111111]" style={{ animation: 'dot-bounce 1.2s 300ms cubic-bezier(0.16,1,0.3,1) infinite' }} />
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Suggestions */}
      <div className="flex gap-2 px-6 py-2 overflow-x-auto scrollbar-hide flex-none border-t border-[#EAEAEA]">
        {SUGGESTIONS.map((s, i) => (
          <button
            key={i}
            onClick={() => handleSend(s)}
            disabled={loading}
            className="flex-none text-xs font-medium text-[#787774]
              bg-white border border-[#EAEAEA] rounded-[6px] px-3 py-1.5 whitespace-nowrap cursor-pointer
              hover:border-[#111111] hover:text-[#111111]
              transition-all duration-200 ease-spring
              disabled:opacity-40"
          >
            {s}
          </button>
        ))}
      </div>

      {/* Input */}
      <div className="flex-none px-6 py-4 border-t border-[#EAEAEA] bg-white flex gap-3 items-center">
        <input
          className="flex-1 bg-transparent border-none outline-none text-sm text-[#111111]
            placeholder-[#787774] caret-[#111111]"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Escribe tu consulta financiera..."
          disabled={loading}
        />
        <button
          onClick={() => setVoiceOpen(true)}
          disabled={loading}
          title="Hablar con el asistente"
          className="flex-none w-9 h-9 rounded-[6px] border border-[#EAEAEA]
            flex items-center justify-center text-[#787774] cursor-pointer
            hover:border-[#111111] hover:text-[#111111]
            transition-all duration-200 ease-spring
            disabled:opacity-30 disabled:cursor-not-allowed"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round"
              d="M12 18.75a6 6 0 006-6v-1.5m-6 7.5a6 6 0 01-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 01-3-3V4.5a3 3 0 116 0v8.25a3 3 0 01-3 3z" />
          </svg>
        </button>
        <button
          onClick={() => handleSend()}
          disabled={loading || !input.trim()}
          className="flex-none bg-[#111111] text-white text-sm font-medium
            px-4 py-2 rounded-[6px] cursor-pointer
            hover:bg-[#333333] active:scale-[0.98]
            transition-all duration-200 ease-spring
            disabled:opacity-30 disabled:cursor-not-allowed
            flex items-center gap-1.5"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
          </svg>
          Enviar
        </button>
      </div>
    </div>
  )
}
