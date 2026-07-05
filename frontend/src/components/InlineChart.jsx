import { useRef, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell,
  Legend, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
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

async function exportAsPng(containerRef) {
  const svgEl = containerRef.current?.querySelector('svg')
  if (!svgEl) return null

  const rect = svgEl.getBoundingClientRect()
  const width = Math.round(rect.width) || 600
  const height = Math.round(rect.height) || 300

  const clone = svgEl.cloneNode(true)
  clone.setAttribute('width', width)
  clone.setAttribute('height', height)

  const svgStr = new XMLSerializer().serializeToString(clone)
  const svgBlob = new Blob([svgStr], { type: 'image/svg+xml;charset=utf-8' })
  const svgUrl = URL.createObjectURL(svgBlob)

  return new Promise((resolve) => {
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = width
      canvas.height = height
      const ctx = canvas.getContext('2d')
      ctx.fillStyle = '#050A08'
      ctx.fillRect(0, 0, width, height)
      ctx.drawImage(img, 0, 0)
      URL.revokeObjectURL(svgUrl)
      canvas.toBlob((blob) => resolve(blob), 'image/png')
    }
    img.onerror = () => { URL.revokeObjectURL(svgUrl); resolve(null) }
    img.src = svgUrl
  })
}

export default function InlineChart({ chartType, chartData, chartTitle }) {
  const containerRef = useRef(null)
  const [status, setStatus] = useState(null) // null | 'copying' | 'copied' | 'downloaded'

  async function handleCopyPng() {
    setStatus('copying')
    const blob = await exportAsPng(containerRef)
    if (!blob) { setStatus(null); return }

    try {
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
      setStatus('copied')
    } catch {
      // Clipboard API blocked — fallback to download
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `${chartTitle || 'grafico'}.png`
      a.click()
      URL.revokeObjectURL(url)
      setStatus('downloaded')
    }

    setTimeout(() => setStatus(null), 2500)
  }

  const buttonLabel = {
    null: 'Copiar PNG',
    copying: 'Generando…',
    copied: '¡Copiado!',
    downloaded: '¡Descargado!',
  }[status]

  return (
    <div className="bezel-outer bubble-animate w-full max-w-[92%]">
      <div className="bezel-inner rounded-[19px] p-4 flex flex-col gap-3">
        {/* Header */}
        {chartTitle && (
          <p className="text-xs font-semibold text-white/60 leading-none">{chartTitle}</p>
        )}

        {/* Chart */}
        <div ref={containerRef}>
          <ResponsiveContainer width="100%" height={200}>
            {chartType === 'bar' ? (
              <BarChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
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
              <LineChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
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
                <Pie data={chartData} cx="50%" cy="50%" outerRadius={80} innerRadius={40} dataKey="value" nameKey="name" paddingAngle={2}>
                  {chartData.map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} stroke="none" />
                  ))}
                </Pie>
                <Tooltip content={<CustomTooltip />} />
                <Legend iconType="circle" iconSize={8} wrapperStyle={{ color: 'rgba(255,255,255,0.45)', fontSize: 11 }} />
              </PieChart>
            )}
          </ResponsiveContainer>
        </div>

        {/* Copy PNG button */}
        <div className="flex justify-end">
          <button
            onClick={handleCopyPng}
            disabled={status === 'copying'}
            className="flex items-center gap-1.5 text-[11px] font-medium text-white/40
              bg-white/5 border border-white/8 rounded-full px-3 py-1.5
              hover:bg-white/10 hover:text-white/70 hover:border-white/15
              transition-all duration-300 ease-spring cursor-pointer
              disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {status === 'copied' || status === 'downloaded' ? (
              <svg className="w-3 h-3 text-unicaja" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 12.75l6 6 9-13.5" />
              </svg>
            ) : (
              <svg className="w-3 h-3" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5M16.5 12L12 16.5m0 0L7.5 12m4.5 4.5V3" />
              </svg>
            )}
            {buttonLabel}
          </button>
        </div>
      </div>
    </div>
  )
}
