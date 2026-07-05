const API_URL = ''

export async function sendChatMessage(message, history = [], userId = 1) {
  const res = await fetch(`${API_URL}/chat/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, user_id: userId, history }),
  })
  if (!res.ok) throw new Error('Error en la respuesta del servidor')
  return res.json()
}

export async function getSummary(userId = 1) {
  const res = await fetch(`${API_URL}/transactions/summary?user_id=${userId}`)
  if (!res.ok) throw new Error('Error obteniendo resumen')
  return res.json()
}

export async function getAccounts(userId = 1) {
  const res = await fetch(`${API_URL}/transactions/accounts?user_id=${userId}`)
  if (!res.ok) throw new Error('Error obteniendo cuentas')
  return res.json()
}
