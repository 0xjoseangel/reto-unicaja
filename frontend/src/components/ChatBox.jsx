import { useEffect, useRef, useState } from 'react'
import { sendChatMessage } from '../services/api'

const SUGGESTIONS = [
  '¿Cuál es mi saldo actual?',
  '¿Cuánto gasté en restaurantes este mes?',
  '¿En qué categorías gasto más?',
  'Evolución mensual de gastos en transporte',
]

export default function ChatBox({ onChartData }) {
  const [messages, setMessages] = useState([
    {
      role: 'assistant',
      text: 'Hola! Soy tu asistente financiero. Puedes preguntarme sobre tus gastos, ingresos o saldo. ¿En qué puedo ayudarte?',
    },
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

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
    <div style={styles.container}>
      <div style={styles.header}>
        <div style={styles.avatar}>💬</div>
        <div>
          <div style={styles.headerTitle}>Habla con tu dinero</div>
          <div style={styles.headerSub}>Asistente financiero personal</div>
        </div>
      </div>

      <div style={styles.messages}>
        {messages.map((msg, i) => (
          <div key={i} style={msg.role === 'user' ? styles.userMsg : styles.assistantMsg}>
            <div style={msg.role === 'user' ? styles.userBubble : styles.assistantBubble}>
              {msg.text}
            </div>
          </div>
        ))}
        {loading && (
          <div style={styles.assistantMsg}>
            <div style={styles.assistantBubble}>
              <span style={styles.dots}>···</span>
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <div style={styles.suggestions}>
        {SUGGESTIONS.map((s, i) => (
          <button key={i} style={styles.suggestionBtn} onClick={() => handleSend(s)}>
            {s}
          </button>
        ))}
      </div>

      <div style={styles.inputRow}>
        <input
          style={styles.input}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSend()}
          placeholder="Escribe tu consulta..."
          disabled={loading}
        />
        <button style={styles.sendBtn} onClick={() => handleSend()} disabled={loading || !input.trim()}>
          →
        </button>
      </div>
    </div>
  )
}

const styles = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    height: '100%',
    background: '#1e293b',
    borderRadius: 12,
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '16px 20px',
    background: '#0f172a',
    borderBottom: '1px solid #334155',
  },
  avatar: {
    fontSize: 24,
    width: 40,
    height: 40,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background: '#6366f1',
    borderRadius: 10,
  },
  headerTitle: { color: '#e2e8f0', fontWeight: 600, fontSize: 15 },
  headerSub: { color: '#64748b', fontSize: 12 },
  messages: {
    flex: 1,
    overflowY: 'auto',
    padding: '16px',
    display: 'flex',
    flexDirection: 'column',
    gap: 10,
  },
  userMsg: { display: 'flex', justifyContent: 'flex-end' },
  assistantMsg: { display: 'flex', justifyContent: 'flex-start' },
  userBubble: {
    background: '#6366f1',
    color: '#fff',
    padding: '10px 14px',
    borderRadius: '12px 12px 2px 12px',
    maxWidth: '80%',
    fontSize: 14,
    lineHeight: 1.5,
  },
  assistantBubble: {
    background: '#0f172a',
    color: '#e2e8f0',
    padding: '10px 14px',
    borderRadius: '12px 12px 12px 2px',
    maxWidth: '85%',
    fontSize: 14,
    lineHeight: 1.6,
    whiteSpace: 'pre-line',
    border: '1px solid #334155',
  },
  dots: { color: '#6366f1', fontSize: 20, letterSpacing: 2 },
  suggestions: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 6,
    padding: '8px 16px',
    borderTop: '1px solid #0f172a',
  },
  suggestionBtn: {
    background: '#0f172a',
    color: '#94a3b8',
    border: '1px solid #334155',
    borderRadius: 20,
    padding: '5px 12px',
    fontSize: 12,
    cursor: 'pointer',
    transition: 'all 0.15s',
  },
  inputRow: {
    display: 'flex',
    gap: 8,
    padding: '12px 16px',
    borderTop: '1px solid #334155',
    background: '#0f172a',
  },
  input: {
    flex: 1,
    background: '#1e293b',
    border: '1px solid #334155',
    borderRadius: 8,
    padding: '10px 14px',
    color: '#e2e8f0',
    fontSize: 14,
    outline: 'none',
  },
  sendBtn: {
    background: '#6366f1',
    color: '#fff',
    border: 'none',
    borderRadius: 8,
    padding: '10px 16px',
    fontSize: 18,
    cursor: 'pointer',
    opacity: 1,
  },
}
