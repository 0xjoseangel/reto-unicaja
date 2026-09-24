import { useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { apiPost } from '../services/api'

export default function LoginPage() {
  const { login } = useAuth()
  const [tab, setTab] = useState('login')
  const [form, setForm] = useState({ name: '', email: '', password: '' })
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  function handleChange(e) {
    setForm(prev => ({ ...prev, [e.target.name]: e.target.value }))
    setError('')
  }

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      const endpoint = tab === 'login' ? '/auth/login' : '/auth/register'
      const body = tab === 'login'
        ? { email: form.email, password: form.password }
        : { name: form.name, email: form.email, password: form.password }
      const data = await apiPost(endpoint, body)
      login(data)
    } catch (err) {
      setError(err.message || 'Ha ocurrido un error. Inténtalo de nuevo.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-[#FBFBFA] items-center justify-center">
      <div className="w-full max-w-sm px-4">

        {/* Logo / branding */}
        <div className="mb-8 text-center">
          <p className="text-[10px] font-medium text-[#787774] uppercase tracking-[0.1em] mb-1">
            Cátedra Unicaja · UGR
          </p>
          <h1 className="text-xl font-semibold text-[#111111]">Asistente Financiero</h1>
          <p className="text-xs text-[#787774] mt-1">Habla con tu dinero</p>
        </div>

        {/* Card */}
        <div className="bg-white border border-[#EAEAEA] rounded-[12px] shadow-[0_2px_12px_rgba(0,0,0,0.06)] overflow-hidden">

          {/* Tabs */}
          <div className="flex border-b border-[#EAEAEA]">
            {['login', 'register'].map(t => (
              <button
                key={t}
                onClick={() => { setTab(t); setError('') }}
                className={`flex-1 py-3 text-xs font-medium transition-colors duration-150 cursor-pointer
                  ${tab === t
                    ? 'text-[#111111] border-b-2 border-[#111111] -mb-px'
                    : 'text-[#787774] hover:text-[#111111]'
                  }`}
              >
                {t === 'login' ? 'Entrar' : 'Crear cuenta'}
              </button>
            ))}
          </div>

          {/* Form */}
          <form onSubmit={handleSubmit} className="p-6 flex flex-col gap-4">
            {tab === 'register' && (
              <div className="flex flex-col gap-1.5">
                <label className="text-xs font-medium text-[#787774]">Nombre</label>
                <input
                  name="name"
                  type="text"
                  value={form.name}
                  onChange={handleChange}
                  placeholder="Tu nombre"
                  required
                  className="w-full text-sm text-[#111111] bg-[#FBFBFA] border border-[#EAEAEA]
                    rounded-[6px] px-3 py-2 outline-none placeholder-[#BDBDBD]
                    focus:border-[#111111] transition-colors duration-150"
                />
              </div>
            )}

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-[#787774]">Email</label>
              <input
                name="email"
                type="email"
                value={form.email}
                onChange={handleChange}
                placeholder="tu@email.com"
                required
                className="w-full text-sm text-[#111111] bg-[#FBFBFA] border border-[#EAEAEA]
                  rounded-[6px] px-3 py-2 outline-none placeholder-[#BDBDBD]
                  focus:border-[#111111] transition-colors duration-150"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-[#787774]">Contraseña</label>
              <input
                name="password"
                type="password"
                value={form.password}
                onChange={handleChange}
                placeholder="••••••••"
                required
                className="w-full text-sm text-[#111111] bg-[#FBFBFA] border border-[#EAEAEA]
                  rounded-[6px] px-3 py-2 outline-none placeholder-[#BDBDBD]
                  focus:border-[#111111] transition-colors duration-150"
              />
            </div>

            {error && (
              <p className="text-xs text-red-600 bg-red-50 border border-red-100 rounded-[6px] px-3 py-2">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-[#111111] text-white text-sm font-medium
                py-2.5 rounded-[6px] cursor-pointer
                hover:bg-[#333333] active:scale-[0.99]
                transition-all duration-200
                disabled:opacity-40 disabled:cursor-not-allowed mt-1"
            >
              {loading
                ? 'Cargando...'
                : tab === 'login' ? 'Entrar' : 'Crear cuenta'}
            </button>

            {tab === 'login' && (
              <p className="text-center text-xs text-[#787774]">
                Usuario demo:{' '}
                <button
                  type="button"
                  onClick={() => setForm({ name: '', email: 'joseangelcarretero300@gmail.com', password: 'demo1234' })}
                  className="text-[#111111] underline underline-offset-2 cursor-pointer"
                >
                  Rellenar
                </button>
              </p>
            )}
          </form>
        </div>
      </div>
    </div>
  )
}
