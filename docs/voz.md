# Sistema de Interacción por Voz

Documentación del subsistema de voz de "Habla con tu dinero": cómo funciona la detección de voz (VAD), el reconocimiento de voz (STT), la síntesis de voz (TTS), los endpoints del backend, la UI del frontend y cómo se integra todo con el agente financiero existente.

---

## Índice

1. [Visión general](#1-visión-general)
2. [Arquitectura y flujo completo](#2-arquitectura-y-flujo-completo)
3. [Speech-to-Text: faster-whisper](#3-speech-to-text-faster-whisper)
4. [Text-to-Speech: Piper TTS](#4-text-to-speech-piper-tts)
5. [Endpoints del backend](#5-endpoints-del-backend)
6. [Infraestructura Docker](#6-infraestructura-docker)
7. [Frontend: VoiceModal en modo conversación](#7-frontend-voicemodal-en-modo-conversación)
8. [Integración con el agente](#8-integración-con-el-agente)
9. [Persistencia de modelos](#9-persistencia-de-modelos)
10. [Rendimiento y limitaciones](#10-rendimiento-y-limitaciones)

---

## 1. Visión general

El subsistema de voz permite al usuario hablar directamente con el asistente financiero. Toda la IA corre en local, sin depender de APIs externas de voz:

| Componente | Dónde corre | Tecnología | Modelo | Tamaño |
|-----------|-------------|-----------|--------|--------|
| VAD (¿está hablando?) | Navegador | `@ricky0123/vad-web` + onnxruntime-web | Silero VAD v5 | ~2 MB |
| STT (voz → texto) | Backend | faster-whisper | `base` (multilingüe) | ~150 MB |
| TTS (texto → voz) | Backend | Piper TTS | `es_ES-davefx-medium` | ~65 MB |

La interacción es una **conversación**, no "pulsa para hablar":

- El VAD detecta solo cuándo empiezas y terminas de hablar.
- El asistente empieza a contestar en cuanto tiene la primera frase, sin esperar a la respuesta entera.
- Al terminar de hablar, el micrófono se vuelve a abrir solo.

Whisper y Piper se descargan la primera vez y quedan cacheados en un volumen Docker persistente (`ml_models`). Además se **precargan en memoria al arrancar el backend**, así que la primera frase no espera a que se carguen. El modelo del VAD se sirve desde el propio frontend (`/vad/`), sin CDN: todo el modo voz funciona sin internet, salvo el LLM si es un proveedor en la nube.

---

## 2. Arquitectura y flujo completo

```
┌──────────────────────────────────────────────────────────────────────┐
│                     FRONTEND (React, VoiceModal)                     │
│                                                                      │
│  Micrófono → MicVAD (Silero VAD en un AudioWorklet)                  │
│     │  onSpeechStart  → orbe rojo, reacciona al volumen              │
│     │  onSpeechEnd    → 700 ms de silencio = fin del turno           │
│     ▼                                                                │
│  Float32Array 16 kHz → WAV                                           │
└─────┬────────────────────────────────────────────────────────────────┘
      │ 1. POST /voice/transcribe  (audio/wav)
      ▼
┌──────────────────────────────────────────────────────────────────────┐
│  BACKEND  whisper_service → WhisperModel("base") → texto             │
└─────┬────────────────────────────────────────────────────────────────┘
      │ 2. {"text": "¿Cuánto vale mi cartera?"}
      │ 3. POST /chat/stream  (voice_mode: true)
      ▼
┌──────────────────────────────────────────────────────────────────────┐
│  AGENTE (grafo de LangGraph)                                         │
│  agent: tool loop  →  respond: streaming SSE de tokens               │
└─────┬────────────────────────────────────────────────────────────────┘
      │ 4. tokens llegando...
      ▼
┌──────────────────────────────────────────────────────────────────────┐
│  FRONTEND  SentenceSplitter: corta en frases según llegan            │
│            SpeechQueue: cada frase → POST /voice/synthesize          │
│                         (en paralelo) y se reproduce en orden        │
└─────┬────────────────────────────────────────────────────────────────┘
      │ 5. Termina la última frase
      ▼
   El micrófono se vuelve a abrir solo → siguiente turno
   (los mensajes aparecen también en el chat escrito)
```

### Timeline de un turno

```
t=0ms     El usuario empieza a hablar → VAD: onSpeechStart → orbe rojo
t=2000ms  Deja de hablar
t=2700ms  700 ms de silencio → VAD: onSpeechEnd → POST /voice/transcribe (WAV)
t=4500ms  Whisper devuelve {"text": "¿Cuánto vale mi cartera?"}
t=4510ms  POST /chat/stream → nodo agent (tool loop)
t=7500ms  Empiezan a llegar tokens (nodo respond)
t=8200ms  Primera frase completa → POST /voice/synthesize
t=8800ms  Empieza a sonar la primera frase, mientras siguen llegando tokens
          y se sintetizan las siguientes
t=15000ms Termina la última frase → micro abierto ("Te escucho")
```

Antes, el audio no empezaba hasta tener la respuesta **entera** sintetizada. Ahora empieza en cuanto está la primera frase, y además el usuario no tiene que pulsar para terminar su turno.

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
file: <audio blob>   # audio/wav (modo conversación, VAD), audio/webm o audio/ogg
```

**Response:** `application/json`
```json
{
  "text": "¿Cuánto vale mi cartera de inversiones?"
}
```

**Errores:**
- `400 Bad Request` si no se detecta voz en el audio (transcripción vacía)
- `500 Internal Server Error` si no se puede decodificar el audio (ver la nota sobre `av` en §6)

**Implementación:** `backend/app/api/routes/voice.py`
```python
@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    data = await file.read()
    content_type = file.content_type or ""
    # El modo conversación (VAD en el navegador) envía WAV; MediaRecorder, webm/ogg
    if "wav" in content_type:
        suffix = ".wav"
    elif "ogg" in content_type:
        suffix = ".ogg"
    else:
        suffix = ".webm"
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
- En modo conversación se llama **una vez por frase**, no una vez por respuesta
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

**Versión de `av` fijada:** `requirements.txt` fija `av>=12,<16`. `faster-whisper` 1.2 llama a `av.open(..., metadata_errors="ignore")`, y `av` 19 ya no acepta ese parámetro: cualquier `/voice/transcribe` devolvía 500. Está probado con `av` 15.1.

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

**Frontend: dependencias nuevas del VAD.** El contenedor del frontend guarda `node_modules` en un volumen anónimo (`/app/node_modules`), y `docker compose up --build` **reutiliza** ese volumen viejo. Tras un `git pull` que añada paquetes (como `@ricky0123/vad-web`), hay que renovarlo:

```bash
docker compose up -d --build -V frontend   # -V = --renew-anon-volumes
```

Si no, Vite falla al importar `@ricky0123/vad-web`.

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

## 7. Frontend: VoiceModal en modo conversación

### Ubicación y activación

El modal se abre desde el botón flotante del dashboard o desde el botón de micrófono del chat. Los dos llaman a `openVoice()` en `App.jsx`. Al abrirse, carga el VAD y empieza a escuchar directamente, sin pulsar nada más.

### Máquina de estados

```
           (VAD: empieza a hablar)          (VAD: 700 ms de silencio)
listening ─────────────────────────► hearing ────────────────────────► processing
    ▲   │                                                                   │
    │   └─(20 s sin hablar o toque)─► idle ─(toque)─► listening             │
    │                                                                       ▼
    └──────────────(termina la última frase)───────────────────────── speaking
                                                                            │
                     (el agente propone un Bizum/inversión) ─────────► confirm
```

| Estado | Orbe | Micrófono | Toque en el orbe | Texto |
|--------|------|-----------|------------------|-------|
| `loading` | Gris, gira | — | — | "Preparando micrófono..." |
| `listening` | Verde, reacciona al volumen | Abierto (VAD) | Pausa la conversación | "Te escucho" |
| `hearing` | Rojo, reacciona al volumen | Abierto (VAD) | Pausa la conversación | "Escuchando..." |
| `processing` | Gris, gira | En pausa | — | "Pensando..." |
| `speaking` | Verde, pulso rápido | En pausa (o abierto si "interrumpir hablando") | Corta la respuesta y escucha | "Respondiendo..." |
| `confirm` | Gris | En pausa | — | "Confirma la operación en pantalla" |
| `idle` | Verde, pulso lento | En pausa | Reanuda | "Conversación en pausa" |

Bajo el orbe se muestra lo último que ha entendido Whisper («...»), para que se vea qué ha transcrito.

### Detección de voz (VAD): `@ricky0123/vad-web`

`MicVAD` ejecuta el modelo **Silero VAD v5** en el navegador (onnxruntime-web, wasm) sobre el audio del micrófono, en tramas de 32 ms. Cada trama recibe una probabilidad de voz, y la librería emite eventos:

```javascript
const vad = await MicVAD.new({
  model: 'v5',
  baseAssetPath: '/vad/',       // modelo .onnx y worklet, servidos por Vite
  onnxWASMBasePath: '/vad/',    // runtime wasm de onnxruntime
  startOnLoad: false,
  positiveSpeechThreshold: 0.5,
  negativeSpeechThreshold: 0.35,
  redemptionMs: 700,      // silencio que marca el final del turno
  minSpeechMs: 300,       // más corto que esto es ruido (tos, golpe) → onVADMisfire
  preSpeechPadMs: 300,    // audio previo incluido para no cortar la primera sílaba
  onSpeechStart: ...,     // listening → hearing
  onSpeechEnd: audio => ...,  // Float32Array 16 kHz con la frase completa
  onVADMisfire: ...,      // falsa alarma → vuelve a listening
  onFrameProcessed: (probs, frame) => ...,  // RMS de la trama → escala del orbe
})
```

- **`redemptionMs: 700`** es el ajuste principal. Con menos, corta al usuario cuando hace una pausa para pensar; con más, la respuesta se nota lenta.
- El micrófono se pide con `echoCancellation`, `noiseSuppression` y `autoGainControl`, que son los valores por defecto de la librería.
- `vad.pause()` cierra el micrófono (se apaga el indicador del navegador) y `vad.start()` lo vuelve a abrir. El primer `start()` es el que pide permiso; si se deniega, se muestra el error y el modal queda en `idle`.
- **StrictMode:** en desarrollo, React monta, desmonta y vuelve a montar el componente. Por eso el efecto reinicia `closedRef`, y `destroy()` ignora el error de un VAD que no llegó a arrancar.

**Assets servidos en local** (`vite.config.js`, con `vite-plugin-static-copy`): `silero_vad_v5.onnx`, `vad.worklet.bundle.min.js` y `ort-wasm-simd-threaded*.{wasm,mjs}` se publican en `/vad/`. Así no hay dependencia de un CDN durante la demo.

> **No excluir `onnxruntime-web` de `optimizeDeps`.** `vad-web` es CommonJS y hace `require("onnxruntime-web/wasm")`. Si Vite no pre-empaqueta esa dependencia, el navegador falla con *"Dynamic require of onnxruntime-web/wasm is not supported"*.

### Un turno: `runTurn()` y `speakResponse()`

```javascript
// onSpeechEnd(audio) → pausa el micro → runTurn(audio)
const userText = await transcribeSpeech(audio)      // encodeWAV + POST /voice/transcribe
const res = await apiStream('/chat/stream', { message: userText, history, voice_mode: true },
                            { signal: controller.signal })
await speakResponse(res, userText, turn)
```

`speakResponse()` lee el SSE y va hablando según llega el texto:

```javascript
const splitter = new SentenceSplitter()
const queue = new SpeechQueue({ onStart: () => setPhase('speaking') })

await readSSE(res, ev => {
  if (ev.type === 'token') splitter.push(ev.text).forEach(s => queue.push(s))
  ...
})
queue.push(splitter.flush())   // el resto que no acabó en punto
queue.close()
await queue.done               // termina de sonar la última frase
resumeListening()              // micro abierto otra vez
```

Las dos clases están en `frontend/src/services/voice.js`:

- **`SentenceSplitter`** corta en finales de frase (`. ! ? … : ;` seguidos de espacio, o salto de línea). Junta los trozos de menos de 40 caracteres con el siguiente, porque cada petición a Piper tiene un coste fijo y los cortes muy seguidos suenan entrecortados. No corta en `1.250` porque tras ese punto no hay espacio.
- **`SpeechQueue`** lanza `POST /voice/synthesize` de cada frase **en cuanto llega**, mientras suena la anterior, y las reproduce en orden. `stop()` corta en seco: para el audio, aborta las síntesis pendientes y libera los `blob:` URLs.

### Interrupciones

- **Tocar el orbe mientras habla** corta la respuesta y vuelve a escuchar. Funciona siempre.
- **Interrumpir hablando** (casilla al pie del modal, se guarda en `localStorage`): el VAD sigue escuchando mientras suena la respuesta, y si detecta voz, la corta y empieza un turno nuevo. Viene **desactivado** porque, con altavoces, el micrófono puede captar la propia voz del asistente aunque haya cancelación de eco. Con auriculares funciona bien.

Cada turno tiene un número (`turnRef`). Al interrumpir se incrementa y se abortan el stream y la cola de audio (`AbortController`). Así, cualquier `await` del turno anterior que termine después ve que ya no es el turno actual y no toca el estado.

### Tarjeta de confirmación (Bizum, inversión)

Si el `done` del stream trae `pending_action`, no se habla nada. Se pausa el micrófono, se muestra la tarjeta (`BizumConfirmModal` / `InvestmentConfirmModal`) y la conversación espera (`confirm`). Los botones llaman a `POST /chat/actions/{action_id}`, y la respuesta del agente (ejecutado o cancelado) se reproduce con el mismo `speakResponse()`. Después se reanuda la escucha.

**La aprobación nunca es por voz.** Decir "sí, confirma" solo genera una propuesta nueva con su propia tarjeta. Así, una frase mal transcrita o una voz de fondo no pueden aprobar un pago. Ver [acciones-langgraph.md](acciones-langgraph.md).

### Integración con el historial del chat

El modal recibe `history` al abrirse y lleva su propio historial (`historyRef`), al que añade cada turno. Así el agente tiene el contexto de toda la conversación por voz, no solo el del momento en que se abrió. Cada turno se notifica también a `onComplete({ userText, assistantText, chartType, chartData, chartTitle })`, que lo añade al chat escrito. Si un turno se interrumpe, se guarda lo que el asistente llegó a decir.

---

## 8. Integración con el agente

El subsistema de voz **no duplica la lógica del agente**. El VoiceModal reutiliza el endpoint `/chat/stream` exactamente igual que el ChatBox de texto. El agente no sabe si la pregunta llegó por voz o por teclado — para él es idéntico.

```
Texto    → POST /chat/stream  ←─── VoiceModal también usa esto
Voz      → POST /voice/transcribe → texto → POST /chat/stream
```

La diferencia es qué se hace con los tokens: el ChatBox los pinta según llegan, y el VoiceModal los trocea en frases y las va sintetizando según llegan. Con `voice_mode: true`, el nodo `respond` usa un prompt de respuesta hablada: sin markdown, frases cortas y cifras en palabras.

---

## 9. Persistencia de modelos

Los modelos ML se descargan la primera vez que se usan y se **precargan en memoria al arrancar el backend** (`_warm_voice_models` en `main.py`, en un thread para no retrasar el arranque). Sin la precarga, la primera frase tardaba unos 10 s más en transcribirse.

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
| Detección de fin de turno (VAD) | 700 ms | `redemptionMs` |
| Transcripción de una frase (Whisper base) | 1.5-3 s | Precargado al arrancar |
| Respuesta del agente hasta la primera frase | 3-6 s | Depende del modelo LLM y del nº de tools |
| Síntesis de una frase (Piper) | 0.3-0.8 s | Se solapa con la reproducción de la anterior |
| **Fin del habla → primer audio** | ~6-10 s | Antes ~8-15 s, más el tiempo de pulsar para parar |

### Limitaciones conocidas

1. **Whisper `base` falla palabras con voces poco claras o con ruido.** En las pruebas con voz sintética de Piper entendió "bicuenta" por "mi cuenta" y "a Marta" como "amarta". Si falla un nombre o un importe, el agente pregunta o la tarjeta de confirmación lo muestra mal y el usuario cancela; nunca se ejecuta nada sin pulsar Confirmar. Para más precisión se puede pasar a `small` (ver abajo), a costa de más latencia.

2. **Interrumpir hablando con altavoces.** La cancelación de eco del navegador ayuda, pero no es perfecta: el micrófono puede captar la voz del asistente e interrumpirse a sí mismo. Por eso la opción viene desactivada.

3. **Pausas largas al hablar.** Con `redemptionMs: 700`, una pausa larga a mitad de frase se interpreta como fin del turno. Se puede subir a ~1000 ms.

4. **Piper TTS no tiene control de velocidad/tono en tiempo de ejecución**: la voz es fija según el modelo. Para cambiar la voz, cambiar `VOICE_NAME` y la `_HF_BASE` en `tts_service.py`.

5. **Silencio prolongado.** Tras 20 s sin hablar, la conversación se pausa y se cierra el micrófono, para no dejarlo abierto indefinidamente.

### Cómo se ha probado

Con Chromium en modo headless (puppeteer-core) y un **micrófono simulado** (`--use-fake-device-for-media-stream --use-file-for-fake-audio-capture=frase.wav`). La frase se generó con el propio Piper, con silencio antes y después. Se comprobó:

- El VAD detecta inicio y fin de cada frase y envía el WAV.
- Whisper transcribe y el agente responde.
- La respuesta se sintetiza en varias frases que empiezan a sonar mientras llega el resto.
- La escucha se reanuda sola y encadena turnos.
- Con "interrumpir hablando", la nueva frase corta la respuesta.
- Un Bizum por voz muestra la tarjeta y, al confirmar, se ejecuta una vez y se lee el resultado.

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
| `backend/app/main.py` | Registro del router de voz + precarga de modelos al arrancar |
| `backend/Dockerfile` | ffmpeg + espeak-ng + libsndfile1 |
| `backend/requirements.txt` | `faster-whisper>=1.0.3`, `av>=12,<16`, `piper-tts>=1.2.0` |
| `docker-compose.yml` | Volumen `ml_models`, var `MODEL_CACHE_DIR` |
| `frontend/src/components/VoiceModal.jsx` | Modo conversación: VAD, máquina de estados, turnos, interrupciones, tarjeta |
| `frontend/src/services/voice.js` | `transcribeSpeech`, `SentenceSplitter`, `SpeechQueue` |
| `frontend/src/App.jsx` / `ChatBox.jsx` | Botones que abren el modal (`openVoice`) |
| `frontend/src/index.css` | Keyframes `orb-idle` y `orb-spin` |
| `frontend/vite.config.js` | Proxy `/voice` → backend + assets del VAD en `/vad/` |
| `frontend/package.json` | `@ricky0123/vad-web`, `vite-plugin-static-copy` |
