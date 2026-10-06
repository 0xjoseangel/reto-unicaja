# Autenticación JWT — Habla con tu dinero

Documentación técnica del sistema de autenticación multi-usuario implementado en la Fase 2 del roadmap.

---

## Índice

1. [Visión general](#1-visión-general)
2. [Flujo de autenticación](#2-flujo-de-autenticación)
3. [Backend — estructura y decisiones](#3-backend--estructura-y-decisiones)
4. [Frontend — AuthContext y fetch autenticado](#4-frontend--authcontext-y-fetch-autenticado)
5. [Endpoints de la API](#5-endpoints-de-la-api)
6. [Seguridad y consideraciones](#6-seguridad-y-consideraciones)
7. [Añadir un usuario nuevo](#7-añadir-un-usuario-nuevo)

---

## 1. Visión general

Antes de esta fase, `user_id=1` estaba hardcodeado en todos los endpoints y en el frontend. Cualquier petición accedía a los datos del mismo usuario. Esto es suficiente para una demo en local, pero hace inviable el multi-usuario y es lo primero que un evaluador técnico detecta.

Con JWT (JSON Web Tokens) el flujo es:

```
Usuario introduce email + password
    │  POST /auth/login
    ▼
Backend verifica credenciales contra la BD
    │  → genera token firmado: { sub: "1", exp: ... }
    ▼
Frontend guarda el token en localStorage
    │  Authorization: Bearer eyJhbGci...
    ▼
Cada petición al backend lleva el token en la cabecera
    │  FastAPI extrae user_id del token
    ▼
Todos los endpoints usan el user_id del token, no un parámetro manual
```

El token dura **7 días**. No hay refresh token — para un proyecto de demostración es suficiente y simplifica el código considerablemente.

---

## 2. Flujo de autenticación

### Login

```
POST /auth/login
Body: { "email": "...", "password": "..." }

→ 200: { "access_token": "...", "token_type": "bearer", "user_id": 1, "name": "..." }
→ 401: { "detail": "Email o contraseña incorrectos." }
```

### Registro

```
POST /auth/register
Body: { "name": "...", "email": "...", "password": "..." }

→ 201: { "access_token": "...", "token_type": "bearer", "user_id": 2, "name": "..." }
→ 409: { "detail": "Ya existe una cuenta con ese email." }
```

### Petición protegida

```
GET /transactions/summary
Header: Authorization: Bearer eyJhbGci...

→ 200: { "balance": ..., "total_income": ..., ... }
→ 401: { "detail": "Not authenticated" }         ← sin token
→ 401: { "detail": "Token inválido o expirado" } ← token mal formado o caducado
```

---

## 3. Backend — estructura y decisiones

### Archivos nuevos

```
backend/app/
├── core/
│   ├── security.py      ← hash/verify de contraseñas, creación/decodificación de JWT
│   └── dependencies.py  ← dependencia FastAPI: extrae user_id del token
├── schemas/
│   └── auth.py          ← RegisterRequest, LoginRequest, TokenResponse
└── api/routes/
    └── auth.py          ← /auth/register, /auth/login, /auth/me
```

### `security.py` — hashing y JWT

El proyecto usa `bcrypt` directamente (sin `passlib`) para evitar incompatibilidades con Python 3.12:

```python
import bcrypt
from jose import jwt

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())

def create_access_token(user_id: int) -> str:
    expire = datetime.utcnow() + timedelta(days=settings.jwt_expire_days)
    payload = {"sub": str(user_id), "exp": expire}
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)
```

El `SECRET_KEY` vive en `Settings` y se puede sobreescribir con la variable de entorno `JWT_SECRET_KEY`. En producción nunca debe ser el valor por defecto.

### `dependencies.py` — extracción del user_id

FastAPI usa el sistema de inyección de dependencias (`Depends`). La dependencia `get_current_user` se añade a cada endpoint protegido:

```python
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

async def get_current_user(token: str = Depends(oauth2_scheme)) -> int:
    user_id = decode_token(token)
    if user_id is None:
        raise HTTPException(status_code=401, ...)
    return user_id
```

Cuando FastAPI ve `Depends(oauth2_scheme)`, extrae automáticamente el valor de la cabecera `Authorization: Bearer <token>`. Esto también hace que los endpoints aparezcan como protegidos en `/docs`.

### Cambios en rutas existentes

**Antes (hardcodeado):**
```python
@router.get("/summary")
async def summary(user_id: int = 1, db: Session = Depends(get_db)):
    ...
```

**Después (autenticado):**
```python
@router.get("/summary")
async def summary(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ...
```

El cambio es idéntico en los tres endpoints de `/transactions/` y en los dos de `/chat/`. El `user_id` del body de `ChatRequest` se eliminó; ahora llega exclusivamente del token.

En el chat, el `user_id` del token llega también a las tools del agente, pero **nunca pasa por el modelo**. Ninguna tool lo expone en su schema, el mensaje del usuario no lo incluye, y el bucle de tools (`_call_tool` en `chat_agent.py`) descarta cualquier `user_id` que mande el modelo e inyecta el del token. Así, un prompt injection no puede hacer que el agente lea u opere sobre la cuenta de otro usuario. El endpoint `POST /chat/actions/{id}`, que aprueba Bizum e inversiones, comprueba además que la operación pertenece al usuario del token (si no, devuelve 404). Ver [acciones-langgraph.md](acciones-langgraph.md).

---

## 4. Frontend — AuthContext y fetch autenticado

### AuthContext

El estado de autenticación se gestiona con React Context para evitar prop drilling:

```jsx
// src/context/AuthContext.jsx
const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [token, setToken] = useState(() => localStorage.getItem('token'))
  const [user, setUser] = useState(() => JSON.parse(localStorage.getItem('user')))

  function login(tokenResponse) {
    localStorage.setItem('token', tokenResponse.access_token)
    localStorage.setItem('user', JSON.stringify({ id: tokenResponse.user_id, name: tokenResponse.name }))
    setToken(...)
    setUser(...)
  }

  function logout() {
    localStorage.removeItem('token')
    localStorage.removeItem('user')
    setToken(null)
    setUser(null)
  }

  return <AuthContext.Provider value={{ token, user, login, logout }}>{children}</AuthContext.Provider>
}
```

El token se inicializa desde `localStorage` al montar el provider. Así el usuario sigue autenticado tras recargar la página (mientras el token no haya caducado).

### apiFetch — fetch autenticado centralizado

En lugar de llamar a `fetch` directamente en cada componente, todos los componentes usan `apiFetch` de `src/services/api.js`:

```js
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
```

Esto garantiza que el header `Authorization` siempre está presente sin tener que modificar cada `fetch` por separado.

### App.jsx — renderizado condicional

```jsx
export default function App() {
  const { token, user, logout } = useAuth()

  if (!token) return <LoginPage />   // ← muestra login si no hay sesión

  return (
    <div>
      <header>
        ...
        <span>{user.name}</span>
        <button onClick={logout}>Salir</button>
      </header>
      <ChatBox />
    </div>
  )
}
```

No se usa `react-router-dom` en esta fase. El renderizado condicional es suficiente y evita añadir una dependencia innecesaria. Cuando se implemente el dashboard (Fase 4) se añadirá el router para gestionar `/` y `/chat`.

---

## 5. Endpoints de la API

| Método | Ruta | Auth | Descripción |
|--------|------|------|-------------|
| POST | `/auth/register` | No | Crea cuenta nueva |
| POST | `/auth/login` | No | Obtiene token |
| GET | `/auth/me` | Sí | Datos del usuario actual |
| GET | `/transactions/` | Sí | Lista de transacciones |
| GET | `/transactions/summary` | Sí | Resumen financiero |
| GET | `/transactions/accounts` | Sí | Cuentas del usuario |
| POST | `/chat/` | Sí | Chat (respuesta completa) |
| POST | `/chat/stream` | Sí | Chat (streaming SSE) |
| POST | `/voice/transcribe` | No | Transcripción de audio |
| POST | `/voice/synthesize` | No | Síntesis de voz |

Los endpoints de voz no están protegidos porque son stateless (no acceden a datos del usuario).

---

## 6. Seguridad y consideraciones

### Fortalezas de la implementación actual

- **Contraseñas con bcrypt**: coste de cómputo deliberadamente alto, resistente a ataques de fuerza bruta
- **JWT firmado con HS256**: cualquier token manipulado es rechazado
- **No se almacena el token en el servidor**: la verificación es stateless, escala sin estado compartido
- **Password nunca viaja tras el login**: solo el hash vive en la BD

### Limitaciones conocidas (aceptables para una demo)

- **Token en localStorage**: vulnerable a XSS si hubiera scripts maliciosos inyectados. La alternativa más segura son cookies `HttpOnly`, pero requieren CORS más complejo. Para este proyecto sin datos reales, localStorage es aceptable.
- **Sin refresh token**: el usuario debe volver a hacer login cada 7 días. Añadir refresh tokens en el futuro es trivial con el sistema actual.
- **`JWT_SECRET_KEY` en código**: el valor por defecto `"dev-secret-change-in-production"` es inseguro. En despliegue real, debe venir de una variable de entorno.

---

## 7. Añadir un usuario nuevo

### Desde la interfaz

Usar la pantalla de login, pestaña "Crear cuenta". El usuario nuevo empieza sin datos financieros.

### Desde la CLI (para testing)

```bash
curl -X POST http://localhost:8000/auth/register \
  -H "Content-Type: application/json" \
  -d '{"name": "Nombre", "email": "email@ejemplo.com", "password": "mipassword"}'
```

### Usuario demo preexistente

El `seed.py` crea automáticamente el usuario de demo con las credenciales:

| Campo | Valor |
|-------|-------|
| Email | `joseangelcarretero300@gmail.com` |
| Password | `demo1234` |

La pantalla de login tiene un botón "Rellenar" que autocompleta estos datos.
