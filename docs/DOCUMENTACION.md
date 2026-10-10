# Visión general y arranque — "Habla con tu dinero"

Asistente financiero conversacional para el reto Cátedra Unicaja · Universidad de Granada.
Autor: Jose Angel Carretero Montes.

Este documento es el capítulo 1 del [libro de documentación](README.md): una introducción
de alto nivel y las instrucciones para arrancar el proyecto. El resto de capítulos del
índice cubren cada subsistema en profundidad (modelo de datos, agente de IA, grafo de
LangGraph, dashboard, memoria, voz...).

---

## Índice

1. [Visión general](#1-visión-general)
2. [Cómo arrancarlo](#2-cómo-arrancarlo)
3. [Flujo completo de una petición](#3-flujo-completo-de-una-petición)
4. [Resumen tecnológico](#4-resumen-tecnológico)

---

## 1. Visión general

El usuario escribe en lenguaje natural ("¿cuánto gasté en restaurantes este mes?", "manda
30€ a María") y la app:

1. Envía el mensaje al backend (autenticado con JWT) junto con el historial de conversación.
2. Un agente de IA, orquestado con **LangGraph** sobre **litellm** (Claude por defecto;
   también soporta Gemini, Groq, Mistral u Ollama local), decide qué herramientas de
   consulta usar mediante **tool calling** — ver [agente-ia.md](agente-ia.md).
3. Si la petición implica mover dinero (Bizum, inversión), el modelo solo puede
   *proponer* la operación; el servidor la valida con código determinista y el usuario
   la aprueba en un modal antes de que se ejecute — ver
   [acciones-langgraph.md](acciones-langgraph.md).
4. El frontend muestra la respuesta en streaming y, si procede, un gráfico dinámico
   (Recharts).

Alrededor de ese núcleo hay cuatro piezas más: un **dashboard proactivo** que genera
tarjetas con IA cada noche ([dashboard-proactivo.md](dashboard-proactivo.md)), una
**memoria de usuario** que extrae hechos de conversaciones pasadas para personalizar
futuras respuestas ([memoria-usuario.md](memoria-usuario.md)), un **modo voz** con
Whisper y Piper ([voz.md](voz.md)), y un **historial de conversaciones** navegable desde
el frontend.

---

## 2. Cómo arrancarlo

La forma recomendada es Docker Compose — ver [DOCKER.md](DOCKER.md) para el detalle
completo. Resumen:

```bash
cp backend/.env.example backend/.env   # y rellenar al menos una API key (ver config.py)
docker compose up --build
docker compose exec backend python seed.py   # usuarios y datos de prueba
```

- Frontend: http://localhost:3000
- Backend: http://localhost:8000 (docs interactivas en `/docs`)

Usuarios de prueba y qué probar con cada uno: [usuarios-prueba.md](usuarios-prueba.md).

### Sin Docker (desarrollo local)

```bash
# Backend
cd backend
uv venv --python 3.12 .venv && source .venv/bin/activate
uv pip install -r requirements.txt
alembic upgrade head
python seed.py
uvicorn app.main:app --reload --port 8000

# Frontend (en otra terminal)
cd frontend
npm install
npm run dev      # http://localhost:3000
```

---

## 3. Flujo completo de una petición

Siguiendo "Manda un Bizum de 50€ a Carlos" de principio a fin:

```
1. FRONTEND
   ChatBox.jsx: handleSend("Manda un Bizum de 50€ a Carlos")
   → history = [{role:"user", content:"Manda un Bizum de 50€ a Carlos"}]
   → api.js: POST /chat/stream con {message, history} + JWT

2. BACKEND — ruta
   chat.py: recibe ChatRequest; user_id sale del JWT (get_current_user)
   → process_chat_stream(message, user_id, history)

3. BACKEND — grafo (graph.py)
   Estado inicial: messages = [system: SYSTEM_PROMPT (+ memoria si hay), user: "Manda un Bizum..."]
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
    → graph.py::_save_message persiste el turno en la tabla Conversation

12. FRONTEND
    ChatBox muestra la confirmación del Bizum
```

Detalle completo del grafo (nodos, aristas, checkpointer, idempotencia):
[acciones-langgraph.md](acciones-langgraph.md).

---

## 4. Resumen tecnológico

| Capa | Tecnología | Por qué |
|---|---|---|
| API | FastAPI | Asíncrono, validación automática, docs interactivas en `/docs` |
| Validación | Pydantic v2 | Contratos de datos entre capas |
| ORM | SQLAlchemy 2.0 | Abstracción SQL tipada |
| Base de datos | SQLite | Sin servidor, fichero único, perfecto para desarrollo y demos |
| Autenticación | JWT (`python-jose`/bcrypt) | Stateless, cada request lleva su propio `user_id` verificado |
| IA | litellm + Claude (Anthropic) | Proveedor configurable sin cambiar código; Claude por defecto |
| Orquestación | LangGraph | Grafo con aprobación humana (`interrupt`) y estado persistido para las operaciones que mueven dinero |
| Memoria | litellm embeddings + similitud coseno | RAG casero sin dependencias de BD vectorial |
| Voz | faster-whisper + Piper | Transcripción y síntesis de voz locales, sin servicios externos |
| Frontend | React + Vite | Componentes reactivos, hot reload, proxy integrado |
| Gráficos | Recharts | Librería de gráficos para React, simple y flexible |
| Contenedores | Docker Compose | Un solo comando para levantar todo el stack |
