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

  return (
    <div style={styles.root}>
      <aside style={styles.sidebar}>
        <div style={styles.logo}>
          <span style={styles.logoIcon}>💰</span>
          <span style={styles.logoText}>Habla con tu dinero</span>
        </div>

        {summary && (
          <div style={styles.statsSection}>
            <StatCard label="Saldo total" value={`${summary.balance.toFixed(2)}€`} color="#10b981" />
            <StatCard label="Ingresos" value={`${summary.total_income.toFixed(2)}€`} color="#6366f1" />
            <StatCard label="Gastos" value={`${summary.total_expenses.toFixed(2)}€`} color="#ef4444" />
          </div>
        )}

        {accounts.length > 0 && (
          <div style={styles.accountsSection}>
            <div style={styles.sectionTitle}>Cuentas</div>
            {accounts.map((acc) => (
              <div key={acc.id} style={styles.accountCard}>
                <div style={styles.accountName}>{acc.name}</div>
                <div style={styles.accountBalance}>{acc.balance.toFixed(2)}€</div>
                <div style={styles.accountType}>{acc.account_type}</div>
              </div>
            ))}
          </div>
        )}

        {summary?.top_categories?.length > 0 && (
          <div style={styles.accountsSection}>
            <div style={styles.sectionTitle}>Top categorías</div>
            {summary.top_categories.map((c, i) => (
              <div key={i} style={styles.categoryRow}>
                <span style={styles.categoryName}>{c.category}</span>
                <span style={styles.categoryAmount}>{c.total.toFixed(2)}€</span>
              </div>
            ))}
          </div>
        )}
      </aside>

      <main style={styles.main}>
        <div style={styles.topPanel}>
          <ChartPanel
            chartType={chart.chartType}
            chartData={chart.chartData}
            chartTitle={chart.chartTitle}
          />
        </div>
        <div style={styles.bottomPanel}>
          <ChatBox onChartData={setChart} />
        </div>
      </main>
    </div>
  )
}

function StatCard({ label, value, color }) {
  return (
    <div style={{ ...styles.statCard, borderLeft: `3px solid ${color}` }}>
      <div style={styles.statLabel}>{label}</div>
      <div style={{ ...styles.statValue, color }}>{value}</div>
    </div>
  )
}

const styles = {
  root: {
    display: 'flex',
    height: '100vh',
    background: '#0f172a',
    gap: 0,
  },
  sidebar: {
    width: 240,
    minWidth: 240,
    background: '#0f172a',
    borderRight: '1px solid #1e293b',
    display: 'flex',
    flexDirection: 'column',
    gap: 16,
    padding: '20px 16px',
    overflowY: 'auto',
  },
  logo: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    paddingBottom: 16,
    borderBottom: '1px solid #1e293b',
  },
  logoIcon: { fontSize: 22 },
  logoText: { color: '#e2e8f0', fontWeight: 700, fontSize: 14 },
  statsSection: { display: 'flex', flexDirection: 'column', gap: 8 },
  statCard: {
    background: '#1e293b',
    borderRadius: 8,
    padding: '10px 12px',
  },
  statLabel: { color: '#64748b', fontSize: 11, marginBottom: 2 },
  statValue: { fontSize: 16, fontWeight: 700 },
  accountsSection: { display: 'flex', flexDirection: 'column', gap: 6 },
  sectionTitle: { color: '#475569', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1, marginBottom: 4 },
  accountCard: {
    background: '#1e293b',
    borderRadius: 8,
    padding: '10px 12px',
  },
  accountName: { color: '#94a3b8', fontSize: 12, marginBottom: 2 },
  accountBalance: { color: '#e2e8f0', fontSize: 15, fontWeight: 600 },
  accountType: { color: '#475569', fontSize: 11, marginTop: 2 },
  categoryRow: {
    display: 'flex',
    justifyContent: 'space-between',
    padding: '6px 0',
    borderBottom: '1px solid #1e293b',
  },
  categoryName: { color: '#94a3b8', fontSize: 12, textTransform: 'capitalize' },
  categoryAmount: { color: '#ef4444', fontSize: 12, fontWeight: 600 },
  main: {
    flex: 1,
    display: 'flex',
    flexDirection: 'column',
    gap: 12,
    padding: 16,
    overflow: 'hidden',
  },
  topPanel: { flex: 1, minHeight: 0 },
  bottomPanel: { height: 380, minHeight: 380 },
}
