import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

const COLORS = ['#6366f1', '#8b5cf6', '#ec4899', '#f59e0b', '#10b981', '#3b82f6', '#ef4444', '#14b8a6']

const formatEur = (value) => `${value.toFixed(2)}€`

export default function ChartPanel({ chartType, chartData, chartTitle }) {
  if (!chartType || !chartData || chartData.length === 0) {
    return (
      <div style={styles.empty}>
        <p style={styles.emptyText}>Haz una pregunta para ver gráficos aquí</p>
        <p style={styles.emptyHint}>Ejemplo: "¿En qué categorías gasto más?"</p>
      </div>
    )
  }

  return (
    <div style={styles.container}>
      {chartTitle && <h3 style={styles.title}>{chartTitle}</h3>}

      <ResponsiveContainer width="100%" height={280}>
        {chartType === 'bar' ? (
          <BarChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} />
            <YAxis tickFormatter={formatEur} tick={{ fill: '#94a3b8', fontSize: 11 }} />
            <Tooltip formatter={formatEur} contentStyle={styles.tooltip} />
            <Bar dataKey="value" fill="#6366f1" radius={[4, 4, 0, 0]} />
          </BarChart>
        ) : chartType === 'line' ? (
          <LineChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
            <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} />
            <YAxis tickFormatter={formatEur} tick={{ fill: '#94a3b8', fontSize: 11 }} />
            <Tooltip formatter={formatEur} contentStyle={styles.tooltip} />
            <Line type="monotone" dataKey="value" stroke="#6366f1" strokeWidth={2} dot={{ fill: '#6366f1' }} />
          </LineChart>
        ) : (
          <PieChart>
            <Pie
              data={chartData}
              cx="50%"
              cy="50%"
              outerRadius={100}
              dataKey="value"
              nameKey="name"
              label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
              labelLine={{ stroke: '#475569' }}
            >
              {chartData.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} />
              ))}
            </Pie>
            <Tooltip formatter={formatEur} contentStyle={styles.tooltip} />
            <Legend wrapperStyle={{ color: '#94a3b8', fontSize: 12 }} />
          </PieChart>
        )}
      </ResponsiveContainer>
    </div>
  )
}

const styles = {
  container: {
    background: '#1e293b',
    borderRadius: 12,
    padding: '20px',
    height: '100%',
  },
  title: {
    color: '#e2e8f0',
    fontSize: 15,
    fontWeight: 600,
    marginBottom: 16,
  },
  tooltip: {
    background: '#0f172a',
    border: '1px solid #334155',
    borderRadius: 8,
    color: '#e2e8f0',
  },
  empty: {
    background: '#1e293b',
    borderRadius: 12,
    padding: '20px',
    height: '100%',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
  },
  emptyText: {
    color: '#475569',
    fontSize: 15,
  },
  emptyHint: {
    color: '#334155',
    fontSize: 13,
  },
}
