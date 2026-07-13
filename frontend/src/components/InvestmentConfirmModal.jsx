export default function InvestmentConfirmModal({ ticker, nombre, shares, avgPrice, investmentType, onConfirm, onCancel }) {
  const typeLabel = { accion: 'Acción', etf: 'ETF', fondo_indexado: 'Fondo indexado' }[investmentType] ?? investmentType

  return (
    <div className="absolute inset-0 z-50 flex items-center justify-center p-4"
         style={{ background: 'rgba(5,10,8,0.82)', backdropFilter: 'blur(8px)' }}>
      <div className="bezel-outer w-full max-w-sm bubble-animate">
        <div className="bezel-inner rounded-[19px] p-5 flex flex-col gap-4">

          {/* Header */}
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-full bg-unicaja/15 border border-unicaja/30
                            flex items-center justify-center flex-none">
              <svg className="w-4 h-4 text-unicaja" fill="none" stroke="currentColor"
                   strokeWidth="2" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round"
                      d="M7 17l9.2-9.2M17 17V7H7" />
              </svg>
            </div>
            <span className="text-sm font-semibold text-white/90">Confirmar compra</span>
          </div>

          {/* Details */}
          <div className="flex flex-col gap-2">
            <Row label="Activo" value={nombre} highlight />
            <Row label="Ticker" value={ticker} />
            <Row label="Tipo" value={typeLabel} />
            <Row label="Acciones" value={shares.toLocaleString('es-ES')} highlight />
            <Row label="Precio medio"
                 value={`${avgPrice.toLocaleString('es-ES', { minimumFractionDigits: 2 })} por acción`}
                 highlight />
          </div>

          <p className="text-xs text-white/40 leading-relaxed">
            Comprueba los datos antes de confirmar. Esta operación añadirá el activo a tu cartera.
          </p>

          {/* Actions */}
          <div className="flex gap-2 pt-1">
            <button
              onClick={onCancel}
              className="flex-1 py-2.5 rounded-[14px] text-sm font-medium
                         bg-white/5 border border-white/10 text-white/60
                         hover:bg-white/10 hover:text-white/80 transition-all duration-200 cursor-pointer"
            >
              Cancelar
            </button>
            <button
              onClick={onConfirm}
              className="flex-1 py-2.5 rounded-[14px] text-sm font-semibold
                         bg-unicaja text-white shadow-[0_0_20px_rgba(0,166,81,0.35)]
                         hover:bg-unicaja-dark transition-all duration-200 cursor-pointer"
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
    <div className="flex justify-between items-center py-2 border-b border-white/5 last:border-0">
      <span className="text-xs text-white/45">{label}</span>
      <span className={`text-sm font-medium ${highlight ? 'text-white/90' : 'text-white/65'}`}>
        {value}
      </span>
    </div>
  )
}
