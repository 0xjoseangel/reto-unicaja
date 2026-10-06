import { utils } from '@ricky0123/vad-web'
import { apiFetch } from './api'

// Transcribe un turno de voz detectado por el VAD (Float32Array, 16 kHz, mono)
export async function transcribeSpeech(samples) {
  const wav = utils.encodeWAV(samples)
  const form = new FormData()
  form.append('file', new Blob([wav], { type: 'audio/wav' }), 'audio.wav')
  const res = await apiFetch('/voice/transcribe', { method: 'POST', body: form })
  if (res.status === 400) return ''   // no se entendió nada
  if (!res.ok) throw new Error('Transcripción fallida')
  const { text } = await res.json()
  return text.trim()
}

// Trocea el texto que llega en streaming en frases completas, para empezar a
// sintetizar la primera sin esperar a la respuesta entera. Las frases muy cortas
// se juntan con la siguiente: cada petición a Piper tiene un coste fijo y los
// cortes muy seguidos suenan entrecortados.
const SENTENCE_END = /[.!?…:;]+["»)]?\s+|\n+/g
const MIN_CHUNK = 40

export class SentenceSplitter {
  constructor() {
    this.buffer = ''
  }

  push(text) {
    this.buffer += text
    const chunks = []
    let start = 0
    let match
    SENTENCE_END.lastIndex = 0
    while ((match = SENTENCE_END.exec(this.buffer)) !== null) {
      const end = match.index + match[0].length
      if (end - start >= MIN_CHUNK) {
        chunks.push(this.buffer.slice(start, end).trim())
        start = end
      }
    }
    this.buffer = this.buffer.slice(start)
    return chunks.filter(Boolean)
  }

  flush() {
    const rest = this.buffer.trim()
    this.buffer = ''
    return rest
  }
}

// Cola de reproducción: cada frase se manda a sintetizar en cuanto llega (en
// paralelo con la reproducción de la anterior) y se reproduce en orden.
// stop() corta en seco: para el audio actual y descarta lo pendiente.
export class SpeechQueue {
  constructor({ onStart } = {}) {
    this.items = []
    this.closed = false
    this.stopped = false
    this.onStart = onStart
    this.abort = new AbortController()
    this.wake = null
    this.audio = null
    this.endCurrent = null
    this.done = this.#run()
  }

  push(text) {
    if (this.stopped || !text) return
    this.items.push(this.#synthesize(text))
    this.#notify()
  }

  // No llegarán más frases; `done` se resuelve al terminar de reproducir todo
  close() {
    this.closed = true
    this.#notify()
  }

  stop() {
    if (this.stopped) return
    this.stopped = true
    this.abort.abort()
    this.audio?.pause()
    this.endCurrent?.()
    this.#notify()
  }

  #notify() {
    this.wake?.()
    this.wake = null
  }

  async #synthesize(text) {
    try {
      const res = await apiFetch('/voice/synthesize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
        signal: this.abort.signal,
      })
      if (!res.ok) return null
      return URL.createObjectURL(await res.blob())
    } catch {
      return null
    }
  }

  async #run() {
    let next = 0
    while (!this.stopped) {
      if (next < this.items.length) {
        const url = await this.items[next++]
        if (!url) continue
        if (this.stopped) { URL.revokeObjectURL(url); break }
        this.onStart?.()
        this.onStart = null
        await this.#play(url)
      } else if (this.closed) {
        break
      } else {
        await new Promise(resolve => { this.wake = resolve })
      }
    }
    // Liberar los audios que se sintetizaron pero no llegaron a sonar
    for (const p of this.items.slice(next)) p.then(url => url && URL.revokeObjectURL(url))
  }

  #play(url) {
    return new Promise(resolve => {
      const audio = new Audio(url)
      this.audio = audio
      const end = () => {
        this.endCurrent = null
        URL.revokeObjectURL(url)
        resolve()
      }
      this.endCurrent = end
      audio.onended = end
      audio.onerror = end
      audio.play().catch(end)
    })
  }
}
