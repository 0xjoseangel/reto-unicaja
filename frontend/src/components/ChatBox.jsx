import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import InlineChart from './InlineChart'
import BizumConfirmModal from './BizumConfirmModal'

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
  const [pendingBizum, setPendingBizum] = useState(null)
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
        // Keep incomplete last line in buffer
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
              setMessages(prev => [...prev, { role: 'assistant', text: streamingText }])
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
              // Quitar el mensaje streamed (suele estar vacío) y mostrar modal
              if (assistantAdded) {
                setMessages(prev => prev.slice(0, -1))
              }
              setPendingBizum(event.pending_action)
              setHistory(updatedHistory)
              return
            }

            // Si no hubo ningún token (respuesta vacía), añadir mensaje vacío silencioso
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

  return (
    <div className="flex flex-col h-full bg-transparent relative">
      {pendingBizum && (
        <BizumConfirmModal
          recipient={pendingBizum.recipient}
          amount={pendingBizum.amount}
          concept={pendingBizum.concept}
          onConfirm={handleBizumConfirm}
          onCancel={handleBizumCancel}
        />
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-3">
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
            <div key={i} className={`flex gap-2.5 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              {msg.role === 'assistant' && (
                <div className="w-7 h-7 rounded-full bg-unicaja/15 border border-unicaja/30 flex items-center justify-center flex-none mt-0.5 text-[10px] font-bold text-unicaja">
                  AI
                </div>
              )}
              {msg.role === 'user' ? (
                <div className="max-w-[75%] px-4 py-2.5 text-sm leading-relaxed whitespace-pre-line bubble-animate
                  bg-unicaja text-white rounded-2xl rounded-br-sm
                  shadow-[0_0_24px_rgba(0,166,81,0.30)]">
                  {msg.text}
                </div>
              ) : (
                <div className="bezel-outer max-w-[75%] bubble-animate">
                  <div className="bezel-inner rounded-[19px] px-4 py-2.5 text-sm leading-relaxed text-white/85 prose-chat">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{msg.text}</ReactMarkdown>
                  </div>
                </div>
              )}
            </div>
          )
        })}

        {/* Loading dots — solo durante Phase 1 (antes del primer token) */}
        {loading && (
          <div className="flex gap-2.5 justify-start">
            <div className="w-7 h-7 rounded-full bg-unicaja/15 border border-unicaja/30 flex items-center justify-center flex-none text-[10px] font-bold text-unicaja">
              AI
            </div>
            <div className="bezel-outer bubble-animate">
              <div className="bezel-inner rounded-[19px] px-4 py-3 flex gap-1.5 items-center">
                <span className="w-1.5 h-1.5 rounded-full bg-unicaja/50" style={{ animation: 'dot-bounce 1.2s 0ms cubic-bezier(0.32,0.72,0,1) infinite' }} />
                <span className="w-1.5 h-1.5 rounded-full bg-unicaja/50" style={{ animation: 'dot-bounce 1.2s 150ms cubic-bezier(0.32,0.72,0,1) infinite' }} />
                <span className="w-1.5 h-1.5 rounded-full bg-unicaja/50" style={{ animation: 'dot-bounce 1.2s 300ms cubic-bezier(0.32,0.72,0,1) infinite' }} />
              </div>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Suggestions */}
      <div className="flex gap-2 px-4 py-2 overflow-x-auto scrollbar-hide flex-none">
        {SUGGESTIONS.map((s, i) => (
          <button
            key={i}
            onClick={() => handleSend(s)}
            disabled={loading}
            className="flex-none text-xs font-medium text-white/60 bg-white/5 border border-white/10
              rounded-full px-3 py-1.5 whitespace-nowrap cursor-pointer
              hover:bg-unicaja/15 hover:text-unicaja hover:border-unicaja/30
              transition-all duration-300 ease-spring
              disabled:opacity-30"
          >
            {s}
          </button>
        ))}
      </div>

      {/* Input */}
      <div className="flex-none px-3 pb-3 pt-1">
        <div className="bezel-outer">
          <div className="bezel-inner rounded-[19px] px-3 py-2 flex gap-2 items-center">
            <input
              className="flex-1 bg-transparent border-none outline-none text-sm text-white/85
                placeholder-white/25 caret-unicaja"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSend()}
              placeholder="Escribe tu consulta financiera..."
              disabled={loading}
            />
            <button
              onClick={() => handleSend()}
              disabled={loading || !input.trim()}
              className="flex-none bg-unicaja/15 border border-unicaja/35 rounded-[14px] p-0.5
                transition-all duration-300 ease-spring
                hover:bg-unicaja/20 hover:border-unicaja/50
                active:scale-[0.98]
                disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
            >
              <span className="flex items-center gap-1.5 bg-unicaja rounded-[12px] px-4 py-2
                text-white text-sm font-semibold">
                <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
                </svg>
                Enviar
              </span>
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
