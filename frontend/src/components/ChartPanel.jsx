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

const COLORS = ['#00A651', '#4CC87A', '#3B82F6', '#8B5CF6', '#F59E0B', '#EF4444', '#14B8A6', '#EC4899']

const formatEur = (value) =>
  typeof value === 'number'
    ? value.toLocaleString('es-ES', { style: 'currency', currency: 'EUR' })
    : value

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="bezel-outer text-sm" style={{ pointerEvents: 'none' }}>
      <div className="bezel-inner rounded-[19px] px-3 py-2">
        {label && <p className="text-white/40 text-xs mb-1">{label}</p>}
        <p className="font-semibold text-white/90">{formatEur(payload[0].value)}</p>
      </div>
    </div>
  )
}

export default function ChartPanel({ chartType, chartData, chartTitle, onClose }) {
  if (!chartType || !chartData || chartData.length === 0) return null

  return (
    <div className="bezel-outer animate-reveal is-visible">
      <div className="bezel-inner rounded-[19px] p-4">
        <div className="flex items-center justify-between mb-3">
          {chartTitle && (
            <h3 className="text-sm font-semibold text-white/75">{chartTitle}</h3>
          )}
          {onClose && (
            <button
              onClick={onClose}
              className="ml-auto w-7 h-7 flex items-center justify-center
                rounded-full bg-white/5 border border-white/[0.08] text-white/40
                hover:bg-white/10 hover:text-white/70 text-lg leading-none
                transition-all duration-300 ease-spring cursor-pointer"
              aria-label="Cerrar gráfico"
            >
              ×
            </button>
          )}
        </div>

        <ResponsiveContainer width="100%" height={200}>
          {chartType === 'bar' ? (
            <BarChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="barGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#4CC87A" stopOpacity={0.9} />
                  <stop offset="100%" stopColor="#00A651" stopOpacity={0.7} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
              <XAxis dataKey="name" tick={{ fill: 'rgba(255,255,255,0.38)', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={formatEur} tick={{ fill: 'rgba(255,255,255,0.38)', fontSize: 11 }} axisLine={false} tickLine={false} width={70} />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
              <Bar dataKey="value" fill="url(#barGradient)" radius={[6, 6, 0, 0]} maxBarSize={48} />
            </BarChart>
          ) : chartType === 'line' ? (
            <LineChart data={chartData} margin={{ top: 4, right: 16, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
              <XAxis dataKey="name" tick={{ fill: 'rgba(255,255,255,0.38)', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={formatEur} tick={{ fill: 'rgba(255,255,255,0.38)', fontSize: 11 }} axisLine={false} tickLine={false} width={70} />
              <Tooltip content={<CustomTooltip />} />
              <Line
                type="monotone"
                dataKey="value"
                stroke="#4CC87A"
                strokeWidth={2.5}
                dot={{ fill: '#4CC87A', r: 4, strokeWidth: 0 }}
                activeDot={{ r: 6, fill: '#4CC87A' }}
              />
            </LineChart>
          ) : (
            <PieChart>
              <Pie
                data={chartData}
                cx="50%"
                cy="50%"
                outerRadius={80}
                innerRadius={40}
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
                wrapperStyle={{ color: 'rgba(255,255,255,0.45)', fontSize: 11 }}
              />
            </PieChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  )
}
