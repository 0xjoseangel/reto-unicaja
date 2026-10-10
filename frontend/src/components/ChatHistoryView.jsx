import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { getChatHistoryDay, getChatHistoryDays } from '../services/api'

function formatDay(dateStr) {
  const d = new Date(`${dateStr}T00:00:00`)
  return d.toLocaleDateString('es-ES', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })
}

function formatTime(iso) {
  return new Date(iso).toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })
}

// Vista de solo lectura: lista de conversaciones pasadas agrupadas por día (no hay
// un id de sesión en el backend, así que "una conversación" es "un día natural").
export default function ChatHistoryView() {
  const [days, setDays] = useState([])
  const [loadingDays, setLoadingDays] = useState(true)
  const [selectedDay, setSelectedDay] = useState(null)
  const [messages, setMessages] = useState([])
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    getChatHistoryDays()
      .then(setDays)
      .catch(() => setError('No se ha podido cargar el historial.'))
      .finally(() => setLoadingDays(false))
  }, [])

  function openDay(day) {
    setSelectedDay(day)
    setLoadingMessages(true)
    setError(null)
    getChatHistoryDay(day)
      .then(setMessages)
      .catch(() => setError('No se ha podido cargar esta conversación.'))
      .finally(() => setLoadingMessages(false))
  }

  return (
    <div className="flex h-full bg-[#FBFBFA]">
      {/* Lista de días */}
      <div className="w-80 flex-none border-r border-[#EAEAEA] overflow-y-auto">
        <div className="px-5 py-4 border-b border-[#EAEAEA]">
          <h2 className="text-sm font-semibold text-[#111111]">Conversaciones pasadas</h2>
          <p className="text-xs text-[#787774] mt-0.5">Agrupadas por día</p>
        </div>

        {loadingDays && (
          <p className="px-5 py-4 text-xs text-[#787774]">Cargando...</p>
        )}

        {!loadingDays && days.length === 0 && (
          <p className="px-5 py-4 text-xs text-[#787774]">Todavía no hay conversaciones guardadas.</p>
        )}

        <ul>
          {days.map((d) => (
            <li key={d.date}>
              <button
                onClick={() => openDay(d.date)}
                className={`w-full text-left px-5 py-3 border-b border-[#EAEAEA] cursor-pointer
                  transition-colors duration-150
                  ${selectedDay === d.date ? 'bg-[#F1F1EF]' : 'hover:bg-[#F7F7F5]'}`}
              >
                <p className="text-xs font-medium text-[#111111] capitalize">{formatDay(d.date)}</p>
                <p className="text-xs text-[#787774] mt-0.5 truncate">{d.preview || '(sin texto)'}</p>
                <p className="text-[11px] text-[#9B9B97] mt-0.5">{d.message_count} mensajes</p>
              </button>
            </li>
          ))}
        </ul>
      </div>

      {/* Transcripción del día seleccionado */}
      <div className="flex-1 overflow-y-auto px-6 py-6">
        {error && <p className="text-xs text-red-600">{error}</p>}

        {!selectedDay && !error && (
          <p className="text-sm text-[#787774]">Selecciona una conversación de la izquierda para verla.</p>
        )}

        {selectedDay && loadingMessages && (
          <p className="text-sm text-[#787774]">Cargando conversación...</p>
        )}

        {selectedDay && !loadingMessages && !error && (
          <div className="flex flex-col gap-4 max-w-2xl">
            <h3 className="text-sm font-semibold text-[#111111] capitalize">{formatDay(selectedDay)}</h3>
            {messages.map((m, i) => (
              <div key={i} className={`flex gap-3 ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                {m.role === 'assistant' && (
                  <div className="w-7 h-7 rounded-[6px] bg-[#EDF3EC] border border-[#C6DEC5]
                    flex items-center justify-center flex-none mt-0.5
                    text-[10px] font-semibold text-[#346538] tracking-tight">
                    AI
                  </div>
                )}
                <div className={m.role === 'user'
                  ? 'max-w-[72%] px-4 py-2.5 text-sm leading-relaxed bg-[#111111] text-white rounded-[10px] rounded-br-[4px]'
                  : 'max-w-[72%] px-4 py-2.5 text-sm leading-relaxed bg-white border border-[#EAEAEA] rounded-[10px] rounded-bl-[4px] text-[#111111] prose-chat'}>
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{m.content}</ReactMarkdown>
                  <p className="text-[10px] mt-1 opacity-50">{formatTime(m.created_at)}</p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
