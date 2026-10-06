function getToken() {
  return localStorage.getItem('token')
}

export function apiFetch(url, options = {}) {
  const token = getToken()
  return fetch(url, {
    ...options,
    headers: {
      ...(options.headers || {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
  })
}

// `signal` (AbortController) permite cortar el stream, p. ej. al interrumpir la voz
export function apiStream(url, body, { signal } = {}) {
  return apiFetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
}

export async function apiPost(url, body) {
  const res = await apiFetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Error ${res.status}`)
  }
  return res.json()
}

export async function apiGet(url) {
  const res = await apiFetch(url)
  if (!res.ok) {
    const err = await res.json().catch(() => ({}))
    throw new Error(err.detail || `Error ${res.status}`)
  }
  return res.json()
}

// Lee un stream SSE (data: {...}\n\n) y llama a onEvent con cada evento parseado
export async function readSSE(res, onEvent) {
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''
    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const raw = line.slice(6).trim()
      if (!raw) continue
      let event
      try { event = JSON.parse(raw) } catch { continue }
      onEvent(event)
    }
  }
}

// Aprueba o rechaza una operación propuesta por el agente (Bizum, inversión).
// Devuelve la Response: SSE con la respuesta del agente, o 404/409/410 con { detail }.
export function decideAction(actionId, decision, options) {
  return apiStream(`/chat/actions/${actionId}`, { decision }, options)
}
