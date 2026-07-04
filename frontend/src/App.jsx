import { useEffect, useState } from 'react'
import ChatBox from './components/ChatBox'
import ChartPanel from './components/ChartPanel'
import { getAccounts, getSummary } from './services/api'

export default function App() {
  const [chart, setChart] = useState({ chartType: null, chartData: null, chartTitle: null })
  const [summary, setSummary] = useState(null)
  const [accounts, setAccounts] = useState([])

  useEffect(() => {
    getSummary().then(setSummary).catch(console.error)
    getAccounts().then(setAccounts).catch(console.error)
  }, [])

  const maxCategoryTotal = summary?.top_categories?.[0]?.total ?? 1

  return (
    <div className="flex h-screen bg-gray-50 overflow-hidden">
      {/* Sidebar */}
      <aside className="w-64 min-w-64 bg-white border-r border-gray-100 flex flex-col overflow-y-auto shadow-sm">
        {/* Logo */}
        <div className="flex items-center gap-3 px-5 py-5 border-b border-gray-100">
          <div className="w-8 h-8 rounded-xl bg-unicaja flex items-center justify-center text-white text-base font-bold shadow-sm">
            U
          </div>
          <div>
            <div className="text-xs font-semibold text-gray-800 leading-none">Habla con</div>
            <div className="text-xs text-gray-400 leading-tight">tu dinero</div>
          </div>
        </div>

        <div className="flex flex-col gap-5 px-4 py-5 flex-1">
          {/* Saldo principal */}
          {summary && (
            <div className="bg-gradient-to-br from-unicaja to-unicaja-dark rounded-2xl p-4 text-white shadow-sm">
              <p className="text-xs font-medium opacity-80 mb-1">Saldo total</p>
              <p className="text-2xl font-bold tracking-tight">
                {summary.balance.toLocaleString('es-ES', { style: 'currency', currency: 'EUR' })}
              </p>
              <div className="flex gap-4 mt-3 pt-3 border-t border-white/20">
                <div>
                  <p className="text-xs opacity-70">Ingresos</p>
                  <p className="text-sm font-semibold">
                    {summary.total_income.toLocaleString('es-ES', { style: 'currency', currency: 'EUR' })}
                  </p>
                </div>
                <div>
                  <p className="text-xs opacity-70">Gastos</p>
                  <p className="text-sm font-semibold">
                    {summary.total_expenses.toLocaleString('es-ES', { style: 'currency', currency: 'EUR' })}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Cuentas */}
          {accounts.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 px-1">Cuentas</p>
              <div className="flex flex-col gap-2">
                {accounts.map((acc) => (
                  <div key={acc.id} className="bg-gray-50 rounded-xl p-3 border border-gray-100 hover:border-unicaja/30 transition-colors">
                    <div className="flex items-center justify-between mb-0.5">
                      <span className="text-xs font-medium text-gray-700">{acc.name}</span>
                      <span className="text-xs font-bold text-gray-900">
                        {acc.balance.toLocaleString('es-ES', { style: 'currency', currency: 'EUR' })}
                      </span>
                    </div>
                    <span className="inline-block text-[10px] font-medium text-unicaja bg-unicaja/10 rounded-full px-2 py-0.5">
                      {acc.account_type}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Top categorías */}
          {summary?.top_categories?.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 px-1">Top categorías</p>
              <div className="flex flex-col gap-2">
                {summary.top_categories.map((c, i) => (
                  <div key={i}>
                    <div className="flex justify-between items-center mb-1">
                      <span className="text-xs text-gray-600 capitalize">{c.category}</span>
                      <span className="text-xs font-semibold text-gray-700">
                        {c.total.toLocaleString('es-ES', { style: 'currency', currency: 'EUR' })}
                      </span>
                    </div>
                    <div className="h-1.5 bg-gray-100 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-unicaja rounded-full"
                        style={{ width: `${Math.min((c.total / maxCategoryTotal) * 100, 100)}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-4 py-3 border-t border-gray-100">
          <p className="text-[10px] text-gray-300 text-center">Cátedra Unicaja · UGR</p>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 flex flex-col overflow-hidden">
        {/* Header */}
        <header className="h-14 bg-white border-b border-gray-100 flex items-center justify-between px-6 flex-none">
          <div>
            <h1 className="text-sm font-semibold text-gray-800">Asistente Financiero</h1>
            <p className="text-xs text-gray-400">Consulta tu información bancaria en lenguaje natural</p>
          </div>
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-unicaja animate-pulse" />
            <span className="text-xs text-gray-400">Activo</span>
          </div>
        </header>

        {/* Chart panel — visible only when there's data */}
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

        {/* Chat — takes remaining space */}
        <div className="flex-1 min-h-0">
          <ChatBox onChartData={setChart} hasChart={!!chart.chartType} />
        </div>
      </main>
    </div>
  )
}
