import ChatBox from './components/ChatBox'

export default function App() {
  return (
    <div className="flex flex-col h-screen overflow-hidden bg-[#FBFBFA]">
      {/* Top bar */}
      <header className="flex items-center justify-between px-8 py-4 border-b border-[#EAEAEA] bg-white flex-none">
        <div>
          <p className="text-[11px] font-medium text-[#787774] uppercase tracking-[0.08em] leading-none mb-0.5">
            Cátedra Unicaja · UGR
          </p>
          <h1 className="text-sm font-semibold text-[#111111] leading-tight">Asistente Financiero</h1>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-1.5 h-1.5 rounded-full bg-[#346538] glow-pulse" />
          <span className="text-xs text-[#787774]">Activo</span>
        </div>
      </header>

      {/* Chat */}
      <div className="flex-1 min-h-0">
        <ChatBox />
      </div>
    </div>
  )
}
