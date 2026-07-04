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

const COLORS = ['#00A651', '#10B981', '#3B82F6', '#8B5CF6', '#F59E0B', '#EF4444', '#14B8A6', '#EC4899']

const formatEur = (value) =>
  typeof value === 'number'
    ? value.toLocaleString('es-ES', { style: 'currency', currency: 'EUR' })
    : value

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-white border border-gray-100 rounded-xl shadow-lg px-3 py-2 text-sm">
      {label && <p className="text-gray-500 text-xs mb-1">{label}</p>}
      <p className="font-semibold text-gray-800">{formatEur(payload[0].value)}</p>
    </div>
  )
}

export default function ChartPanel({ chartType, chartData, chartTitle, onClose }) {
  if (!chartType || !chartData || chartData.length === 0) return null

  return (
    <div className="mx-4 mt-4 bg-white rounded-2xl border border-gray-100 shadow-sm p-4">
      <div className="flex items-center justify-between mb-3">
        {chartTitle && (
          <h3 className="text-sm font-semibold text-gray-700">{chartTitle}</h3>
        )}
        {onClose && (
          <button
            onClick={onClose}
            className="ml-auto text-gray-300 hover:text-gray-500 transition-colors text-lg leading-none cursor-pointer"
            aria-label="Cerrar gráfico"
          >
            ×
          </button>
        )}
      </div>

      <ResponsiveContainer width="100%" height={220}>
        {chartType === 'bar' ? (
          <BarChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" vertical={false} />
            <XAxis dataKey="name" tick={{ fill: '#94A3B8', fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis tickFormatter={formatEur} tick={{ fill: '#94A3B8', fontSize: 11 }} axisLine={false} tickLine={false} width={70} />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: '#F8FAFC' }} />
            <Bar dataKey="value" fill="#00A651" radius={[6, 6, 0, 0]} maxBarSize={48} />
          </BarChart>
        ) : chartType === 'line' ? (
          <LineChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#F1F5F9" vertical={false} />
            <XAxis dataKey="name" tick={{ fill: '#94A3B8', fontSize: 11 }} axisLine={false} tickLine={false} />
            <YAxis tickFormatter={formatEur} tick={{ fill: '#94A3B8', fontSize: 11 }} axisLine={false} tickLine={false} width={70} />
            <Tooltip content={<CustomTooltip />} />
            <Line
              type="monotone"
              dataKey="value"
              stroke="#00A651"
              strokeWidth={2.5}
              dot={{ fill: '#00A651', r: 4, strokeWidth: 0 }}
              activeDot={{ r: 6, fill: '#00A651' }}
            />
          </LineChart>
        ) : (
          <PieChart>
            <Pie
              data={chartData}
              cx="50%"
              cy="50%"
              outerRadius={88}
              innerRadius={44}
              dataKey="value"
              nameKey="name"
              paddingAngle={2}
            >
              {chartData.map((_, i) => (
                <Cell key={i} fill={COLORS[i % COLORS.length]} stroke="none" />
              ))}
            </Pie>
            <Tooltip content={<CustomTooltip />} />
            <Legend
              iconType="circle"
              iconSize={8}
              wrapperStyle={{ color: '#64748B', fontSize: 11 }}
            />
          </PieChart>
        )}
      </ResponsiveContainer>
    </div>
  )
}
