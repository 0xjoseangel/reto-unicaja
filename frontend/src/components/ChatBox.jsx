import { useEffect, useRef, useState } from 'react'
import { sendChatMessage } from '../services/api'

const SUGGESTIONS = [
  '¿Cuál es mi saldo actual?',
  '¿Cuánto gasté en restaurantes?',
  '¿En qué categorías gasto más?',
  'Evolución mensual de gastos',
]

export default function ChatBox({ onChartData, hasChart }) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      text: '¡Hola! Soy tu asistente financiero personal. Puedes preguntarme sobre tus gastos, ingresos o saldo. ¿En qué puedo ayudarte hoy?',
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  async function handleSend(text) {
    const message = text || input.trim()
    if (!message || loading) return

    setMessages((prev) => [...prev, { role: 'user', text: message }])
    setInput('')
    setLoading(true)

    try {
      const data = await sendChatMessage(message)
      setMessages((prev) => [...prev, { role: 'assistant', text: data.response }])
      if (data.chart_type && data.chart_data) {
        onChartData({
          chartType: data.chart_type,
          chartData: data.chart_data,
          chartTitle: data.chart_title,
        })
      }
    } catch {
      setMessages((prev) => [
        ...prev,
        { role: 'assistant', text: 'Lo siento, ha ocurrido un error. ¿Puedes intentarlo de nuevo?' },
      ])
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-full bg-gray-50">
      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-4 py-4 flex flex-col gap-3">
        {messages.map((msg, i) => (
          <div key={i} className={`flex gap-2.5 ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            {msg.role === 'assistant' && (
              <div className="w-7 h-7 rounded-full bg-unicaja/10 flex items-center justify-center flex-none mt-0.5 text-sm">
                🤖
              </div>
            )}
            <div
              className={`max-w-[78%] px-4 py-2.5 text-sm leading-relaxed whitespace-pre-line shadow-sm ${
                msg.role === 'user'
                  ? 'bg-unicaja text-white rounded-2xl rounded-br-sm'
                  : 'bg-white text-gray-800 rounded-2xl rounded-bl-sm border border-gray-100'
              }`}
            >
              {msg.text}
            </div>
          </div>
        ))}

        {/* Loading indicator */}
        {loading && (
          <div className="flex gap-2.5 justify-start">
            <div className="w-7 h-7 rounded-full bg-unicaja/10 flex items-center justify-center flex-none text-sm">
              🤖
            </div>
            <div className="bg-white border border-gray-100 rounded-2xl rounded-bl-sm px-4 py-3 shadow-sm flex gap-1 items-center">
              <span className="w-1.5 h-1.5 rounded-full bg-unicaja/60 animate-bounce [animation-delay:0ms]" />
              <span className="w-1.5 h-1.5 rounded-full bg-unicaja/60 animate-bounce [animation-delay:150ms]" />
              <span className="w-1.5 h-1.5 rounded-full bg-unicaja/60 animate-bounce [animation-delay:300ms]" />
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
            className="flex-none text-xs font-medium text-unicaja bg-white border border-unicaja/25 rounded-full px-3 py-1.5 hover:bg-unicaja hover:text-white hover:border-unicaja transition-all cursor-pointer disabled:opacity-40 whitespace-nowrap"
          >
            {s}
          </button>
        ))}
      </div>

      {/* Input row */}
      <div className="bg-white border-t border-gray-100 px-4 py-3 flex gap-2 flex-none">
        <input
          className="flex-1 bg-gray-50 border border-gray-200 rounded-xl px-4 py-2.5 text-sm text-gray-800 placeholder-gray-400 outline-none focus:ring-2 focus:ring-unicaja/20 focus:border-unicaja transition-all"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Escribe tu consulta financiera..."
          disabled={loading}
        />
        <button
          onClick={() => handleSend()}
          disabled={loading || !input.trim()}
          className="bg-unicaja hover:bg-unicaja-dark text-white rounded-xl px-4 py-2.5 text-sm font-semibold transition-all disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer flex items-center gap-1.5"
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
