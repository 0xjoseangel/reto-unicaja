import { useRef, useState } from 'react'
import {
  Bar, BarChart, CartesianGrid, Cell,
  Legend, Line, LineChart, Pie, PieChart,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'

const COLORS = ['#346538', '#787774', '#1F6C9F', '#956400', '#9F2F2D', '#111111', '#444444', '#AAAAAA']

const formatEur = (value) =>
  typeof value === 'number'
    ? value.toLocaleString('es-ES', { style: 'currency', currency: 'EUR' })
    : value

function CustomTooltip({ active, payload, label }) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-white border border-[#EAEAEA] rounded-[8px] px-3 py-2 text-sm"
         style={{ boxShadow: '0 2px 8px rgba(0,0,0,0.06)', pointerEvents: 'none' }}>
      {label && <p className="text-[#787774] text-xs mb-1">{label}</p>}
      <p className="font-semibold text-[#111111]">{formatEur(payload[0].value)}</p>
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
      ctx.fillStyle = '#FFFFFF'
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
  const [status, setStatus] = useState(null)

  async function handleCopyPng() {
    setStatus('copying')
    const blob = await exportAsPng(containerRef)
    if (!blob) { setStatus(null); return }

    try {
      await navigator.clipboard.write([new ClipboardItem({ 'image/png': blob })])
      setStatus('copied')
    } catch {
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
    <div className="bg-white border border-[#EAEAEA] rounded-[12px] p-4 bubble-animate w-full max-w-[92%]"
         style={{ boxShadow: '0 1px 4px rgba(0,0,0,0.04)' }}>
      {/* Header */}
      {chartTitle && (
        <p className="text-xs font-semibold text-[#787774] uppercase tracking-[0.06em] leading-none mb-3">
          {chartTitle}
        </p>
      )}

      {/* Chart */}
      <div ref={containerRef}>
        <ResponsiveContainer width="100%" height={200}>
          {chartType === 'bar' ? (
            <BarChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.05)" vertical={false} />
              <XAxis dataKey="name" tick={{ fill: '#787774', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={formatEur} tick={{ fill: '#787774', fontSize: 11 }} axisLine={false} tickLine={false} width={70} />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(0,0,0,0.03)' }} />
              <Bar dataKey="value" fill="#111111" radius={[4, 4, 0, 0]} maxBarSize={40} />
            </BarChart>
          ) : chartType === 'line' ? (
            <LineChart data={chartData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.05)" vertical={false} />
              <XAxis dataKey="name" tick={{ fill: '#787774', fontSize: 11 }} axisLine={false} tickLine={false} />
              <YAxis tickFormatter={formatEur} tick={{ fill: '#787774', fontSize: 11 }} axisLine={false} tickLine={false} width={70} />
              <Tooltip content={<CustomTooltip />} />
              <Line
                type="monotone"
                dataKey="value"
                stroke="#111111"
                strokeWidth={2}
                dot={{ fill: '#111111', r: 3, strokeWidth: 0 }}
                activeDot={{ r: 5, fill: '#111111' }}
              />
            </LineChart>
          ) : (
            <PieChart>
              <Pie data={chartData} cx="50%" cy="50%" outerRadius={80} innerRadius={40}
                   dataKey="value" nameKey="name" paddingAngle={2}>
                {chartData.map((_, i) => (
                  <Cell key={i} fill={COLORS[i % COLORS.length]} stroke="none" />
                ))}
              </Pie>
              <Tooltip content={<CustomTooltip />} />
              <Legend iconType="circle" iconSize={8} wrapperStyle={{ color: '#787774', fontSize: 11 }} />
            </PieChart>
          )}
        </ResponsiveContainer>
      </div>

      {/* Copy PNG button */}
      <div className="flex justify-end mt-2 pt-2 border-t border-[#EAEAEA]">
        <button
          onClick={handleCopyPng}
          disabled={status === 'copying'}
          className="flex items-center gap-1.5 text-[11px] font-medium text-[#787774]
            bg-[#F7F6F3] border border-[#EAEAEA] rounded-[6px] px-3 py-1.5
            hover:border-[#111111] hover:text-[#111111]
            transition-all duration-200 ease-spring cursor-pointer
            disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {status === 'copied' || status === 'downloaded' ? (
            <svg className="w-3 h-3 text-[#346538]" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24">
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
  )
}
