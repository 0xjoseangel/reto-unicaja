# Documentación Técnica — "Habla con tu dinero"

Asistente financiero conversacional para el reto Cátedra Unicaja · Universidad de Granada.  
Autor: Jose Angel Carretero Montes.

---

## Índice

1. [Visión general](#1-visión-general)
2. [Arquitectura del sistema](#2-arquitectura-del-sistema)
3. [Backend — FastAPI](#3-backend--fastapi)
4. [Base de datos — SQLite + SQLAlchemy](#4-base-de-datos--sqlite--sqlalchemy)
5. [El agente IA — Groq + MCP](#5-el-agente-ia--groq--mcp)
6. [Frontend — React + Recharts](#6-frontend--react--recharts)
7. [Cómo arrancarlo](#7-cómo-arrancarlo)
8. [Flujo completo de una petición](#8-flujo-completo-de-una-petición)

---

## 1. Visión general

El usuario escribe en lenguaje natural ("¿cuánto gasté en restaurantes este mes?") y la app:

1. Envía el mensaje al backend junto con el **historial de conversación**.
2. Un agente IA (Groq / Llama) decide qué consultas SQL hacer usando **tool calling**.
3. Ejecuta las herramientas, obtiene datos reales de SQLite y genera una respuesta.
4. El frontend muestra el texto y, si procede, un **gráfico dinámico**.

---

## 2. Arquitectura del sistema

```
┌─────────────────────────────────────────────────────────────┐
│  FRONTEND  React + Vite (puerto 3000)                       │
│                                                             │
│  App.jsx                                                    │
│  └── ChatBox.jsx  ←→  api.js  ──POST /chat/──┐             │
│                                               │             │
└───────────────────────────────────────────────┼─────────────┘
                                                │ HTTP + Vite proxy
┌───────────────────────────────────────────────┼─────────────┐
│  BACKEND  FastAPI + Uvicorn (puerto 8000)      │             │
│                                               ▼             │
│  main.py ── router /chat/ ── chat_agent.py                  │
│                               │                             │
│                    ┌──────────┴──────────┐                  │
│                    │  Groq API (externa)  │                  │
│                    │  llama-3.3-70b       │                  │
│                    └──────────┬──────────┘                  │
│                               │ tool calls                  │
│                    financial_mcp.py (12 tools)              │
│                               │ SQLAlchemy                  │
│                    ┌──────────┴──────────┐                  │
│                    │  SQLite             │                   │
│                    │  data/db.sqlite3    │                   │
│                    └─────────────────────┘                  │
└─────────────────────────────────────────────────────────────┘
```

**Comunicación frontend↔backend:** Vite tiene un proxy configurado que redirige `/chat` y `/transactions` a `http://localhost:8000`. Esto evita errores CORS sin tocar cabeceras.

---

## 3. Backend — FastAPI

### Estructura de carpetas

```
backend/
├── app/
│   ├── main.py                   # App FastAPI, CORS, routers
│   ├── core/
│   │   ├── config.py             # Variables de entorno (Pydantic Settings)
│   │   └── database.py           # Motor SQLAlchemy, SessionLocal
│   ├── models/
│   │   └── financial.py          # Tablas ORM: User, Account, Transaction
│   ├── schemas/
│   │   └── financial.py          # Contratos de entrada/salida (Pydantic)
│   ├── services/
│   │   └── query_service.py      # Funciones de consulta SQL reutilizables
│   ├── agent/
│   │   ├── graph.py              # Grafo de LangGraph que orquesta el chat
│   │   ├── chat_agent.py         # Prompts, schemas de tools, fases 1 y 2
│   │   ├── actions.py            # Validación/aprobación/ejecución de Bizum e inversiones
│   │   └── financial_mcp.py      # Herramientas de consulta (SQLite) + operaciones de dinero
│   └── api/
│       └── routes/
│           ├── chat.py           # POST /chat/, /chat/stream, /chat/actions/{id}
│           └── transactions.py   # GET /transactions/, /summary, /accounts
├── seed.py                       # Genera datos de prueba realistas
├── requirements.txt
└── .env                          # GROQ_API_KEY=...
```

### FastAPI — conceptos clave

**FastAPI** es un framework web asíncrono. Cada ruta es una función Python con anotaciones de tipo que sirven tanto de documentación como de validación automática.

```python
# Así se define una ruta
@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest):          # ChatRequest se valida automáticamente
    return await process_chat(request.message, request.user_id, history)
```

`async def` significa que la función no bloquea el servidor mientras espera la respuesta de Groq. FastAPI puede atender otras peticiones en ese tiempo.

### Pydantic — validación de datos

Pydantic garantiza que lo que entra y sale de la API tiene el formato correcto:

```python
class ChatRequest(BaseModel):
    message: str
    user_id: int = 1
    history: list[HistoryMessage] = []   # lista vacía por defecto

class ChatResponse(BaseModel):
    response: str
    chart_type: Literal["bar", "line", "pie"] | None = None
    chart_data: list[ChartDataPoint] | None = None
    chart_title: str | None = None
```

Si el cliente envía `user_id: "abc"` Pydantic devuelve un error 422 automáticamente antes de que llegue a tu código.

### Pydantic Settings — configuración

```python
# core/config.py
class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/db.sqlite3"
    groq_api_key: str = ""

    class Config:
        env_file = ".env"

settings = Settings()   # lee automáticamente backend/.env
```

Usas `settings.groq_api_key` en cualquier parte del código. Si la variable existe en `.env` o en el entorno del sistema operativo, se carga automáticamente.

---

## 4. Base de datos — SQLite + SQLAlchemy

### Por qué SQLite

SQLite guarda toda la base de datos en un único fichero (`data/db.sqlite3`). No necesita un servidor separado. Es perfecta para desarrollo y demos.

### Modelos SQLAlchemy 2.0

SQLAlchemy es un ORM (Object-Relational Mapper): traduce clases Python a tablas SQL.

```python
class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"))
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(20))  # "ingreso" | "gasto"
    category: Mapped[str] = mapped_column(String(50))
    description: Mapped[str] = mapped_column(String(200), nullable=True)
    date: Mapped[datetime] = mapped_column(DateTime)
```

`Mapped[int]` es la sintaxis moderna (SQLAlchemy 2.0). Le dice a Python y al IDE el tipo del campo.

### Relaciones entre tablas

```
User (1) ──── (N) Account (1) ──── (N) Transaction
```

Un usuario tiene varias cuentas. Cada cuenta tiene muchas transacciones.

```python
# En el modelo Account:
transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="account")
```

Con esto puedes hacer `account.transactions` y SQLAlchemy hace el JOIN automáticamente.

### SessionLocal — gestión de conexiones

```python
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
```

Cada tool del agente crea su propia sesión y la cierra al terminar:

```python
db = SessionLocal()
try:
    resultado = db.query(Transaction).filter(...).all()
    return resultado
finally:
    db.close()   # siempre se cierra, aunque haya un error
```

### Datos de prueba (seed.py)

El script `seed.py` genera 12 meses de transacciones realistas:
- 1 usuario, 2 cuentas (corriente + ahorro)
- ~316 transacciones: nóminas, restaurantes, supermercado, alquiler, ocio, etc.
- Establecimientos reales: Mercadona, Netflix, Endesa, Burger King...

Para ejecutarlo: `python seed.py` (dentro de `backend/` con el entorno activo).

---

## 5. El agente IA — Groq + MCP

Esta es la parte más importante del proyecto. Aquí es donde ocurre la "magia".

### ¿Qué es Groq?

Groq es una plataforma de inferencia de modelos de lenguaje muy rápida. Usamos el modelo `llama-3.3-70b-versatile` — un LLM de 70.000 millones de parámetros. Es compatible con la API de OpenAI, lo que facilita la integración.

Tier gratuito: 30 peticiones/minuto, suficiente para demos y desarrollo.

### ¿Qué es MCP?

MCP (Model Context Protocol) es un estándar para definir herramientas que los modelos de lenguaje pueden usar. En este proyecto, usamos `FastMCP` para registrar funciones Python como herramientas:

```python
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("financial-assistant")

@mcp.tool()
def get_financial_summary(user_id: int = 1) -> dict:
    """El modelo lee este docstring para saber cuándo usar esta herramienta."""
    db = SessionLocal()
    # ... consulta SQL ...
```

El decorador `@mcp.tool()` registra la función en el servidor MCP. Pero la función sigue siendo Python normal — se puede llamar directamente, sin ninguna capa extra.

Las funciones que mueven dinero (`execute_bizum`, `execute_investment`) **no** llevan el decorador ni están en la lista de tools del agente: el modelo no puede llamarlas. Ver [acciones-langgraph.md](acciones-langgraph.md).

### Herramientas principales

Lista resumida; la completa está en `TOOLS_SCHEMA` (`chat_agent.py`). Ninguna recibe el `user_id` del modelo: lo inyecta el servidor a partir del JWT.

| Herramienta | Para qué sirve |
|---|---|
| `get_financial_summary` | Saldo, ingresos totales, gastos totales |
| `get_expenses_by_category` | Total gastado en una categoría en un período |
| `get_monthly_evolution` | Gráfico de evolución mensual de una categoría |
| `get_category_breakdown` | Desglose de todas las categorías |
| `get_transaction_count` | Contar visitas/compras (ej: "¿cuántas veces fui al super?") |
| `get_places_by_category` | Lista de establecimientos visitados (ej: "¿a qué restaurantes fui?") |
| `get_spending_analysis` | Comparación mes actual vs promedio histórico |
| `search_specific_transactions` | Buscar por nombre de comercio (ej: "Netflix") |
| `get_recent_transactions` | Últimos movimientos |
| `get_largest_expenses` | Gastos más grandes de un período |
| `propose_bizum` | Proponer un Bizum (no ejecuta nada; el usuario lo aprueba en un modal) |
| `propose_investment` | Proponer la compra de un activo (no ejecuta nada; precio y coste los fija el servidor) |
| `get_bizum_history` | Historial de Bizums enviados |

### El bucle agente — cómo funciona por dentro

El agente funciona en **dos fases** por petición:

**Fase 1 — Recopilación de datos**

```
Usuario: "¿A qué restaurantes he ido este año?"
         ↓
  Groq recibe: system_prompt + historial + mensaje
         ↓
  Groq decide: voy a llamar get_places_by_category(category="restaurantes", period="all_time")
         ↓
  Código Python ejecuta la función → consulta SQLite → devuelve datos
         ↓
  Resultados se añaden al historial de mensajes
         ↓
  Groq ya no necesita más datos → sale del bucle
```

El bucle permite hasta 7 iteraciones por si el modelo necesita llamar varias herramientas encadenadas.

Las dos fases son los nodos `agent` y `respond` de un grafo de LangGraph (`graph.py`). Ver [agente-ia.md §5](agente-ia.md#5-el-agente-como-grafo-de-langgraph).

**Fase 2 — Respuesta estructurada**

```python
# Se añade al historial:
{"role": "user", "content": "Genera la respuesta final en JSON con esta estructura: ..."}

# Llamada con json_object mode — Groq GARANTIZA que devuelve JSON válido
final_response = client.chat.completions.create(
    model="llama-3.3-70b-versatile",
    messages=messages,
    response_format={"type": "json_object"},
)
```

El JSON tiene siempre esta forma:
```json
{
  "response_text": "Has visitado 5 restaurantes este año...",
  "chart_type": "bar",
  "chart_data": "[{\"name\": \"Burger King\", \"value\": 598.85}]",
  "chart_title": "Gasto por restaurante"
}
```

### Contexto conversacional

Cada petición envía el historial completo de la conversación. Esto permite referencias como "¿y el mes pasado?" sin repetir el contexto:

```python
# En ChatBox.jsx
const updatedHistory = [...history, { role: "user", content: message }]
const data = await sendChatMessage(message, updatedHistory)
setHistory([...updatedHistory, { role: "assistant", content: data.response }])
```

El historial vive en el frontend (estado React); el backend no guarda la conversación entre peticiones. La única excepción son las operaciones pendientes de aprobación (Bizum, inversión): su estado se conserva en el checkpointer de LangGraph y en la tabla `pending_actions` hasta que el usuario decide.

### Bizum e inversiones — operaciones que mueven dinero

El LLM **no decide** si se ejecuta una operación. Solo puede proponerla, y la ejecuta el código después de que el usuario la apruebe en un modal:

1. Usuario: "Manda 30€ a María"
2. El modelo llama `propose_bizum(recipient="María", amount=30)`. No se ejecuta nada.
3. El grafo valida la propuesta con código: límite de 2000 €, saldo suficiente. Para una inversión, además fija el precio de mercado y el coste en euros.
4. El grafo se para (`interrupt()`) y el frontend muestra el modal con los datos validados y un `action_id`.
5. Usuario pulsa **Confirmar** → `POST /chat/actions/{action_id}` con `{"decision": "approve"}`.
6. El grafo se reanuda y ejecuta la operación **una sola vez**: descuenta de la cuenta corriente y crea la transacción.

Escribir "sí, confirma" en el chat no ejecuta nada. Un segundo clic en Confirmar devuelve 409, y una propuesta de hace más de 5 minutos, 410.

Detalle completo (grafo, checkpointer, idempotencia, API): [acciones-langgraph.md](acciones-langgraph.md).

---

## 6. Frontend — React + Recharts

### Estructura

```
frontend/src/
├── App.jsx              # Layout principal (solo envuelve ChatBox)
├── components/
│   ├── ChatBox.jsx      # Chat completo: historial, input, sugerencias
│   └── InlineChart.jsx  # Gráfico embebido dentro del chat
├── services/
│   └── api.js           # fetch al backend
└── hooks/
    └── useRevealObserver.js  # Animación de entrada al hacer scroll
```

### ChatBox.jsx — estado y flujo

```jsx
const [messages, setMessages] = useState([...])  // mensajes visuales (incluye charts)
const [history, setHistory] = useState([])        // historial para la IA (solo texto)
const [loading, setLoading] = useState(false)
```

`messages` y `history` son dos estados separados a propósito:
- `messages` contiene todo lo visual: burbujas de texto, gráficos inline, etc.
- `history` solo contiene pares `{role, content}` de texto plano que se envían a Groq.

Flujo de `handleSend`:

```
Usuario escribe → setMessages (añade burbuja usuario) → llamada API con historial
                                                              ↓
                                          setMessages (añade respuesta + chart si hay)
                                          setHistory  (actualiza historial IA)
```

### InlineChart.jsx — gráficos dentro del chat

Los gráficos aparecen como mensajes en el chat, no en un panel separado. Usa Recharts:

```jsx
// chart_type determina qué componente Recharts renderizar
if (chartType === "bar") return <BarChart data={chartData}>...</BarChart>
if (chartType === "line") return <LineChart data={chartData}>...</LineChart>
if (chartType === "pie") return <PieChart>...</PieChart>
```

Los datos vienen del backend como `[{name: "Restaurantes", value: 450.5}, ...]`.

### Proxy Vite — sin CORS

```javascript
// vite.config.js
proxy: {
  '/chat': 'http://localhost:8000',
  '/transactions': 'http://localhost:8000',
}
```

Cuando el frontend llama a `/chat/`, Vite lo redirige internamente a `http://localhost:8000/chat/`. Para el navegador, parece que frontend y backend están en el mismo origen → no hay CORS.

---

## 7. Cómo arrancarlo

### Requisitos previos
- Python 3.12
- Node.js 20+
- `uv` (gestor de paquetes Python)
- Cuenta en [console.groq.com](https://console.groq.com) con una API key

### Backend

```bash
cd backend

# Primera vez: crear entorno virtual e instalar dependencias
uv venv --python 3.12 .venv
source .venv/bin/activate
uv pip install -r requirements.txt

# Crear el fichero de configuración
echo "GROQ_API_KEY=gsk_tu_key_aqui" > .env

# Generar datos de prueba
python seed.py

# Arrancar el servidor
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev      # http://localhost:3000
```

### Verificar que funciona

```bash
# El backend responde
curl http://localhost:8000/

# Datos de la base de datos
curl http://localhost:8000/transactions/summary

# El chat funciona
curl -X POST http://localhost:8000/chat/ \
  -H "Content-Type: application/json" \
  -d '{"message": "¿Cuál es mi saldo?"}'
```

---

## 8. Flujo completo de una petición

Siguiendo "Manda un Bizum de 50€ a Carlos":

```
1. FRONTEND
   ChatBox.jsx: handleSend("Manda un Bizum de 50€ a Carlos")
   → history = [{role:"user", content:"Manda un Bizum de 50€ a Carlos"}]
   → api.js: POST /chat/stream con {message, history} + JWT

2. BACKEND — ruta
   chat.py: recibe ChatRequest; user_id sale del JWT (get_current_user)
   → process_chat_stream(message, user_id, history)

3. BACKEND — grafo (graph.py)
   Estado inicial: messages = [system: SYSTEM_PROMPT, user: "Manda un Bizum..."]
   thread_id = uuid nuevo

4. Nodo agent — Fase 1
   El modelo llama propose_bizum(recipient="Carlos", amount=50)
   → se anota la propuesta, no se toca la BD → sale del bucle

5. Nodo validate
   actions.validate_proposal(): importe ≤ 2000€, saldo ≥ 50€ → OK
   → crea pending_actions(id=thread_id, status="pending")

6. Nodo await_approval
   interrupt() → el estado se guarda en checkpoints.sqlite
   → SSE: done {pending_action: {type:"bizum_confirm", action_id, recipient:"Carlos", amount:50}}

7. FRONTEND
   ChatBox muestra el modal de confirmación

--- El usuario pulsa "Confirmar" ---

8. FRONTEND
   api.js: decideAction(action_id, "approve") → POST /chat/actions/{action_id}

9. BACKEND — ruta
   actions.decide(): comprueba dueño y caducidad; pending → approved
   → resume_chat_stream(action_id): Command(resume) sobre el mismo thread

10. Nodo execute
    actions.execute(): approved → executed + execute_bizum() en una transacción
    → account.balance -= 50, Transaction(category="bizum"), BizumTransfer
    → {success: true, nuevo_saldo_total: ...}

11. Nodo respond — Fase 2
    El modelo redacta el resultado real: "Bizum enviado a Carlos. Nuevo saldo: ..."
    → SSE: token, token... done

12. FRONTEND
    ChatBox muestra la confirmación del Bizum
```

---

## Resumen tecnológico

| Capa | Tecnología | Por qué |
|---|---|---|
| API | FastAPI | Asíncrono, validación automática, docs en /docs |
| Validación | Pydantic v2 | Contratos de datos entre capas |
| ORM | SQLAlchemy 2.0 | Abstracción SQL tipada |
| Base de datos | SQLite | Sin servidor, fichero único, perfecto para demos |
| IA | Groq / Llama 3.3 70B | Rápido, tier gratuito generoso, API OpenAI-compatible |
| Tools | MCP (FastMCP) | Estándar open source para tool calling con LLMs |
| Orquestación | LangGraph | Grafo con aprobación humana (`interrupt`) y estado persistido para las operaciones que mueven dinero |
| Frontend | React + Vite | Componentes reactivos, hot reload, proxy integrado |
| Gráficos | Recharts | Librería de gráficos para React, simple y flexible |
