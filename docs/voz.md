# Sistema de Interacción por Voz

Documentación del subsistema de voz de "Habla con tu dinero": cómo funciona el reconocimiento de voz (STT), la síntesis de voz (TTS), los endpoints del backend, la UI del frontend y cómo se integra todo con el agente financiero existente.

---

## Índice

1. [Visión general](#1-visión-general)
2. [Arquitectura y flujo completo](#2-arquitectura-y-flujo-completo)
3. [Speech-to-Text: faster-whisper](#3-speech-to-text-faster-whisper)
4. [Text-to-Speech: Piper TTS](#4-text-to-speech-piper-tts)
5. [Endpoints del backend](#5-endpoints-del-backend)
6. [Infraestructura Docker](#6-infraestructura-docker)
7. [Frontend: VoiceModal](#7-frontend-voicemodaln)
8. [Integración con el agente](#8-integración-con-el-agente)
9. [Persistencia de modelos](#9-persistencia-de-modelos)
10. [Rendimiento y limitaciones](#10-rendimiento-y-limitaciones)

---

## 1. Visión general

El subsistema de voz permite al usuario hablar directamente con el asistente financiero. Toda la IA corre en local, sin depender de APIs externas de voz:

| Componente | Tecnología | Modelo | Tamaño |
|-----------|-----------|--------|--------|
| STT (voz → texto) | faster-whisper | `base` (multilingüe) | ~150 MB |
| TTS (texto → voz) | Piper TTS | `es_ES-davefx-medium` | ~65 MB |

Los modelos se descargan automáticamente la primera vez que se llama al endpoint y quedan cacheados en un volumen Docker persistente (`ml_models`). Las llamadas siguientes son instantáneas.

---

## 2. Arquitectura y flujo completo

```
┌─────────────────────────────────────────────────────────────────────┐
│                         FRONTEND (React)                            │
│                                                                     │
│  [🎤 botón]  →  VoiceModal abre                                     │
│                     │                                               │
│              Estado: idle → listening → processing → speaking       │
│                     │                                               │
│           MediaRecorder (audio/webm)                                │
│           Web Audio API (amplitud → escala del orbe)                │
└─────────────────────┬───────────────────────────────────────────────┘
                      │ 1. POST /voice/transcribe  (audio blob)
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        BACKEND (FastAPI)                            │
│                                                                     │
│  /voice/transcribe                                                  │
│    └─ whisper_service.py                                            │
│         └─ WhisperModel("base") → texto en español                  │
│                                                                     │
│  {"text": "¿Cuánto vale mi cartera?"}                               │
└─────────────────────┬───────────────────────────────────────────────┘
                      │ 2. {"text": "..."} devuelto al frontend
                      │
                      │ 3. Frontend llama a POST /chat/stream
                      │    (reutiliza el agente existente)
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    AGENTE FINANCIERO (LiteLLM)                      │
│                                                                     │
│  Phase 1: tool loop (get_portfolio, get_market_overview, ...)       │
│  Phase 2: streaming SSE → tokens de texto                           │
│                                                                     │
│  Frontend acumula todos los tokens → texto completo                 │
└─────────────────────┬───────────────────────────────────────────────┘
                      │ 4. POST /voice/synthesize  (texto de respuesta)
                      ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        BACKEND (FastAPI)                            │
│                                                                     │
│  /voice/synthesize                                                  │
│    └─ tts_service.py                                                │
│         └─ PiperVoice("es_ES-davefx-medium")                       │
│              └─ generador AudioChunk → WAV 16-bit 22050 Hz          │
│                                                                     │
│  Response: audio/wav (binario)                                      │
└─────────────────────┬───────────────────────────────────────────────┘
                      │ 5. Blob URL → new Audio().play()
                      ▼
                 Usuario escucha la respuesta
                 Mensajes aparecen también en el chat escrito
```

### Timeline de una consulta de voz

```
t=0ms    Usuario pulsa el orbe → MediaRecorder.start()
t=...    Web Audio API lee amplitud → orbe escala en tiempo real
t=3000ms Usuario pulsa para parar → MediaRecorder.stop()
t=3050ms Blob audio/webm listo → POST /voice/transcribe
t=5000ms Whisper devuelve {"text": "¿Cuánto vale mi cartera?"}
t=5010ms POST /chat/stream enviado → agente empieza tool loop
t=5500ms Agente llama get_portfolio() + get_market_overview()
t=8000ms Fase 2: streaming de tokens comienza → orbe gira (processing)
t=9500ms Todos los tokens recibidos → POST /voice/synthesize
t=10000ms Piper genera ~1.5s de audio WAV
t=10000ms Audio.play() → orbe pulsa (speaking)
t=11500ms Audio termina → orbe vuelve a idle
t=11500ms Mensajes aparecen en el chat
```

---

## 3. Speech-to-Text: faster-whisper

### ¿Qué es Whisper?

Whisper es el modelo de reconocimiento de voz de OpenAI, publicado como código abierto. `faster-whisper` es una reimplementación en C++ (usando CTranslate2) que es 4× más rápida que la librería original de Python y usa menos memoria gracias a cuantización INT8.

### Modelos disponibles

| Modelo | Tamaño | VRAM | Velocidad en CPU | Precisión |
|--------|--------|------|-----------------|-----------|
| `tiny` | 75 MB  | ~1GB | ~32× tiempo real | Baja |
| `base` | 145 MB | ~1GB | ~16× tiempo real | **Buena** ← usamos este |
| `small` | 461 MB | ~2GB | ~6× tiempo real | Muy buena |
| `medium` | 1.5 GB | ~5GB | ~2× tiempo real | Excelente |

El modelo `base` es el equilibrio óptimo para el demo: transcribe 5 segundos de audio en ~2-4 segundos en CPU, con muy buena precisión en español.

### Código: `backend/app/services/whisper_service.py`

```python
from faster_whisper import WhisperModel

_model: WhisperModel | None = None

def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        cache = os.path.join(os.getenv("MODEL_CACHE_DIR", "/tmp/models"), "whisper")
        _model = WhisperModel("base", device="cpu", compute_type="int8",
                              download_root=cache)
    return _model

async def transcribe(audio_bytes: bytes, suffix: str = ".webm") -> str:
    def _sync() -> str:
        model = _get_model()
        # Escribe el audio en un fichero temporal (faster-whisper necesita un path)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        try:
            # language="es" fuerza español y evita el overhead de detección
            # beam_size=5 es el default; más beam_size = más preciso pero más lento
            segments, _ = model.transcribe(tmp_path, language="es", beam_size=5)
            return " ".join(s.text.strip() for s in segments).strip()
        finally:
            os.unlink(tmp_path)  # limpiar siempre

    return await asyncio.to_thread(_sync)  # no bloqueamos el event loop de FastAPI
```

**Decisiones de diseño:**
- **Singleton `_model`**: cargar un modelo Whisper tarda ~3s la primera vez; con singleton solo ocurre una vez durante la vida del proceso.
- **`asyncio.to_thread`**: `WhisperModel.transcribe` es síncrono y bloqueante. Ejecutarlo en un thread pool evita bloquear el event loop de FastAPI mientras otros requests pueden seguir procesándose.
- **Fichero temporal**: faster-whisper acepta paths, no bytes en memoria. El fichero se borra en el bloque `finally` aunque haya error.
- **`language="es"`**: sin esto, Whisper dedica ~200ms a detectar el idioma automáticamente. Como sabemos que el usuario habla español, lo fijamos.
- **Formato de entrada**: el navegador graba en `audio/webm` (Chrome/Edge) o `audio/ogg` (Firefox). ffmpeg (instalado en el Dockerfile) se encarga de decodificar cualquier formato antes de que Whisper lo procese.

### Por qué NOT usar la API de OpenAI Whisper

La API de Whisper de OpenAI (`api.openai.com/v1/audio/transcriptions`) es más rápida pero:
- Requiere API key y tiene coste por minuto de audio
- Envía el audio a servidores externos (privacidad)
- El reto pide modelos locales

---

## 4. Text-to-Speech: Piper TTS

### ¿Qué es Piper?

Piper es un sistema TTS neural desarrollado por Rhasspy (proyecto de asistentes de voz locales, usado en Home Assistant). Características:
- Voces neurales de alta calidad, mucho mejor que eSpeak
- Optimizado para CPU: genera audio en tiempo real o más rápido
- Modelos pequeños (~20-80 MB por voz)
- Soporte nativo de español con múltiples voces

### La voz elegida: `es_ES-davefx-medium`

Disponible en el repositorio oficial `rhasspy/piper-voices` en Hugging Face. Alternativas en español:

| Voz | Calidad | Tamaño | Nota |
|-----|---------|--------|------|
| `es_ES-carlfm-x_low` | Baja | ~20 MB | Más rápida, menos natural |
| `es_ES-davefx-medium` | **Media** | ~65 MB | **← usamos esta** |
| `es_ES-sharvard-medium` | Media | ~65 MB | Alternativa |

### Cómo funciona Piper internamente

```
Texto → eSpeak-ng (fonemización) → Modelo ONNX (VITS neural) → Audio float32 → WAV 16-bit
```

1. **eSpeak-ng** convierte el texto en fonemas IPA: `"hola"` → `/ola/`
2. El **modelo VITS** (ONNX Runtime) convierte los fonemas en audio como array float32 normalizado [-1, 1]
3. El código convierte a **PCM 16-bit**: `(float32 * 32767).astype(np.int16)`
4. Se escribe en un fichero **WAV** (44 bytes de header + frames PCM)

Por eso es obligatorio instalar `espeak-ng` en el Dockerfile — sin él, la fonemización falla silenciosamente y el WAV sale vacío (solo los 44 bytes del header).

### Código: `backend/app/services/tts_service.py`

```python
from piper.voice import PiperVoice
import numpy as np, wave, io

VOICE_NAME = "es_ES-davefx-medium"
_voice: PiperVoice | None = None

def _get_voice() -> PiperVoice:
    global _voice
    if _voice is None:
        cache = os.path.join(os.getenv("MODEL_CACHE_DIR", "/tmp/models"), "piper")
        onnx_path, cfg_path = _ensure_model(cache)  # descarga si no existe
        _voice = PiperVoice.load(onnx_path, config_path=cfg_path, use_cuda=False)
    return _voice

async def synthesize(text: str) -> bytes:
    def _sync() -> bytes:
        voice = _get_voice()
        buf = io.BytesIO()
        wav_file = wave.open(buf, "wb")
        wav_file.setnchannels(1)                       # mono
        wav_file.setframerate(voice.config.sample_rate) # 22050 Hz
        wav_file.setsampwidth(2)                       # 16-bit PCM

        # voice.synthesize() es un generador: un AudioChunk por frase
        for chunk in voice.synthesize(text):
            audio_int16 = (chunk.audio_float_array * 32767).astype(np.int16)
            wav_file.writeframes(audio_int16.tobytes())

        wav_file.close()
        return buf.getvalue()

    return await asyncio.to_thread(_sync)
```

**Decisiones de diseño:**
- **`voice.synthesize()` es un generador**: cada llamada produce un `AudioChunk` por frase. Iterarlo permite ir escribiendo el WAV de forma streaming (aunque aquí lo acumulamos todo en memoria para simplificar).
- **Conversión float32 → int16**: Piper produce audio como float32 normalizado. El formato WAV estándar usa PCM 16-bit, que es `int16` (rango -32768 a 32767). La conversión es `* 32767`.
- **22050 Hz**: es la frecuencia de muestreo del modelo `davefx-medium`. No es CD quality (44100 Hz) pero es más que suficiente para voz.
- **`use_cuda=False`**: sin GPU dedicada, CUDA ralentizaría más que ayudaría en modelos pequeños. CPU es la opción correcta aquí.
- **Descarga automática**: `_ensure_model` comprueba si los ficheros `.onnx` y `.onnx.json` existen en el cache; solo los descarga si no están. La URL apunta al repositorio oficial de HuggingFace.

---

## 5. Endpoints del backend

### `POST /voice/transcribe`

Transcribe un fichero de audio a texto en español.

**Request:** `multipart/form-data`
```
file: <audio blob>   # audio/webm, audio/ogg o audio/wav
```

**Response:** `application/json`
```json
{
  "text": "¿Cuánto vale mi cartera de inversiones?"
}
```

**Errores:**
- `400 Bad Request` si no se detecta voz en el audio (transcripción vacía)
- `500 Internal Server Error` si ffmpeg no puede decodificar el formato

**Implementación:** `backend/app/api/routes/voice.py`
```python
@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    data = await file.read()
    suffix = ".ogg" if "ogg" in (file.content_type or "") else ".webm"
    text = await transcribe(data, suffix)
    if not text:
        raise HTTPException(status_code=400, detail="No se detectó audio")
    return {"text": text}
```

---

### `POST /voice/synthesize`

Convierte texto en audio WAV con la voz española de Piper.

**Request:** `application/json`
```json
{
  "text": "Tu cartera vale 12.450 euros, con una ganancia del 8,3%."
}
```

**Response:** `audio/wav` (binario)
- Formato: PCM 16-bit, mono, 22050 Hz
- Tamaño típico: ~100-300 KB (1-3 segundos de audio)
- Sin compresión: el browser puede reproducirlo directamente con `new Audio(blobURL)`

---

## 6. Infraestructura Docker

### `backend/Dockerfile`

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Dependencias del sistema para audio y voz
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg        \  # decodifica audio/webm y audio/ogg de MediaRecorder
    libsndfile1   \  # lectura de ficheros de audio (requerido por soundfile)
    espeak-ng        # fonemización de texto para Piper TTS
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# faster-whisper y piper-tts están en requirements.txt

COPY . .
RUN mkdir -p /app/data
EXPOSE 8000
```

**Por qué cada paquete:**
- **ffmpeg**: el navegador graba audio en `webm` (códec Opus). faster-whisper necesita PCM raw; ffmpeg hace la conversión transparentemente cuando se le pasa el fichero `.webm`.
- **libsndfile1**: librería de C para I/O de audio, usada por varias dependencias de Python como `soundfile`.
- **espeak-ng**: Piper usa eSpeak-ng como backend de fonemización. Sin él, `piper.voice.PiperVoice.synthesize()` completa sin error pero no produce audio (solo el header WAV de 44 bytes).

### `docker-compose.yml`

```yaml
services:
  backend:
    volumes:
      - ./backend:/app
      - sqlite_data:/app/data
      - ml_models:/app/models    # ← nuevo: cachea los modelos ML
    environment:
      - MODEL_CACHE_DIR=/app/models  # ← nuevo: indica dónde guardar modelos

volumes:
  sqlite_data:
  ml_models:   # ← nuevo volumen Docker nombrado
```

El volumen `ml_models` es un volumen Docker nombrado (no un bind mount). Docker lo gestiona en `/var/lib/docker/volumes/reto-unicaja_ml_models/`. Los modelos se organizan así dentro del volumen:

```
/app/models/
├── whisper/
│   ├── models--Systran--faster-whisper-base/   # estructura HuggingFace Hub
│   │   └── snapshots/...
│   └── ...
└── piper/
    ├── es_ES-davefx-medium.onnx                # ~65 MB
    └── es_ES-davefx-medium.onnx.json           # config de la voz
```

---

## 7. Frontend: VoiceModal

### Ubicación y activación

El botón de micrófono aparece en el footer del chat, a la izquierda del botón Enviar:

```jsx
// ChatBox.jsx
<button onClick={() => setVoiceOpen(true)} disabled={loading} title="Hablar con el asistente">
  <svg ...>{/* icono micrófono */}</svg>
</button>

{voiceOpen && (
  <VoiceModal
    history={history}          // historial de conversación para contexto
    onClose={() => setVoiceOpen(false)}
    onComplete={handleVoiceComplete}  // añade mensajes al chat escrito
  />
)}
```

### Máquina de estados del orbe

El `VoiceModal` implementa una máquina de estados de 4 fases, visible en la animación del orbe:

```
         tap orbe              tap orbe
  idle ──────────→ listening ──────────→ processing ──→ speaking ──→ idle
   ↑                                                                   │
   └───────────────────────── audio.onended ──────────────────────────┘
```

| Estado | Color orbe | Animación | Interacción | Texto |
|--------|-----------|-----------|-------------|-------|
| `idle` | Verde `#00A651` | Pulso lento (2.4s) | Click → listening | "Toca para hablar" |
| `listening` | Rojo `#E53E3E` | Escala JS según amplitud | Click → processing | "Escuchando..." |
| `processing` | Gris `#444444` | Rotación continua (1.2s) | — | "Procesando..." |
| `speaking` | Verde `#00A651` | Pulso rápido (0.9s) | — | "Respondiendo..." |

### Web Audio API: visualización de amplitud

Durante `listening`, el orbe reacciona a la voz del usuario en tiempo real. Esto se consigue con la Web Audio API:

```javascript
// 1. Obtener acceso al micrófono
const stream = await navigator.mediaDevices.getUserMedia({ audio: true })

// 2. Crear el grafo de audio: fuente → analizador
const ctx = new AudioContext()
const source = ctx.createMediaStreamSource(stream)
const analyser = ctx.createAnalyser()
analyser.fftSize = 256  // 128 bins de frecuencia
source.connect(analyser)

// 3. Bucle de animación: leer amplitud cada frame
const data = new Uint8Array(analyser.frequencyBinCount)  // 128 valores 0-255
function tick() {
  analyser.getByteFrequencyData(data)              // energía por frecuencia
  const avg = data.reduce((s, v) => s + v, 0) / data.length  // promedio
  const scale = 1 + (avg / 255) * 0.45            // rango: 1.0 → 1.45
  setOrbScale(scale)                               // React re-renderiza el orbe
  animFrameRef.current = requestAnimationFrame(tick)
}
tick()
```

`fftSize=256` da 128 bins de frecuencia. El promedio de energía da un número entre 0 y 255; mapeamos ese rango a un factor de escala entre 1.0 (silencio) y 1.45 (voz alta). El resultado es que el orbe "crece" cuando el usuario habla.

### MediaRecorder: grabación de audio

```javascript
const mr = new MediaRecorder(stream)
audioChunksRef.current = []
mr.ondataavailable = e => { if (e.data.size > 0) audioChunksRef.current.push(e.data) }
mr.start()

// Al parar:
const blob = await new Promise(resolve => {
  mr.onstop = () => resolve(new Blob(audioChunksRef.current, { type: 'audio/webm' }))
  mr.stop()
})
```

`MediaRecorder` produce fragmentos de audio en el formato nativo del navegador:
- **Chrome/Edge**: `audio/webm` con códec Opus
- **Firefox**: `audio/ogg` con códec Opus

El backend detecta el content type y añade la extensión correcta al fichero temporal para que ffmpeg lo decodifique bien.

### Flujo interno del componente

```javascript
async function processAudio(audioBlob) {
  // 1. Transcribir
  const form = new FormData()
  form.append('file', audioBlob, 'audio.webm')
  const { text: userText } = await fetch('/voice/transcribe', { method: 'POST', body: form }).then(r => r.json())

  // 2. Enviar al agente (stream SSE)
  const chatRes = await fetch('/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message: userText, user_id: 1, history })
  })

  // 3. Acumular todos los tokens
  let assistantText = ''
  const reader = chatRes.body.getReader()
  // ... bucle SSE, acumula tokens de tipo 'token' ...

  // 4. Notificar al padre (añade mensajes al chat escrito)
  onComplete({ userText, assistantText })

  // 5. Sintetizar y reproducir
  setPhase('speaking')
  const audioBytes = await fetch('/voice/synthesize', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: assistantText })
  }).then(r => r.arrayBuffer())

  const audioUrl = URL.createObjectURL(new Blob([audioBytes], { type: 'audio/wav' }))
  const audio = new Audio(audioUrl)
  audio.onended = () => { URL.revokeObjectURL(audioUrl); setPhase('idle') }
  audio.play()
}
```

**Por qué `URL.createObjectURL` y no un `<audio src>`**: el audio WAV viene como `ArrayBuffer` de la respuesta fetch. `createObjectURL` genera una URL temporal `blob://...` que el browser puede reproducir directamente. Se revoca con `revokeObjectURL` cuando termina la reproducción para liberar memoria.

### Integración con el historial del chat

El VoiceModal recibe `history` como prop (el estado de historial de ChatBox) y lo incluye en la llamada a `/chat/stream`. Esto garantiza que el agente tiene contexto de la conversación anterior, tanto de mensajes escritos como de voz.

Cuando la interacción de voz termina, llama a `onComplete({ userText, assistantText })`, que actualiza el estado de ChatBox:

```javascript
function handleVoiceComplete({ userText, assistantText }) {
  setMessages(prev => [...prev,
    { role: 'user', text: userText },
    { role: 'assistant', text: assistantText },
  ])
  setHistory(prev => [...prev,
    { role: 'user', content: userText },
    { role: 'assistant', content: assistantText },
  ])
}
```

Los mensajes de voz aparecen visualmente en el chat igual que los escritos.

---

## 8. Integración con el agente

El subsistema de voz **no duplica la lógica del agente**. El VoiceModal reutiliza el endpoint `/chat/stream` exactamente igual que el ChatBox de texto. El agente no sabe si la pregunta llegó por voz o por teclado — para él es idéntico.

```
Texto    → POST /chat/stream  ←─── VoiceModal también usa esto
Voz      → POST /voice/transcribe → texto → POST /chat/stream
```

La única diferencia es que el VoiceModal acumula la respuesta completa (todos los tokens del SSE) para luego enviarla a `/voice/synthesize`, mientras que el ChatBox de texto muestra los tokens mientras llegan (streaming en tiempo real).

---

## 9. Persistencia de modelos

Los modelos ML se descargan la primera vez que se llama al endpoint correspondiente:

| Evento | Momento | Duración estimada |
|--------|---------|-------------------|
| Primera llamada a `/voice/transcribe` | Descarga Whisper base (~150 MB) | ~30-60s según conexión |
| Primera llamada a `/voice/synthesize` | Descarga Piper model (~65 MB) | ~15-30s según conexión |
| Llamadas posteriores | Los modelos están en memoria (`_model`, `_voice`) | <100ms |

Los modelos se persisten en el volumen Docker `ml_models` (ruta `/app/models` dentro del contenedor). Si el contenedor se reinicia, los modelos siguen en el volumen y no hay que volver a descargarlos. Solo se descargan de nuevo si el volumen se borra (`docker volume rm reto-unicaja_ml_models`).

Para verificar que los modelos están descargados:
```bash
docker exec reto-unicaja-backend-1 ls -lh /app/models/piper/
docker exec reto-unicaja-backend-1 ls -lh /app/models/whisper/
```

---

## 10. Rendimiento y limitaciones

### Latencias típicas (CPU, sin GPU)

| Operación | Tiempo típico | Notas |
|-----------|--------------|-------|
| Transcripción 5s de audio (Whisper base) | 2-4s | Primer uso tarda más (carga modelo) |
| Síntesis de 100 palabras (Piper) | 0.5-1s | Muy rápido en CPU |
| Respuesta del agente | 3-8s | Depende del modelo LLM y nº de tools |
| **Total ciclo voz** | ~8-15s | Desde fin de habla hasta inicio de audio |

### Limitaciones conocidas

1. **No hay detección de silencio automática**: el usuario debe pulsar el orbe para empezar y parar de grabar. No hay VAD (Voice Activity Detection).

2. **Una sola vuelta por sesión de voz**: el modal cierra automáticamente después de reproducir la respuesta y vuelve a `idle`. Para otra pregunta, el usuario pulsa el orbe de nuevo.

3. **Sin modo conversación continua**: la voz no queda escuchando permanentemente. Es "pulsa para hablar", no "hey asistente...".

4. **Whisper base tiene limitaciones con acentos fuertes o ruido**: el modelo `base` es bueno pero no perfecto. Para mayor precisión se puede cambiar a `small` o `medium` en `whisper_service.py` (a costa de mayor latencia).

5. **Piper TTS no tiene control de velocidad/tono en tiempo de ejecución**: la voz es fija según el modelo. Para cambiar la voz, cambiar `VOICE_NAME` y la `_HF_BASE` en `tts_service.py`.

6. **Los pending_action (confirmación de Bizum/inversiones) no funcionan por voz**: si el agente genera un `pending_action`, este aparece en el chat escrito pero el modal de voz no lo gestiona. El usuario debe confirmar por texto.

### Cambiar a otro modelo de voz

Para cambiar la voz española, editar `backend/app/services/tts_service.py`:
```python
# Voz femenina alternativa:
VOICE_NAME = "es_ES-sharvard-medium"
_HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/sharvard/medium"

# Voz masculina muy ligera (x_low quality):
VOICE_NAME = "es_ES-carlfm-x_low"
_HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main/es/es_ES/carlfm/x_low"
```

Borrar el modelo anterior del volumen para que se descargue el nuevo:
```bash
docker exec reto-unicaja-backend-1 rm -f /app/models/piper/*.onnx /app/models/piper/*.json
```

### Cambiar a Whisper más potente

En `backend/app/services/whisper_service.py`:
```python
_model = WhisperModel("small", device="cpu", compute_type="int8", ...)
# o "medium" para máxima precisión (más lento)
```

---

## Archivos clave del subsistema

| Archivo | Rol |
|---------|-----|
| `backend/app/services/whisper_service.py` | Singleton STT con faster-whisper |
| `backend/app/services/tts_service.py` | Singleton TTS con Piper |
| `backend/app/api/routes/voice.py` | Endpoints FastAPI `/voice/*` |
| `backend/app/main.py` | Registro del router de voz |
| `backend/Dockerfile` | ffmpeg + espeak-ng + libsndfile1 |
| `backend/requirements.txt` | `faster-whisper>=1.0.3`, `piper-tts>=1.2.0` |
| `docker-compose.yml` | Volumen `ml_models`, var `MODEL_CACHE_DIR` |
| `frontend/src/components/VoiceModal.jsx` | UI completa del orbe animado |
| `frontend/src/components/ChatBox.jsx` | Botón micrófono + integración VoiceModal |
| `frontend/src/index.css` | Keyframes `orb-idle` y `orb-spin` |
| `frontend/vite.config.js` | Proxy `/voice` → backend |
