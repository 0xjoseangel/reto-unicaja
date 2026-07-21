# Cómo funciona el agente de IA

Documentación técnica del sistema conversacional de "Habla con tu dinero".

---

## Índice

1. [Visión general](#1-visión-general)
2. [La infraestructura](#2-la-infraestructura)
3. [LiteLLM — la capa de abstracción](#3-litellm--la-capa-de-abstracción)
4. [La API de Anthropic en detalle](#4-la-api-de-anthropic-en-detalle)
5. [El agente en dos fases](#5-el-agente-en-dos-fases)
6. [Streaming con SSE](#6-streaming-con-sse)
7. [El ciclo completo de una pregunta](#7-el-ciclo-completo-de-una-pregunta)

---

## 1. Visión general

Cuando el usuario escribe "¿cuánto gasté en restaurantes este mes?", esto es lo que ocurre a alto nivel:

```
Usuario (navegador)
    │  POST /chat/stream  {"message": "¿cuánto gasté..."}
    ▼
FastAPI (backend Python)
    │  litellm.acompletion(model="anthropic/claude-haiku-4-5", ...)
    ▼
API de Anthropic (Claude Haiku)
    │  → decide llamar a get_expenses_by_category(category="restaurantes")
    ▼
Tool Python (SQLite)
    │  → devuelve {"total": 187.50, "period": "current_month"}
    ▼
API de Anthropic (segunda llamada)
    │  → genera respuesta en texto + JSON del gráfico
    ▼
FastAPI (streaming SSE)
    │  data: {"type":"token","text":"Has gastado **187,50 €**..."}
    │  data: {"type":"token","text":" en restaurantes este mes."}
    │  data: {"type":"done","chart_type":"bar",...}
    ▼
Usuario (texto aparece progresivamente en pantalla)
```

El sistema tiene tres piezas clave que conviene entender por separado: **la infraestructura** (cómo se comunican las partes), **LiteLLM** (cómo se habla con los modelos de IA), y **el agente** (la lógica de dos fases que decide qué hacer).

---

## 2. La infraestructura

### Docker Compose

El proyecto corre en tres contenedores Docker que se comunican entre sí a través de una red virtual (`app_network`):

```
┌─────────────────────────────────────────────────┐
│                  app_network                    │
│                                                 │
│  ┌──────────────┐    ┌─────────────────────┐   │
│  │   frontend   │    │      backend        │   │
│  │  React+Vite  │───▶│  FastAPI + Python   │   │
│  │  puerto 3000 │    │    puerto 8000      │   │
│  └──────────────┘    └─────────┬───────────┘   │
│                                │               │
│                       ┌────────▼────────┐      │
│                       │    SQLite DB    │      │
│                       │  /app/data/     │      │
│                       └─────────────────┘      │
└─────────────────────────────────────────────────┘
         │                        │
    puerto 3000              puerto 8000
    (navegador)             (API REST)
```

El frontend hace peticiones al backend por red interna de Docker. El backend lee `.env` para la API key de Anthropic y guarda datos en un volumen SQLite persistente.

### FastAPI

FastAPI es el framework web del backend. Define los endpoints como funciones Python asíncronas:

```python
# backend/app/api/routes/chat.py
@router.post("/stream")
async def chat_stream(request: ChatRequest):
    return StreamingResponse(
        process_chat_stream(request.message, request.user_id, history),
        media_type="text/event-stream",   # SSE
    )
```

`async def` es importante: permite que Python atienda otras peticiones mientras espera respuesta de la API de Anthropic (E/S no bloqueante).

### Pydantic

Pydantic valida automáticamente los datos que entran y salen de la API:

```python
class ChatRequest(BaseModel):
    message: str       # obligatorio
    user_id: int = 1   # opcional, default 1
    history: list[HistoryMessage] = []

# Si llega un JSON sin "message", FastAPI devuelve 422 automáticamente
```

---

## 3. LiteLLM — la capa de abstracción

### El problema que resuelve

Sin LiteLLM, para soportar Claude y Ollama habría que escribir código diferente para cada proveedor. Cada uno tiene su propia librería, su propio formato de mensajes, su propia forma de pasar tools:

```python
# Sin LiteLLM — código diferente para cada proveedor:

# Anthropic SDK
import anthropic
client = anthropic.Anthropic(api_key="...")
response = client.messages.create(
    model="claude-haiku-4-5",
    tools=[{"name": "...", "input_schema": {...}}],  # Anthropic usa input_schema
    ...
)

# OpenAI SDK (también sirve para Ollama)
from openai import OpenAI
client = OpenAI(base_url="http://ollama:11434/v1")
response = client.chat.completions.create(
    model="qwen2.5:7b",
    tools=[{"name": "...", "parameters": {...}}],   # OpenAI usa parameters
    ...
)
```

### La solución: una interfaz unificada

Con LiteLLM hay una sola función para todo. El proveedor se especifica en el nombre del modelo con un prefijo:

```python
import litellm

# La misma llamada funciona para todos los proveedores:
response = litellm.completion(
    model="anthropic/claude-haiku-4-5",    # Claude
  # model="ollama/qwen2.5:7b",             # Ollama local
  # model="groq/llama-3.3-70b-versatile",  # Groq
    messages=[{"role": "user", "content": "Hola"}],
    tools=TOOLS_SCHEMA,  # siempre en formato OpenAI
)
```

LiteLLM traduce internamente el formato de tools: para Anthropic convierte `parameters` → `input_schema`, ajusta los nombres de campos, y maneja las diferencias de respuesta.

### Model strings

El formato es siempre `"proveedor/nombre-del-modelo"`:

| String | Proveedor | Qué necesita |
|--------|-----------|--------------|
| `anthropic/claude-haiku-4-5` | Anthropic API | `ANTHROPIC_API_KEY` en env |
| `anthropic/claude-sonnet-4-6` | Anthropic API | `ANTHROPIC_API_KEY` en env |
| `ollama/qwen2.5:7b` | Ollama local | `OLLAMA_API_BASE` con la URL |
| `groq/llama-3.3-70b-versatile` | Groq API | `GROQ_API_KEY` en env |

En el código, `_build_model()` construye el string correcto leyendo la config:

```python
# backend/app/agent/chat_agent.py
def _build_model() -> str:
    if settings.ai_provider == "claude":
        os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
        return f"anthropic/{settings.claude_model}"   # "anthropic/claude-haiku-4-5"
    if settings.ai_provider == "ollama":
        os.environ["OLLAMA_API_BASE"] = settings.ollama_base_url
        return f"ollama/{settings.ollama_model}"       # "ollama/qwen2.5:7b"
    ...
```

### Llamada síncrona vs asíncrona

LiteLLM tiene dos versiones de cada función:

```python
# Síncrona — bloquea hasta recibir respuesta completa
response = litellm.completion(model=..., messages=...)

# Asíncrona — compatible con async/await, no bloquea
response = await litellm.acompletion(model=..., messages=..., stream=True)
```

En el proyecto, Phase 1 (tool calling) usa `completion` síncrona dentro de un thread, y Phase 2 (streaming) usa `acompletion` asíncrona con `stream=True`.

---

## 4. La API de Anthropic en detalle

### El endpoint `/v1/messages`

Toda la interacción con Claude ocurre en un único endpoint REST. No hay "conversaciones" guardadas en Anthropic — cada petición envía el historial completo:

```http
POST https://api.anthropic.com/v1/messages
Authorization: x-api-key: sk-ant-...
Content-Type: application/json

{
  "model": "claude-haiku-4-5",
  "max_tokens": 4096,
  "system": "Eres un asistente financiero...",
  "messages": [
    {"role": "user",      "content": "¿cuánto gasté en restaurantes?"},
    {"role": "assistant", "content": null, "tool_use": [...]},
    {"role": "user",      "content": [{"type": "tool_result", ...}]},
    ...
  ],
  "tools": [...]
}
```

Esto es importante: **Claude no tiene memoria**. Cada petición incluye toda la conversación desde el principio. LiteLLM y el código del agente construyen esta lista de mensajes acumulando todo el historial.

### Tool calling — cómo Claude decide llamar una función

Cuando Claude recibe tools, puede responder de dos formas:

**A) Responde directamente con texto:**
```json
{
  "stop_reason": "end_turn",
  "content": [
    {"type": "text", "text": "Tu saldo es 2.480 €"}
  ]
}
```

**B) Decide llamar a una o varias tools:**
```json
{
  "stop_reason": "tool_use",
  "content": [
    {
      "type": "tool_use",
      "id": "toolu_01XY...",
      "name": "get_expenses_by_category",
      "input": {"category": "restaurantes", "period": "current_month", "user_id": 1}
    }
  ]
}
```

Cuando `stop_reason` es `"tool_use"`, el modelo **no ha terminado**. Está pidiendo al código que ejecute la función y le devuelva el resultado.

### El ciclo de tool calling

```
Código                              Claude
  │                                   │
  │── messages con herramientas ──────▶│
  │                                   │ "Necesito get_expenses_by_category"
  │◀── stop_reason: "tool_use" ───────│
  │                                   │
  │  ejecuta get_expenses_by_category()
  │  result = {"total": 187.50, ...}
  │                                   │
  │── messages + tool_result ─────────▶│
  │                                   │ "Bien, ahora respondo al usuario"
  │◀── stop_reason: "end_turn" ───────│
  │    text: "Has gastado 187,50 €..."│
```

Este ciclo puede repetirse hasta 7 veces si Claude necesita llamar múltiples herramientas.

### Cómo se pasan los tools a la API

El formato que LiteLLM acepta (y traduce para Anthropic) es el estándar de OpenAI:

```python
TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_expenses_by_category",
            "description": "Total gastado en una categoría en un período.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "restaurantes, supermercado, transporte..."
                    },
                    "period": {
                        "type": "string",
                        "enum": ["current_month", "last_month", "last_3_months", "all_time"]
                    },
                    "user_id": {"type": "integer"}
                },
                "required": ["category"]
            }
        }
    },
    # ... 22 tools más
]
```

La `description` es crucial: Claude la usa para decidir cuándo llamar cada tool. Una buena descripción hace que el modelo elija la herramienta correcta.

### Streaming

Con `stream=True`, en vez de esperar a que Claude genere toda la respuesta, la API envía chunks según los va generando:

```python
stream = await litellm.acompletion(model=model, messages=msgs, stream=True)
async for chunk in stream:
    delta = chunk.choices[0].delta.content or ""
    # delta puede ser "", "Has", " gastado", " **187", ",50 €**"...
```

Cada `chunk` tiene un pequeño fragmento del texto. El código los acumula y los reenvía al navegador via SSE.

---

## 5. El agente en dos fases

El agente (`chat_agent.py`) orquesta todo. Funciona en dos fases secuenciales.

### Fase 1 — Recopilación de datos con tools

```python
# _run_tool_loop_async() — corre en un thread (asyncio.to_thread)
for _ in range(7):   # máximo 7 iteraciones
    response = litellm.completion(
        model=model,
        messages=messages,
        tools=TOOLS_SCHEMA,
        tool_choice="auto",   # Claude decide si llama tools o no
    )

    tool_calls = response.choices[0].message.tool_calls

    if not tool_calls:
        break   # Claude no quiere llamar más tools → Fase 1 terminada

    # Ejecutar cada tool que Claude ha pedido
    for tc in tool_calls:
        name = tc.function.name            # "get_expenses_by_category"
        args = json.loads(tc.function.arguments)  # {"category": "restaurantes", ...}
        func = TOOL_MAP[name]              # función Python real
        result = func(**args)              # ejecuta la query SQLite
        messages.append({
            "role": "tool",
            "tool_call_id": tc.id,
            "content": json.dumps(result)  # resultado de vuelta a Claude
        })
```

Al final de Fase 1, `messages` contiene toda la conversación incluidos los resultados de las tools. Claude tiene toda la información que necesita.

### Por qué en un thread separado

LiteLLM y yfinance son síncronos (bloquean el hilo hasta recibir datos). En Python async, no puedes llamar a funciones síncronas lentas directamente porque bloquearías el event loop (FastAPI no podría atender otras peticiones). La solución es `asyncio.to_thread`:

```python
async def _run_tool_loop_async(messages, model):
    def _sync():
        # código síncrono que puede tardar varios segundos
        ...llamadas a litellm.completion() y yfinance...
        return messages

    return await asyncio.to_thread(_sync)
    # asyncio.to_thread ejecuta _sync en un thread del pool
    # el event loop queda libre para otras peticiones mientras espera
```

### Fase 2 — Respuesta en streaming

Una vez terminado el tool loop, se añade el trigger al historial y se hace la llamada final con `stream=True`:

```python
messages.append({"role": "user", "content": "Escribe ahora la respuesta al usuario."})

stream = await litellm.acompletion(model=model, messages=messages, stream=True)
```

Claude ya tiene todos los datos (están en el historial de mensajes como resultados de tools) y ahora genera la respuesta final. El SYSTEM_PROMPT le dice que termine siempre con `---JSON---` seguido de un JSON con los datos del gráfico.

### Detección del marcador `---JSON---`

El texto y el JSON llegan mezclados en el stream. El código detecta el marcador en tiempo real:

```python
_MARKER = "\n---JSON---\n"
accumulated = ""
text_yielded = 0
json_found = False
json_raw = ""

async for chunk in stream:
    delta = chunk.choices[0].delta.content or ""
    accumulated += delta

    if json_found:
        # Ya pasamos el marcador → acumular JSON
        json_raw += delta
        continue

    marker_idx = accumulated.find(_MARKER)
    if marker_idx != -1:
        # Encontramos el marcador
        pending_text = accumulated[:marker_idx][text_yielded:]
        if pending_text:
            yield SSE_token(pending_text)      # último trozo de texto
        json_found = True
        json_raw = accumulated[marker_idx + len(_MARKER):]
    else:
        # Aún no hay marcador — enviar lo que es seguro
        # (reservar los últimos len(_MARKER) chars por si el marcador llega partido)
        safe_end = max(text_yielded, len(accumulated) - len(_MARKER))
        if safe_end > text_yielded:
            yield SSE_token(accumulated[text_yielded:safe_end])
            text_yielded = safe_end
```

El truco de `safe_end` es importante: si el marcador llega partido entre dos chunks (`"\n---"` en uno y `"JSON---\n"` en el siguiente), el código no enviaría el marcador al usuario accidentalmente.

---

## 6. Streaming con SSE

### Qué son Server-Sent Events

SSE es un protocolo HTTP simple para que el servidor envíe datos al navegador de forma continua. A diferencia de WebSockets (bidireccional), SSE es solo servidor → cliente.

Formato del protocolo:
```
data: {"type":"token","text":"Has"}\n\n
data: {"type":"token","text":" gastado"}\n\n
data: {"type":"done","chart_type":"bar",...}\n\n
```

Cada evento es una línea que empieza por `data: ` y termina con `\n\n` (doble salto de línea).

### Cómo el backend envía SSE

FastAPI usa `StreamingResponse` con un generador asíncrono:

```python
async def process_chat_stream(message, user_id, history):
    # ... Fase 1 tool loop ...
    # ... Fase 2 streaming ...

    async for chunk in stream:
        if hay_texto:
            yield f"data: {json.dumps({'type': 'token', 'text': texto})}\n\n"

    # Al final, evento done con datos del gráfico
    yield f"data: {json.dumps({'type': 'done', 'chart_type': ..., ...})}\n\n"

# En la ruta FastAPI:
return StreamingResponse(
    process_chat_stream(...),
    media_type="text/event-stream",
)
```

`yield` es clave: cada vez que el generador hace `yield`, FastAPI envía esos bytes al cliente inmediatamente sin esperar a que termine la función.

### Cómo el frontend recibe SSE

El frontend usa la API nativa `fetch` + `ReadableStream`:

```javascript
const res = await fetch('/chat/stream', {
    method: 'POST',
    body: JSON.stringify({ message, user_id: 1, history }),
})

const reader = res.body.getReader()   // stream de bytes
const decoder = new TextDecoder()
let buffer = ''

while (true) {
    const { done, value } = await reader.read()   // espera el siguiente chunk
    if (done) break

    buffer += decoder.decode(value, { stream: true })

    // Separar en líneas completas (puede llegar más de una por chunk)
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''   // la última línea puede estar incompleta

    for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const event = JSON.parse(line.slice(6))

        if (event.type === 'token') {
            // Actualizar el texto del mensaje en pantalla
            streamingText += event.text
            setMessages(prev => [...prev.slice(0, -1), { role: 'assistant', text: streamingText }])
        } else if (event.type === 'done') {
            // Mostrar gráfico si hay datos
        }
    }
}
```

### Los tres tipos de eventos SSE

| Evento | Cuándo llega | Qué hace el frontend |
|--------|-------------|---------------------|
| `{"type":"token","text":"..."}` | Durante Phase 2, uno por chunk | Añade texto al bubble del asistente |
| `{"type":"done","chart_type":"...","chart_data":[...],"pending_action":...}` | Al final | Muestra gráfico o modal de confirmación |
| `{"type":"error","text":"..."}` | Si algo falla | Muestra mensaje de error |

El primer `token` también oculta el spinner de carga (los tres puntos que aparecen mientras Claude piensa en Phase 1).

---

## 7. El ciclo completo de una pregunta

Aquí está el flujo completo con timestamps aproximados para "¿cuánto gasté en restaurantes?":

```
t=0ms    Usuario pulsa "Enviar"
         Frontend → POST /chat/stream

t=0ms    FastAPI recibe la petición
         Crea el generador process_chat_stream()
         Devuelve StreamingResponse (la conexión SSE queda abierta)

t=5ms    process_chat_stream() construye messages:
         [system: SYSTEM_PROMPT, user: "¿cuánto gasté en restaurantes?"]
         Lanza _run_tool_loop_async() en un thread

── PHASE 1 ───────────────────────────────────────────────────────
t=10ms   Thread → litellm.completion() → POST api.anthropic.com/v1/messages
         Claude recibe: system prompt + pregunta + 22 tools disponibles

t=1500ms Claude responde: tool_use get_expenses_by_category(category="restaurantes")
         Thread ejecuta la función Python → query SQLite
         result = {"total": 187.50, "period": "current_month"}
         Añade resultado a messages

t=1510ms Thread → litellm.completion() (2ª llamada a Anthropic)
         Claude recibe: historial + resultado de la tool
         Claude responde: stop_reason="end_turn" (no necesita más datos)
         Phase 1 terminada. Thread devuelve messages completos.

── PHASE 2 ───────────────────────────────────────────────────────
t=1510ms process_chat_stream() añade: user: "Escribe ahora la respuesta al usuario."
         → litellm.acompletion(..., stream=True) → POST api.anthropic.com/v1/messages

t=1700ms Primer chunk llega: "Has"
         yield SSE: data: {"type":"token","text":"Has"}\n\n
         Frontend recibe → muestra "Has" en pantalla, oculta spinner

t=1750ms Más chunks: " gastado", " **187,50 €**", " en restaurantes"...
         Cada uno yield SSE → frontend actualiza el texto en tiempo real

t=2400ms Claude termina el texto y escribe "\n---JSON---\n"
         Código detecta el marcador, para de enviar tokens de texto
         Acumula el JSON del gráfico

t=2450ms Stream termina. json_raw = '{"chart_type":"bar","chart_data":[...],...}'
         yield SSE: data: {"type":"done","chart_type":"bar","chart_data":[...]}\n\n

t=2460ms Frontend recibe "done"
         Renderiza el gráfico de barras bajo el mensaje de texto

t=2460ms Conexión SSE se cierra
```

**Total:** ~2,5 segundos de los cuales ~1,5s son Phase 1 (tool loop + 2 llamadas a Anthropic) y ~1s es Phase 2 (streaming de texto). El usuario ve el primer texto en pantalla a los ~1,7s y el gráfico a los ~2,5s.

---

## Apéndice — Archivos clave del sistema

| Archivo | Responsabilidad |
|---------|----------------|
| `backend/app/agent/chat_agent.py` | Orquestador: SYSTEM_PROMPT, tool loop, streaming, parseo del marcador |
| `backend/app/agent/financial_mcp.py` | Las 23 funciones Python que son las "tools" del agente |
| `backend/app/api/routes/chat.py` | Endpoints FastAPI `/chat/` y `/chat/stream` |
| `backend/app/models/financial.py` | Modelos SQLAlchemy (tablas de la BD) |
| `backend/app/schemas/financial.py` | Validación Pydantic de requests/responses |
| `backend/app/core/config.py` | Configuración (API keys, modelo, BD) desde `.env` |
| `frontend/src/components/ChatBox.jsx` | UI del chat + lógica de streaming SSE |
| `docker-compose.yml` | Orquestación de contenedores |
| `backend/seed.py` | Poblar la BD con datos de prueba |
