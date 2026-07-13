export default function InvestmentConfirmModal({ ticker, nombre, shares, avgPrice, investmentType, onConfirm, onCancel }) {
  const typeLabel = { accion: 'Acción', etf: 'ETF', fondo_indexado: 'Fondo indexado' }[investmentType] ?? investmentType

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center p-4"
         style={{ background: 'rgba(251,251,250,0.85)', backdropFilter: 'blur(6px)' }}>
      <div className="bg-white border border-[#EAEAEA] rounded-[12px] w-full max-w-sm bubble-animate"
           style={{ boxShadow: '0 4px 24px rgba(0,0,0,0.08)' }}>
        <div className="p-5 flex flex-col gap-4">

          {/* Header */}
          <div className="flex items-center gap-2.5 pb-4 border-b border-[#EAEAEA]">
            <div className="w-8 h-8 rounded-[6px] bg-[#EDF3EC] border border-[#C6DEC5]
                            flex items-center justify-center flex-none">
              <svg className="w-4 h-4 text-[#346538]" fill="none" stroke="currentColor"
                   strokeWidth="2" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round"
                      d="M7 17l9.2-9.2M17 17V7H7" />
              </svg>
            </div>
            <span className="text-sm font-semibold text-[#111111]">Confirmar compra</span>
          </div>

          {/* Details */}
          <div className="flex flex-col">
            <Row label="Activo" value={nombre} highlight />
            <Row label="Ticker" value={ticker} />
            <Row label="Tipo" value={typeLabel} />
            <Row label="Acciones" value={shares.toLocaleString('es-ES')} highlight />
            <Row label="Precio medio"
                 value={`${avgPrice.toLocaleString('es-ES', { minimumFractionDigits: 2 })} / acción`}
                 highlight />
          </div>

          <p className="text-xs text-[#787774] leading-relaxed">
            Comprueba los datos antes de confirmar. Esta operación añadirá el activo a tu cartera.
          </p>

          {/* Actions */}
          <div className="flex gap-2 pt-1">
            <button
              onClick={onCancel}
              className="flex-1 py-2.5 rounded-[6px] text-sm font-medium
                         bg-white border border-[#EAEAEA] text-[#787774]
                         hover:border-[#111111] hover:text-[#111111]
                         transition-all duration-200 cursor-pointer"
            >
              Cancelar
            </button>
            <button
              onClick={onConfirm}
              className="flex-1 py-2.5 rounded-[6px] text-sm font-semibold
                         bg-[#111111] text-white
                         hover:bg-[#333333] active:scale-[0.98]
                         transition-all duration-200 cursor-pointer"
            >
              Confirmar compra
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function Row({ label, value, highlight }) {
  return (
    <div className="flex justify-between items-center py-2.5 border-b border-[#EAEAEA] last:border-0">
      <span className="text-xs text-[#787774]">{label}</span>
      <span className={`text-sm font-medium ${highlight ? 'text-[#111111]' : 'text-[#444444]'}`}>
        {value}
      </span>
    </div>
  )
}
