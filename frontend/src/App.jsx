import ChatBox from './components/ChatBox'

export default function App() {
  return (
    <div className="flex flex-col h-screen overflow-hidden p-3 gap-3">
      {/* Floating pill header */}
      <div className="flex justify-center flex-none pt-0.5">
        <header className="floating-pill px-6 py-3 flex items-center gap-6">
          <div>
            <h1 className="text-sm font-semibold text-white/90 leading-none">Asistente Financiero</h1>
            <p className="text-[11px] text-white/38 leading-tight mt-0.5">
              Habla con tu dinero · Cátedra Unicaja
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-unicaja glow-pulse" />
            <span className="text-[11px] text-white/40 font-medium">Activo</span>
          </div>
        </header>
      </div>

      {/* Chat — full width */}
      <div className="flex-1 min-h-0 bezel-outer">
        <div className="bezel-inner h-full flex flex-col overflow-hidden rounded-[19px]">
          <ChatBox />
        </div>
      </div>
    </div>
  )
}
