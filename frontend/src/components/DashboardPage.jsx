import { useEffect, useRef, useState } from 'react'
import { apiGet, apiPost } from '../services/api'
import InlineChart from './InlineChart'

const formatEur = (value) =>
  typeof value === 'number'
    ? value.toLocaleString('es-ES', { style: 'currency', currency: 'EUR' })
    : value

const SEVERITY_STYLE = {
  critical: { border: 'border-[#F3D9D8]', bg: 'bg-[#FDF4F3]', badge: 'bg-[#9F2F2D] text-white', ring: 'ring-[#9F2F2D]/10' },
  warning: { border: 'border-[#F1E4C6]', bg: 'bg-[#FDF9F0]', badge: 'bg-[#956400] text-white', ring: 'ring-[#956400]/10' },
  info: { border: 'border-[#EAEAEA]', bg: 'bg-white', badge: 'bg-[#111111] text-white', ring: 'ring-black/5' },
}

const TYPE_META = {
  budget_warning: {
    label: 'Presupuesto',
    icon: (
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-8.99 3.75h.008v.008h-.008v-.008z" />
    ),
  },
  anomaly: {
    label: 'Anomalía',
    icon: (
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126zM12 15.75h.007v.008H12v-.008z" />
    ),
  },
  positive: {
    label: 'Buena noticia',
    icon: (
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M2.25 18L9 11.25l4.306 4.306a11.95 11.95 0 015.814-5.518l2.74-1.22m0 0l-5.94-2.28m5.94 2.28l-2.28 5.941" />
    ),
  },
  goal_progress: {
    label: 'Objetivo',
    icon: (
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M3 3v1.5M3 21v-6m0 0l2.77-.693a9 9 0 016.208.682l.108.054a9 9 0 006.086.71l3.114-.732a48.524 48.524 0 01-.005-10.499l-3.11.732a9 9 0 01-6.085-.711l-.108-.054a9 9 0 00-6.208-.682L3 4.5M3 15V4.5" />
    ),
  },
  weekly_summary: {
    label: 'Resumen semanal',
    icon: (
      <path strokeLinecap="round" strokeLinejoin="round"
        d="M6.75 3v2.25M17.25 3v2.25M3 18.75V7.5a2.25 2.25 0 012.25-2.25h13.5A2.25 2.25 0 0121 7.5v11.25m-18 0A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75m-18 0v-7.5A2.25 2.25 0 015.25 9h13.5A2.25 2.25 0 0121 11.25v7.5" />
    ),
  },
}

function TypeIcon({ type }) {
  const meta = TYPE_META[type] || TYPE_META.positive
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth="1.8" viewBox="0 0 24 24">
      {meta.icon}
    </svg>
  )
}

function Card({ card, onOpen }) {
  const sev = SEVERITY_STYLE[card.severity] || SEVERITY_STYLE.info
  const meta = TYPE_META[card.type] || TYPE_META.positive
  const isWide = card.card_type === 'chart' || card.type === 'weekly_summary'

  return (
    <button
      onClick={() => onOpen(card)}
      className={`group text-left rounded-[14px] p-5 w-full h-full cursor-pointer flex flex-col
        border ${sev.border} ${sev.bg}
        transition-all duration-200 ease-spring hover:shadow-[0_4px_16px_rgba(0,0,0,0.08)] hover:-translate-y-0.5
        ${isWide ? 'sm:col-span-2' : ''}`}
    >
      {/* Cabecera: icono + tipo + severidad */}
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <span className={`flex items-center justify-center w-7 h-7 rounded-full ${sev.badge}`}>
            <TypeIcon type={card.type} />
          </span>
          <span className="text-[11px] font-semibold text-[#787774] uppercase tracking-[0.06em]">
            {meta.label}
          </span>
        </div>
        {card.severity === 'critical' && (
          <span className="text-[10px] font-bold text-[#9F2F2D] uppercase tracking-wide">Urgente</span>
        )}
      </div>

      <p className="text-[15px] font-semibold text-[#111111] leading-snug mb-2">
        {card.title}
      </p>

      {card.card_type === 'stat' ? (
        <p className="text-2xl font-bold text-[#111111] leading-tight mt-1 mb-1">{card.body}</p>
      ) : (
        <p className="text-sm text-[#4A4A47] leading-relaxed flex-1">{card.body}</p>
      )}

      {card.card_type === 'chart' && card.chart_type && card.chart_data?.length > 0 && (
        <div className="mt-3 pointer-events-none">
          <InlineChart chartType={card.chart_type} chartData={card.chart_data} chartTitle={card.chart_title} />
        </div>
      )}

      {card.cta_prompt && (
        <div className="flex items-center gap-1.5 text-xs font-medium text-[#111111] mt-4 pt-3 border-t border-black/[0.06]
          group-hover:gap-2.5 transition-all duration-200 ease-spring">
          <span className="truncate">{card.cta_prompt}</span>
          <svg className="w-3.5 h-3.5 flex-none" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
          </svg>
        </div>
      )}
    </button>
  )
}

