import { useEffect, useState } from 'react'
import ChatBox from './components/ChatBox'
import ChartPanel from './components/ChartPanel'
import { useRevealObserver } from './hooks/useRevealObserver'
import { getAccounts, getSummary } from './services/api'

export default function App() {
  const [chart, setChart] = useState({ chartType: null, chartData: null, chartTitle: null })
  const [summary, setSummary] = useState(null)
  const [accounts, setAccounts] = useState([])

  useEffect(() => {
    getSummary().then(setSummary).catch(console.error)
    getAccounts().then(setAccounts).catch(console.error)
  }, [])

  useRevealObserver([summary, accounts])

  const maxCategoryTotal = summary?.top_categories?.[0]?.total ?? 1

  return (
    <div className="grid grid-cols-12 h-screen gap-3 p-3 overflow-hidden">
      {/* Sidebar */}
      <aside className="col-span-3 bezel-outer-lg flex flex-col overflow-hidden">
        <div className="bezel-inner-lg flex flex-col flex-1 overflow-y-auto px-4 py-5 gap-5">

          {/* Logo */}
          <div className="flex items-center gap-3 pb-4 border-b border-white/[0.08]">
            <div className="w-9 h-9 rounded-xl bg-unicaja/20 border border-unicaja/40 flex items-center justify-center text-unicaja text-base font-bold glow-pulse flex-none">
              U
            </div>
            <div>
              <div className="text-xs font-semibold text-white/85 leading-none">Habla con</div>
              <div className="text-[11px] text-white/40 leading-tight mt-0.5">tu dinero</div>
            </div>
          </div>

          {/* Balance hero */}
          {summary && (
            <div className="bezel-outer-accent animate-reveal">
              <div className="bezel-inner-accent rounded-[19px] p-4">
                <p className="text-[11px] font-medium text-unicaja-light/70 mb-1 uppercase tracking-wider">Saldo total</p>
                <p className="text-2xl font-bold tracking-tight text-white">
                  {summary.balance.toLocaleString('es-ES', { style: 'currency', currency: 'EUR' })}
                </p>
                <div className="flex gap-4 mt-3 pt-3 border-t border-white/10">
                  <div>
                    <p className="text-[10px] text-white/40">Ingresos</p>
                    <p className="text-sm font-semibold text-unicaja-light">
                      {summary.total_income.toLocaleString('es-ES', { style: 'currency', currency: 'EUR' })}
                    </p>
                  </div>
                  <div>
                    <p className="text-[10px] text-white/40">Gastos</p>
                    <p className="text-sm font-semibold text-white/70">
                      {summary.total_expenses.toLocaleString('es-ES', { style: 'currency', currency: 'EUR' })}
                    </p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Cuentas */}
          {accounts.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold text-white/30 uppercase tracking-widest mb-2.5 px-1">Cuentas</p>
              <div className="flex flex-col gap-2">
                {accounts.map((acc, idx) => (
                  <div
                    key={acc.id}
                    className="bezel-outer animate-reveal"
                    data-delay={String((idx + 1) * 100)}
                  >
                    <div className="bezel-inner rounded-[19px] px-3 py-2.5 transition-all duration-300 ease-spring hover:bg-white/[0.04] cursor-pointer">
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="text-xs font-medium text-white/70">{acc.name}</span>
                        <span className="text-xs font-bold text-white/90">
                          {acc.balance.toLocaleString('es-ES', { style: 'currency', currency: 'EUR' })}
                        </span>
                      </div>
                      <span className="inline-block text-[10px] font-medium text-unicaja bg-unicaja/10 border border-unicaja/20 rounded-full px-2 py-0.5">
                        {acc.account_type}
                      </span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Top categorías */}
          {summary?.top_categories?.length > 0 && (
            <div className="animate-reveal" data-delay="400">
              <p className="text-[10px] font-semibold text-white/30 uppercase tracking-widest mb-2.5 px-1">Top categorías</p>
              <div className="flex flex-col gap-3">
                {summary.top_categories.map((c, i) => (
                  <div key={i}>
                    <div className="flex justify-between items-center mb-1.5">
                      <span className="text-xs text-white/55 capitalize">{c.category}</span>
                      <span className="text-xs font-semibold text-white/70">
                        {c.total.toLocaleString('es-ES', { style: 'currency', currency: 'EUR' })}
                      </span>
                    </div>
                    <div className="h-1 bg-white/[0.08] rounded-full overflow-hidden">
                      <div
                        className="h-full bg-unicaja rounded-full transition-all duration-700 ease-spring"
                        style={{ width: `${Math.min((c.total / maxCategoryTotal) * 100, 100)}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Spacer */}
          <div className="flex-1" />

          {/* Footer */}
          <p className="text-[10px] text-white/20 text-center pt-3 border-t border-white/[0.06]">
            Cátedra Unicaja · UGR
          </p>
        </div>
      </aside>

      {/* Main */}
      <main className="col-span-9 flex flex-col gap-3 overflow-hidden">
        {/* Floating pill header */}
        <div className="flex justify-center flex-none pt-0.5">
          <header className="floating-pill px-6 py-3 flex items-center gap-6">
            <div>
              <h1 className="text-sm font-semibold text-white/90 leading-none">Asistente Financiero</h1>
              <p className="text-[11px] text-white/38 leading-tight mt-0.5">
                Consulta tu información en lenguaje natural
              </p>
            </div>
            <div className="flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-unicaja glow-pulse" />
              <span className="text-[11px] text-white/40 font-medium">Activo</span>
            </div>
          </header>
        </div>

        {/* Chart panel */}
        {chart.chartType && chart.chartData && (
          <div className="flex-none">
            <ChartPanel
              chartType={chart.chartType}
              chartData={chart.chartData}
              chartTitle={chart.chartTitle}
              onClose={() => setChart({ chartType: null, chartData: null, chartTitle: null })}
            />
          </div>
        )}

        {/* Chat */}
        <div className="flex-1 min-h-0 bezel-outer">
          <div className="bezel-inner h-full flex flex-col overflow-hidden rounded-[19px]">
            <ChatBox onChartData={setChart} hasChart={!!chart.chartType} />
          </div>
        </div>
      </main>
    </div>
  )
}
