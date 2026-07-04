# "Habla con tu dinero" — Documentación técnica didáctica

> Este documento explica **qué se construyó, cómo funciona y por qué** cada decisión técnica. Está pensado para que puedas estudiar cada tecnología antes de seguir construyendo.

---

## Tabla de contenidos

1. [Visión general del sistema](#1-visión-general-del-sistema)
2. [Estructura de directorios](#2-estructura-de-directorios)
3. [Docker y docker-compose](#3-docker-y-docker-compose)
4. [Backend — FastAPI](#4-backend--fastapi)
5. [Base de datos — SQLAlchemy + SQLite](#5-base-de-datos--sqlalchemy--sqlite)
6. [Validación de datos — Pydantic](#6-validación-de-datos--pydantic)
7. [Lógica de negocio — el servicio de consultas](#7-lógica-de-negocio--el-servicio-de-consultas)
8. [Frontend — React + Vite](#8-frontend--react--vite)
9. [Visualización — Recharts](#9-visualización--recharts)
10. [Flujo completo de una petición](#10-flujo-completo-de-una-petición)
11. [Qué viene en la Fase 2 (LangGraph)](#11-qué-viene-en-la-fase-2-langgraph)

---

## 1. Visión general del sistema

El proyecto es una **aplicación web de dos capas** que se comunican entre sí:

```
┌─────────────────────────────────────────────────────────────────┐
│  NAVEGADOR (localhost:3000)                                      │
│                                                                  │
│  React App                                                       │
│  ├── Sidebar: saldo, cuentas, top categorías                     │
│  ├── Panel superior: gráficos dinámicos (Recharts)               │
│  └── Panel inferior: chat (pregunta → respuesta + gráfico)       │
└────────────────────────┬────────────────────────────────────────┘
                         │ HTTP (fetch)
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  SERVIDOR (localhost:8000)                                       │
│                                                                  │
│  FastAPI (Python)                                                │
│  ├── GET /transactions/summary   → resumen financiero            │
│  ├── GET /transactions/accounts  → lista de cuentas             │
│  ├── GET /transactions/          → lista de transacciones        │
│  └── POST /chat/                 → procesa lenguaje natural      │
│                                                                  │
│  SQLite (archivo db.sqlite3)                                     │
│  └── Tablas: users, accounts, transactions                       │
└─────────────────────────────────────────────────────────────────┘
```

**¿Por qué esta separación?**
- El backend y el frontend son responsabilidades distintas. Separándolos puedes cambiar uno sin tocar el otro (por ejemplo, reemplazar React por una app móvil).
- La comunicación es mediante una **API REST**: el frontend hace peticiones HTTP y recibe JSON.

---

## 2. Estructura de directorios

```
reto-unicaja/
├── docker-compose.yml          ← orquesta los dos contenedores
├── CLAUDE.md                   ← instrucciones del proyecto para la IA
│
├── backend/
│   ├── Dockerfile              ← cómo construir la imagen del backend
│   ├── requirements.txt        ← dependencias Python
│   ├── seed.py                 ← script para poblar la base de datos
│   └── app/
│       ├── main.py             ← punto de entrada de FastAPI
│       ├── core/
│       │   ├── config.py       ← configuración (variables de entorno)
│       │   └── database.py     ← conexión a SQLite, sesión de BD
│       ├── models/
│       │   └── financial.py    ← tablas de la base de datos (ORM)
│       ├── schemas/
│       │   └── financial.py    ← contratos de datos (Pydantic)
│       ├── services/
│       │   └── query_service.py ← lógica de negocio
│       ├── api/
│       │   └── routes/
│       │       ├── transactions.py ← endpoints GET
│       │       └── chat.py         ← endpoint POST /chat
│       └── agent/
│           └── graph.py        ← (vacío) reservado para LangGraph
│
└── frontend/
    ├── Dockerfile              ← cómo construir la imagen del frontend
    ├── package.json            ← dependencias Node.js
    ├── vite.config.js          ← configuración de Vite
    ├── index.html              ← HTML raíz
    └── src/
        ├── main.jsx            ← punto de entrada de React
        ├── App.jsx             ← componente raíz + layout
        ├── index.css           ← estilos globales
        ├── components/
        │   ├── ChatBox.jsx     ← interfaz de chat
        │   └── ChartPanel.jsx  ← panel de gráficos
        └── services/
            └── api.js          ← funciones para llamar al backend
```

**Principio clave:** cada carpeta tiene **una sola responsabilidad**.
- `models/` solo define la estructura de la BD.
- `schemas/` solo define qué datos entran y salen de la API.
- `services/` solo contiene lógica de negocio (cálculos, consultas).
- `api/routes/` solo define las URLs y delega al servicio.

---

## 3. Docker y docker-compose

### ¿Qué es Docker?

Docker permite empaquetar una aplicación junto con **todo lo que necesita para ejecutarse** (Python, Node.js, dependencias, configuración) en una unidad llamada **contenedor**. El resultado es que la app funciona igual en cualquier máquina.

**Analogía:** un contenedor es como un USB booteable. Llevas todo el sistema operativo y programas necesarios contigo.

### Dockerfile del backend

```dockerfile
FROM python:3.12-slim          # imagen base: Python 3.12 mínimo

WORKDIR /app                   # directorio de trabajo dentro del contenedor

COPY requirements.txt .        # copiamos solo requirements.txt primero
RUN pip install --no-cache-dir -r requirements.txt  # instalamos dependencias

COPY . .                       # copiamos el resto del código

RUN mkdir -p /app/data         # carpeta para la base de datos SQLite

EXPOSE 8000                    # puerto que expone el contenedor
```

**¿Por qué copiar `requirements.txt` antes que el código?**
Docker construye imágenes en capas. Si el código cambia pero `requirements.txt` no, Docker reutiliza la capa de instalación de dependencias en caché. Esto hace las reconstrucciones mucho más rápidas.

### Dockerfile del frontend

```dockerfile
FROM node:20-alpine            # Node.js 20 versión ligera

WORKDIR /app

COPY package*.json ./          # package.json y package-lock.json
RUN npm install                # instala dependencias

COPY . .

EXPOSE 3000

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "3000"]
```

`--host 0.0.0.0` es crucial: sin esto, Vite solo escucha en `localhost` dentro del contenedor, y no sería accesible desde fuera.

### docker-compose.yml

`docker-compose` es la herramienta para **orquestar múltiples contenedores** que trabajan juntos:

```yaml
services:
  backend:
    build: ./backend           # construye la imagen desde ./backend/Dockerfile
    ports:
      - "8000:8000"            # host:contenedor — expone el puerto 8000
    volumes:
      - ./backend:/app         # monta el código local → hot-reload al editar
      - sqlite_data:/app/data  # volumen persistente para la BD
    environment:
      - DATABASE_URL=sqlite:////app/data/db.sqlite3
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  frontend:
    build: ./frontend
    ports:
      - "3000:3000"
    volumes:
      - ./frontend:/app
      - /app/node_modules      # truco: evita que el volumen sobreescriba node_modules
    environment:
      - VITE_API_URL=http://localhost:8000
    depends_on:
      - backend                # espera a que backend esté listo
    networks:
      - app_network

volumes:
  sqlite_data:                 # volumen con nombre: persiste aunque se elimine el contenedor

networks:
  app_network:
    driver: bridge             # red virtual entre contenedores
```

**Conceptos clave:**
- **`volumes`**: montan directorios del host dentro del contenedor. El truco `- /app/node_modules` crea un volumen anónimo que "protege" `node_modules` del montaje del código.
- **`networks`**: crea una red virtual donde los contenedores se comunican por nombre (`backend`, `frontend`).
- **`depends_on`**: garantiza el orden de arranque.

---

## 4. Backend — FastAPI

### ¿Qué es FastAPI?

FastAPI es un framework web de Python para construir APIs. Su característica principal es que es **asíncrono** (usa `async/await`) y genera automáticamente documentación interactiva.

Ve a `http://localhost:8000/docs` con el servidor corriendo y verás la documentación generada automáticamente.

### Punto de entrada: `app/main.py`

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import chat, transactions
from app.core.config import settings
from app.core.database import Base, engine

# Crea todas las tablas en SQLite al arrancar (si no existen)
Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name, version="0.1.0")

# Middleware CORS: permite que el frontend (localhost:3000) llame al backend (localhost:8000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Registra los routers (grupos de endpoints)
app.include_router(transactions.router)
app.include_router(chat.router)
```

**¿Qué es CORS?**
Los navegadores bloquean por seguridad las peticiones de un origen (localhost:3000) a otro (localhost:8000). El middleware CORS le dice al navegador "este servidor acepta peticiones de esos orígenes".

### Un endpoint típico: `app/api/routes/transactions.py`

```python
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.financial import SummaryOut
from app.services.query_service import get_summary

router = APIRouter(prefix="/transactions", tags=["transactions"])

@router.get("/summary", response_model=SummaryOut)
async def summary(user_id: int = 1, db: Session = Depends(get_db)):
    return get_summary(db, user_id)
```

Tres cosas importantes aquí:

1. **`APIRouter`**: agrupa endpoints bajo un prefijo (`/transactions`). Es como un "sub-app".

2. **`response_model=SummaryOut`**: FastAPI usará este schema de Pydantic para validar Y serializar la respuesta. Si el servicio devuelve campos extra, los filtra. Si faltan campos obligatorios, lanza un error.

3. **`db: Session = Depends(get_db)`**: esto es **inyección de dependencias**. FastAPI llama a `get_db()` automáticamente, obtiene una sesión de base de datos, la pasa a la función, y cuando la función termina, llama al `finally` de `get_db` para cerrar la sesión. Tú no gestionas el ciclo de vida.

### Configuración: `app/core/config.py`

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    database_url: str = "sqlite:///./data/db.sqlite3"
    app_name: str = "Habla con tu dinero"

    class Config:
        env_file = ".env"

settings = Settings()
```

`pydantic-settings` lee las variables de entorno automáticamente. Si defines `DATABASE_URL=sqlite:////app/data/db.sqlite3` en `docker-compose.yml`, sobreescribe el valor por defecto. Si no está definida, usa el default.

---

## 5. Base de datos — SQLAlchemy + SQLite

### ¿Qué es un ORM?

ORM (Object-Relational Mapper) traduce entre el mundo de los objetos Python y el mundo de las tablas SQL. En lugar de escribir:

```sql
SELECT * FROM transactions WHERE account_id = 1
```

Escribes:

```python
db.query(Transaction).filter(Transaction.account_id == 1).all()
```

Esto tiene ventajas: es más seguro (evita SQL injection), más legible, y portable a diferentes bases de datos.

### Conexión: `app/core/database.py`

```python
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from app.core.config import settings

# El engine es la conexión a la base de datos
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},  # necesario para SQLite + async
)

# SessionLocal es una fábrica de sesiones
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Clase base para todos los modelos ORM
class Base(DeclarativeBase):
    pass

# Generador de sesiones para inyección de dependencias
def get_db():
    db = SessionLocal()
    try:
        yield db       # ← el "yield" convierte esto en un generador
    finally:
        db.close()     # ← siempre se ejecuta, incluso si hay una excepción
```

**¿Por qué `yield` y no `return`?**
Con `yield`, la función se convierte en un generador. FastAPI ejecuta el código hasta el `yield` (obtiene la sesión), ejecuta el endpoint, y luego continúa después del `yield` (cierra la sesión). Es un patrón de "setup / teardown" garantizado.

### Los modelos: `app/models/financial.py`

```python
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base

class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)

    # Relación uno-a-muchos: un User tiene muchas Accounts
    accounts: Mapped[list["Account"]] = relationship("Account", back_populates="user")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    account_type: Mapped[str] = mapped_column(String(50), nullable=False)
    balance: Mapped[float] = mapped_column(Float, default=0.0)

    user: Mapped["User"] = relationship("User", back_populates="accounts")
    transactions: Mapped[list["Transaction"]] = relationship("Transaction", back_populates="account")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer, ForeignKey("accounts.id"), nullable=False)
    amount: Mapped[float] = mapped_column(Float, nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "ingreso" o "gasto"
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(String(200), nullable=True)
    date: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    account: Mapped["Account"] = relationship("Account", back_populates="transactions")
```

**SQLAlchemy 2.0 — typed mapping:**
La sintaxis `Mapped[int] = mapped_column(...)` es la forma moderna (2.0+). Usa type hints de Python para que el IDE entienda los tipos. Genera el mismo SQL que la sintaxis antigua, pero con mejor soporte de autocompletado y validación estática.

**Relaciones y claves foráneas:**
```
users (1) ←──── accounts (N)  ←──── transactions (N)
```
- `ForeignKey("users.id")` en `accounts` crea la relación a nivel SQL.
- `relationship(...)` en Python permite navegar: `user.accounts` o `account.transactions`.
- `back_populates` mantiene ambos lados sincronizados: si añades una transacción vía `account.transactions.append(tx)`, SQLAlchemy sabe que `tx.account` es esa cuenta.

### Consultas SQLAlchemy: ejemplos del proyecto

```python
# Obtener todas las cuentas de un usuario
accounts = db.query(Account).filter(Account.user_id == user_id).all()

# Suma total de gastos
total = (
    db.query(func.sum(Transaction.amount))
    .filter(
        Transaction.account_id.in_(account_ids),   # IN (1, 2, ...)
        Transaction.transaction_type == "gasto",
    )
    .scalar()  # devuelve un solo valor, no una lista
) or 0.0

# Agrupar por categoría y ordenar por total descendente
rows = (
    db.query(Transaction.category, func.sum(Transaction.amount).label("total"))
    .filter(Transaction.transaction_type == "gasto")
    .group_by(Transaction.category)
    .order_by(func.sum(Transaction.amount).desc())
    .limit(5)
    .all()
)
# rows es una lista de tuplas: [("alquiler", 7800.0), ("supermercado", 3971.0), ...]
```

### El script seed: `backend/seed.py`

```python
def seed():
    Base.metadata.create_all(bind=engine)  # crea las tablas si no existen
    db = SessionLocal()

    # Guarda de idempotencia: si ya hay datos, no duplicar
    if db.query(User).count() > 0:
        print("Base de datos ya tiene datos. Saltando seed.")
        db.close()
        return

    # Crea usuario y cuentas
    user = User(name="Jose Angel Carretero", email="joseangelcarretero300@gmail.com")
    db.add(user)
    db.flush()  # ← assign el ID sin hacer commit todavía

    checking = Account(user_id=user.id, name="Cuenta Corriente", ...)
    db.add(checking)
    db.flush()

    # Genera transacciones para los últimos 12 meses
    for months_back in range(11, -1, -1):
        ...
        # Nómina + gastos aleatorios por categoría
        transactions.append(Transaction(...))

    db.add_all(transactions)  # más eficiente que add() en bucle
    db.commit()               # persiste todo
```

**`flush()` vs `commit()`:**
- `flush()` envía los cambios a la BD dentro de la transacción actual (para obtener el ID autoincremental), pero no los confirma.
- `commit()` confirma la transacción. Si algo falla antes del `commit()`, todo se revierte automáticamente.

---

## 6. Validación de datos — Pydantic

### ¿Qué es Pydantic?

Pydantic es una librería de validación y serialización de datos. Defines modelos con type hints y Pydantic garantiza que los datos cumplen el contrato.

**Sin Pydantic:**
```python
def create_transaction(data: dict):
    amount = data.get("amount")          # puede ser None
    if not isinstance(amount, float):    # ¿y si es int? ¿str?
        raise ValueError("amount must be float")
    ...  # validates manual interminable
```

**Con Pydantic:**
```python
class TransactionCreate(BaseModel):
    amount: float
    category: str
    date: datetime

# Si `amount` viene como string "12.5", Pydantic lo convierte a float automáticamente.
# Si viene como "hola", lanza ValidationError con un mensaje claro.
tx = TransactionCreate(**data)  # listo, datos garantizados
```

### Los schemas del proyecto: `app/schemas/financial.py`

```python
class TransactionOut(BaseModel):
    id: int
    account_id: int
    amount: float
    transaction_type: str
    category: str
    description: str | None    # puede ser None (campo nullable en BD)
    date: datetime

    model_config = {"from_attributes": True}
    # ^ permite crear este schema desde un objeto SQLAlchemy
    # (antes se llamaba orm_mode = True en Pydantic v1)
```

**`from_attributes = True`** es la clave de integración con SQLAlchemy. Sin esto, Pydantic intentaría acceder a los datos como diccionario (`obj["id"]`). Con esto, los accede como atributos (`obj.id`), que es cómo funcionan los objetos SQLAlchemy.

```python
class ChatRequest(BaseModel):
    message: str
    user_id: int = 1       # valor por defecto

class ChatResponse(BaseModel):
    response: str
    chart_type: Literal["bar", "line", "pie"] | None = None
    chart_data: list[ChartDataPoint] | None = None
    chart_title: str | None = None
```

`Literal["bar", "line", "pie"]` restringe el valor a exactamente esas tres strings. Si el servicio devuelve `"donut"`, Pydantic lanza un error en desarrollo — es documentación ejecutable.

---

## 7. Lógica de negocio — el servicio de consultas

### `app/services/query_service.py`

Este archivo contiene todo el "cerebro" de la Fase 1. La función principal es `process_chat`.

#### Detección de categoría con regex

```python
CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "restaurantes": ["restaurante", "restaurantes", "comer", "comida", "cafetería"],
    "transporte":   ["transporte", "metro", "bus", "gasolina", "taxi"],
    ...
}

def _detect_category(message: str) -> str | None:
    msg = message.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(re.search(r'\b' + re.escape(kw) + r'\b', msg) for kw in keywords):
            return category
    return None
```

**¿Por qué `\b` (word boundary)?**
Sin `\b`, "gas" matchearía dentro de "categorías" (subcadena). `\b` exige que el keyword esté en una frontera de palabra — precedido o seguido por un carácter no-palabra.

```
"categorías" → busca \bgas\b → NO match (g no está en frontera)
"gasolina"   → busca \bgas\b → NO match (gas está dentro de "gasolina")
"gas natural" → busca \bgas\b → SÍ match (gas es palabra completa)
```

`re.escape(kw)` escapa caracteres especiales en el keyword (como `.` o `?`) para que se traten como literales.

#### Detección de período temporal

```python
def _detect_period(message: str) -> tuple[datetime, datetime]:
    now = datetime.now()
    msg = message.lower()

    if "último mes" in msg or "mes pasado" in msg:
        first_day = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
        last_day = now.replace(day=1) - timedelta(days=1)
        return first_day, last_day
    if "últimos 3 meses" in msg or "trimestre" in msg:
        return now - timedelta(days=90), now

    return now.replace(day=1), now  # por defecto: mes actual
```

#### El árbol de decisión del chat

```python
def process_chat(db, message, user_id) -> ChatResponse:
    category = _detect_category(message)

    # 1. ¿Evolución mensual de una categoría?
    if category and any(w in msg for w in ["mensual", "por mes", "evolución"]):
        # → gráfico de línea
        ...

    # 2. ¿Cuánto gasté en X categoría?
    elif category:
        # → respuesta de texto
        ...

    # 3. ¿Saldo o resumen?
    elif any(w in msg for w in ["saldo", "balance", "resumen"]):
        # → gráfico de barras
        ...

    # 4. ¿Desglose por categorías?
    elif any(w in msg for w in ["categoría", "en qué gasto", "desglose"]):
        # → gráfico de tarta
        ...

    # 5. ¿Ingresos?
    elif any(w in msg for w in ["ingreso", "nómina", "salario"]):
        # → respuesta de texto
        ...

    # 6. No entendido
    else:
        return ChatResponse(response="No he entendido bien...")
```

**Limitación de este enfoque:** el orden importa mucho y los casos son rígidos. Esto es exactamente el problema que resuelve LangGraph en la Fase 2 — un LLM entiende la intención semántica en lugar de hacer matching de keywords.

---

## 8. Frontend — React + Vite

### ¿Qué es React?

React es una librería JavaScript para construir interfaces de usuario. Su modelo mental central es:

**UI = f(estado)**

La interfaz es una función pura del estado. Cuando el estado cambia, React re-renderiza los componentes afectados automáticamente.

### ¿Qué es Vite?

Vite es la herramienta de construcción (build tool). Reemplaza a Create React App. Es extremadamente rápido porque:
- En desarrollo, sirve los módulos ES directamente al navegador (sin bundle).
- Usa esbuild (escrito en Go) para transformar JSX/TypeScript.

### El punto de entrada: `src/main.jsx`

```jsx
import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
```

`ReactDOM.createRoot` monta la aplicación React dentro del `<div id="root">` del `index.html`. `StrictMode` activa advertencias adicionales en desarrollo.

### El componente raíz: `src/App.jsx`

```jsx
export default function App() {
  // Estado: datos del gráfico actual
  const [chart, setChart] = useState({ chartType: null, chartData: null, chartTitle: null })
  // Estado: resumen financiero (sidebar)
  const [summary, setSummary] = useState(null)
  const [accounts, setAccounts] = useState([])

  // useEffect: se ejecuta UNA VEZ al montar el componente
  useEffect(() => {
    getSummary().then(setSummary).catch(console.error)
    getAccounts().then(setAccounts).catch(console.error)
  }, [])  // ← array de dependencias vacío = solo al montar

  return (
    <div style={styles.root}>
      <aside style={styles.sidebar}>
        {/* Sidebar con stats y cuentas */}
        {summary && <StatCard label="Saldo total" value={`${summary.balance.toFixed(2)}€`} />}
      </aside>

      <main style={styles.main}>
        {/* Panel superior: gráfico */}
        <ChartPanel {...chart} />

        {/* Panel inferior: chat */}
        <ChatBox onChartData={setChart} />
        {/*              ↑ callback que ChatBox llama cuando hay datos de gráfico */}
      </main>
    </div>
  )
}
```

**Flujo de datos entre componentes:**
```
App (estado: chart)
├── ChartPanel ← recibe chart como props (solo lee)
└── ChatBox    ← recibe setChart como prop "onChartData" (puede modificar estado)
```

Este patrón se llama **"elevación de estado" (lifting state up)**. El estado vive en el ancestro común (`App`) y los hijos lo leen o modifican mediante props.

### `useState` y `useEffect` — los hooks fundamentales

**`useState`:**
```jsx
const [valor, setValor] = useState(valorInicial)
// valor    → el estado actual (solo lectura)
// setValor → función para actualizarlo (dispara re-render)
```

**`useEffect`:**
```jsx
useEffect(() => {
  // código que se ejecuta después del render
  fetchData().then(setData)

  return () => {
    // (opcional) cleanup: se ejecuta antes de desmontar o re-ejecutar
  }
}, [dep1, dep2])  // se re-ejecuta cuando dep1 o dep2 cambian
                  // [] = solo al montar
                  // sin array = en cada render
```

### El componente ChatBox: `src/components/ChatBox.jsx`

```jsx
export default function ChatBox({ onChartData }) {
  const [messages, setMessages] = useState([
    { role: 'assistant', text: 'Hola! Soy tu asistente financiero...' }
  ])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef(null)  // referencia al DOM para scroll automático

  // Scroll al último mensaje cuando cambia la lista
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  async function handleSend(text) {
    const message = text || input.trim()
    if (!message || loading) return

    // Añade el mensaje del usuario al historial
    setMessages(prev => [...prev, { role: 'user', text: message }])
    setInput('')
    setLoading(true)

    try {
      const data = await sendChatMessage(message)  // llamada al backend

      // Añade la respuesta del asistente
      setMessages(prev => [...prev, { role: 'assistant', text: data.response }])

      // Si hay datos de gráfico, notifica al padre (App)
      if (data.chart_type && data.chart_data) {
        onChartData({
          chartType: data.chart_type,
          chartData: data.chart_data,
          chartTitle: data.chart_title,
        })
      }
    } finally {
      setLoading(false)
    }
  }
  ...
}
```

**Puntos clave:**
- `setMessages(prev => [...prev, newMsg])` usa la forma funcional de `setState`. Esto es importante cuando el nuevo estado depende del anterior, para evitar condiciones de carrera.
- `useRef` accede directamente al nodo DOM sin disparar re-renders.

### Las llamadas a la API: `src/services/api.js`

```js
const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
//              ↑ variables de entorno de Vite (deben empezar por VITE_)

export async function sendChatMessage(message, userId = 1) {
  const res = await fetch(`${API_URL}/chat/`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, user_id: userId }),
  })
  if (!res.ok) throw new Error('Error en la respuesta del servidor')
  return res.json()
}
```

`fetch` es la API nativa del navegador para hacer peticiones HTTP. `async/await` convierte el código asíncrono (basado en Promesas) en algo que se lee de forma síncrona.

---

## 9. Visualización — Recharts

Recharts es una librería de gráficos para React basada en SVG y D3.

### Los tres tipos de gráfico: `src/components/ChartPanel.jsx`

#### Gráfico de barras (balance)

```jsx
<BarChart data={chartData} margin={{ top: 10, right: 20, left: 10, bottom: 5 }}>
  <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
  <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} />
  <YAxis tickFormatter={formatEur} tick={{ fill: '#94a3b8', fontSize: 11 }} />
  <Tooltip formatter={formatEur} contentStyle={styles.tooltip} />
  <Bar dataKey="value" fill="#6366f1" radius={[4, 4, 0, 0]} />
</BarChart>
```

**Estructura de datos esperada:**
```js
[
  { name: "Ingresos", value: 25507.37 },
  { name: "Gastos",   value: 22867.98 }
]
```

#### Gráfico de línea (evolución temporal)

```jsx
<LineChart data={chartData}>
  <Line type="monotone" dataKey="value" stroke="#6366f1" strokeWidth={2} />
</LineChart>
```

`type="monotone"` suaviza la curva entre puntos.

#### Gráfico de tarta (distribución)

```jsx
<PieChart>
  <Pie
    data={chartData}
    dataKey="value"
    nameKey="name"
    label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
  >
    {chartData.map((_, i) => (
      <Cell key={i} fill={COLORS[i % COLORS.length]} />
    ))}
  </Pie>
</PieChart>
```

`Cell` permite colorear cada sector individualmente. `i % COLORS.length` hace que los colores se repitan cíclicamente si hay más categorías que colores.

### `ResponsiveContainer`

```jsx
<ResponsiveContainer width="100%" height={280}>
  <BarChart ...>
    ...
  </BarChart>
</ResponsiveContainer>
```

`ResponsiveContainer` envuelve cualquier gráfico de Recharts y lo hace responsivo — se adapta al tamaño del contenedor padre en lugar de tener dimensiones fijas.

---

## 10. Flujo completo de una petición

Trazamos la petición: **"¿cuánto gasté en restaurantes este mes?"**

```
1. USUARIO escribe en el input y pulsa Enter

2. ChatBox.handleSend("¿cuánto gasté en restaurantes este mes?")
   ↓
   setMessages(prev => [...prev, { role: 'user', text: message }])  // muestra mensaje
   setLoading(true)

3. api.sendChatMessage(message)
   ↓
   fetch("http://localhost:8000/chat/", {
     method: "POST",
     body: JSON.stringify({ message: "¿cuánto gasté en restaurantes este mes?", user_id: 1 })
   })

4. FASTAPI recibe la petición en POST /chat/
   ↓
   Pydantic valida: { message: str, user_id: int } ✓
   Llama a: process_chat(db, message, user_id=1)

5. process_chat() en query_service.py
   ↓
   _detect_category("¿cuánto gasté en restaurantes este mes?")
   → busca \brestaurantes\b → encontrado → devuelve "restaurantes"
   
   _detect_period(message)
   → no detecta período especial → devuelve (primer día del mes, hoy)
   
   No detecta "mensual"/"evolución" → no es gráfico de línea
   Sí hay category → consulta SQL:
   
   SELECT SUM(amount)
   FROM transactions
   JOIN accounts ON transactions.account_id = accounts.id
   WHERE accounts.user_id = 1
     AND transactions.category = 'restaurantes'
     AND transactions.transaction_type = 'gasto'
     AND transactions.date >= '2026-07-01'
     AND transactions.date <= '2026-07-03'
   
   → total = 31.22

6. Devuelve ChatResponse:
   {
     "response": "Has gastado 31.22€ en restaurantes este mes.",
     "chart_type": null,
     "chart_data": null,
     "chart_title": null
   }

7. FastAPI serializa con Pydantic y devuelve JSON al navegador

8. ChatBox recibe la respuesta:
   ↓
   setMessages(prev => [...prev, { role: 'assistant', text: "Has gastado 31.22€..." }])
   // No hay chart_data → no llama a onChartData
   setLoading(false)

9. React re-renderiza: el nuevo mensaje aparece en el chat
```

---

## 11. Qué viene en la Fase 2 (LangGraph)

### El problema de la Fase 1

El keyword matching tiene límites claros:
- "¿Me puedes decir en qué he malgastado más?" → no lo entiende.
- "el mes pasado qué tal fueron mis ahorros?" → no lo entiende.
- Ambigüedades: "gas" → ¿categoría servicios o gasolina?

### La solución: LangGraph + LLM

LangGraph permite construir **flujos de trabajo con IA** como grafos dirigidos. Cada nodo es una función; las aristas son transiciones condicionadas.

El grafo que se construirá en `app/agent/graph.py`:

```
                 ┌─────────────────┐
   mensaje  ───► │  intent_parser  │
                 └────────┬────────┘
                          │ detecta: saldo / categoría / evolución / ...
                          ▼
                 ┌─────────────────┐
                 │  data_retriever │  ← ejecuta la consulta SQL correcta
                 └────────┬────────┘
                          │ datos crudos de la BD
                          ▼
                 ┌──────────────────────┐
                 │  response_formatter  │  ← genera respuesta natural + tipo gráfico
                 └──────────────────────┘
                          │
                          ▼
                   ChatResponse JSON
```

El nodo `intent_parser` usará **Claude API** para entender la intención del usuario en lenguaje natural, sin reglas manuales. El output del LLM será un objeto estructurado (gracias a structured outputs) que el siguiente nodo puede procesar directamente.

### Por qué esta arquitectura escala

- Puedes añadir nodos sin tocar los existentes (open/closed principle).
- Puedes enrutar condicionalmente: si la intención es una "transferencia", ir a un nodo distinto al de "consulta".
- El estado del grafo (el "contexto") fluye entre nodos, permitiendo conversaciones multi-turno.

---

## Resumen de tecnologías y sus roles

| Tecnología | Rol | Por qué esta elección |
|-----------|-----|----------------------|
| **FastAPI** | Framework de API | Async nativo, autodocs, validación integrada con Pydantic |
| **SQLAlchemy** | ORM | Abstracción de BD, evita SQL injection, migrations |
| **SQLite** | Base de datos | Sin servidor, archivo único, perfecto para desarrollo |
| **Pydantic** | Validación | Type hints como contratos, serialización automática |
| **React** | UI | Modelo declarativo, ecosistema maduro, composición de componentes |
| **Vite** | Build tool | 10-100x más rápido que Webpack, HMR instantáneo |
| **Recharts** | Gráficos | Componentes React nativos, basado en SVG, responsivo |
| **Docker** | Contenedores | Reproducibilidad, aislamiento de entorno, despliegue fácil |
| **docker-compose** | Orquestación | Multi-contenedor en un solo fichero, redes automáticas |

---

> **Consejo de estudio:** Lee cada archivo del proyecto en el orden de este documento. Para cada concepto, modifica algo pequeño y observa qué pasa. El mejor aprendizaje es romper cosas controladamente.