export default function DashboardPage({ onOpenCard }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState(null)
  const autoRefreshed = useRef(false)

  async function load() {
    try {
      const res = await apiGet('/dashboard/')
      setData(res)
      setError(null)
      return res
    } catch {
      setError('No se pudo cargar el dashboard.')
      return null
    } finally {
      setLoading(false)
    }
  }

  async function handleRefresh() {
    setRefreshing(true)
    try {
      const res = await apiPost('/dashboard/refresh', {})
      setData(res)
      setError(null)
    } catch {
      setError('No se pudo actualizar el dashboard.')
    } finally {
      setRefreshing(false)
    }
  }

  useEffect(() => {
    if (autoRefreshed.current) return
    autoRefreshed.current = true
    // Al entrar en la app se muestra primero lo que ya hubiera guardado (rápido, sin
    // esperar al LLM) y a continuación se dispara una regeneración en segundo plano, para
    // que el usuario no tenga que acordarse de pulsar "Actualizar ahora" cada vez.
    load().then(() => handleRefresh())
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-sm text-[#787774]">
        Cargando dashboard…
      </div>
    )
  }

  const resumen = data?.resumen
  const cards = data?.tarjetas || []

  return (
    <div className="flex flex-col h-full overflow-y-auto bg-[#FBFBFA] px-8 py-6">
      {/* Resumen rápido */}
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <div className="flex gap-6 flex-wrap">
          {resumen && (
            <>
              <div>
                <p className="text-[11px] text-[#787774] uppercase tracking-[0.06em] mb-0.5">Saldo</p>
                <p className="text-lg font-semibold text-[#111111]">{formatEur(resumen.balance)}</p>
              </div>
              <div>
                <p className="text-[11px] text-[#787774] uppercase tracking-[0.06em] mb-0.5">Ingresos</p>
                <p className="text-lg font-semibold text-[#346538]">{formatEur(resumen.total_income)}</p>
              </div>
              <div>
                <p className="text-[11px] text-[#787774] uppercase tracking-[0.06em] mb-0.5">Gastos</p>
                <p className="text-lg font-semibold text-[#9F2F2D]">{formatEur(resumen.total_expenses)}</p>
              </div>
            </>
          )}
        </div>
        <button
          onClick={handleRefresh}
          disabled={refreshing}
          className="flex-none flex items-center gap-1.5 text-xs font-medium text-[#787774] bg-white border border-[#EAEAEA]
            rounded-[6px] px-3 py-1.5 cursor-pointer hover:border-[#111111] hover:text-[#111111]
            transition-all duration-200 ease-spring disabled:opacity-40"
        >
          {refreshing && (
            <svg className="w-3 h-3 animate-spin" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          )}
          {refreshing ? 'Analizando con IA…' : 'Actualizar ahora'}
        </button>
      </div>

      {error && <p className="text-xs text-[#9F2F2D] mb-4">{error}</p>}

      {/* Tarjetas generativas */}
      {cards.length === 0 ? (
        <div className="flex-1 flex items-center justify-center text-sm text-[#787774] text-center max-w-sm mx-auto">
          {refreshing
            ? 'Analizando tu situación financiera…'
            : 'Todavía no hay tarjetas generadas. Pulsa "Actualizar ahora" para que la IA analice tu situación financiera.'}
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 auto-rows-fr gap-4">
          {cards.map((card) => (
            <Card key={card.id} card={card} onOpen={onOpenCard} />
          ))}
        </div>
      )}
    </div>
  )
}
