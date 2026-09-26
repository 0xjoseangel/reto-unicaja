import { useCallback, useRef, useState } from 'react'
import { useAuth } from './context/AuthContext'
import ChatBox from './components/ChatBox'
import DashboardPage from './components/DashboardPage'
import LoginPage from './components/LoginPage'
import VoiceModal from './components/VoiceModal'

const TABS = [
  { id: 'dashboard', label: 'Dashboard' },
  { id: 'chat', label: 'Chat' },
]

export default function App() {
  const { token, user, logout } = useAuth()
  const [view, setView] = useState('dashboard')
  const [voiceOpen, setVoiceOpen] = useState(false)
  const [voiceHistory, setVoiceHistory] = useState([])
  const [initialPrompt, setInitialPrompt] = useState(null)

  // El chat vive dentro de ChatBox y solo él conoce su propio historial/mensajes.
  // Como el widget de voz ahora vive aquí (persistente entre pestañas), ChatBox
  // nos registra un handler para poder devolverle el resultado de una vuelta de voz,
  // y nos reporta su historial actual para que la voz pueda usarlo desde cualquier pestaña.
  const voiceCompleteHandlerRef = useRef(null)
  const registerVoiceCompleteHandler = useCallback((handler) => {
    voiceCompleteHandlerRef.current = handler
  }, [])

  const chatHistoryRef = useRef([])
  const handleChatHistoryChange = useCallback((h) => {
    chatHistoryRef.current = h
  }, [])

  if (!token) return <LoginPage />

  function openVoice() {
    const base = chatHistoryRef.current
    if (view === 'dashboard') {
      // Se antepone un mensaje de contexto sintético con lo que se ve en el dashboard,
      // sin perder el historial real del chat si ya existía (App.jsx compone, VoiceModal
      // no necesita saber de dónde viene el history que recibe).
      setVoiceHistory([
        { role: 'user', content: 'Contexto visible: estoy mirando mi dashboard financiero con tarjetas generadas por la IA.' },
        ...base,
      ])
    } else {
      setVoiceHistory(base)
    }
    setVoiceOpen(true)
  }

  function handleOpenCard(card) {
    setView('chat')
    setInitialPrompt(card.cta_prompt || `Cuéntame más sobre: ${card.title}`)
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-[#FBFBFA]">
      {/* Top bar */}
      <header className="flex items-center justify-between px-8 py-4 border-b border-[#EAEAEA] bg-white flex-none">
        <div className="flex items-center gap-8">
          <div>
            <p className="text-[11px] font-medium text-[#787774] uppercase tracking-[0.08em] leading-none mb-0.5">
              Cátedra Unicaja · UGR
            </p>
            <h1 className="text-sm font-semibold text-[#111111] leading-tight">Asistente Financiero</h1>
          </div>
          <nav className="flex items-center gap-1">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setView(tab.id)}
                className={`text-xs font-medium px-3 py-1.5 rounded-[6px] cursor-pointer
                  transition-all duration-200 ease-spring
                  ${view === tab.id
                    ? 'bg-[#111111] text-white'
                    : 'text-[#787774] hover:text-[#111111] hover:bg-[#F1F1EF]'}`}
              >
                {tab.label}
              </button>
            ))}
          </nav>
        </div>
        <div className="flex items-center gap-4">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-[#346538] glow-pulse" />
            <span className="text-xs text-[#787774]">Activo</span>
          </div>
          {user && (
            <div className="flex items-center gap-3">
              <span className="text-xs text-[#787774]">{user.name}</span>
              <button
                onClick={logout}
                className="text-xs text-[#787774] hover:text-[#111111] transition-colors duration-150 cursor-pointer"
              >
                Salir
              </button>
            </div>
          )}
        </div>
      </header>

      {/* Vista principal — ChatBox se mantiene montado tras la primera visita para no
          perder su historial ni el handler de voz registrado al cambiar de pestaña */}
      <div className="flex-1 min-h-0 relative">
        <div className="absolute inset-0" hidden={view !== 'dashboard'}>
          <DashboardPage onOpenCard={handleOpenCard} />
        </div>
        <div className="absolute inset-0" hidden={view !== 'chat'}>
          <ChatBox
            onOpenVoice={openVoice}
            registerVoiceCompleteHandler={registerVoiceCompleteHandler}
            onHistoryChange={handleChatHistoryChange}
            initialPrompt={initialPrompt}
            onInitialPromptConsumed={() => setInitialPrompt(null)}
          />
        </div>

        {/* Botón flotante de voz — solo en el dashboard: en el chat ya hay un botón de
            micrófono propio dentro de la caja de mensaje, y los dos solapaban la UI */}
        {!voiceOpen && view === 'dashboard' && (
          <button
            onClick={() => openVoice()}
            title="Hablar con el asistente"
            className="absolute bottom-6 right-6 w-12 h-12 rounded-full bg-[#111111] text-white
              flex items-center justify-center cursor-pointer shadow-lg
              hover:bg-[#333333] active:scale-95
              transition-all duration-200 ease-spring"
          >
            <svg className="w-5 h-5" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round"
                d="M12 18.75a6 6 0 006-6v-1.5m-6 7.5a6 6 0 01-6-6v-1.5m6 7.5v3.75m-3.75 0h7.5M12 15.75a3 3 0 01-3-3V4.5a3 3 0 116 0v8.25a3 3 0 01-3 3z" />
            </svg>
          </button>
        )}

        {voiceOpen && (
          <VoiceModal
            history={voiceHistory}
            onClose={() => setVoiceOpen(false)}
            onComplete={(payload) => voiceCompleteHandlerRef.current?.(payload)}
          />
        )}
      </div>
    </div>
  )
}
