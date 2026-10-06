# Operaciones que mueven dinero: el grafo de LangGraph

Cómo se ejecutan los Bizum y las compras de inversiones desde el chat y por qué el LLM ya no decide si se ejecutan.

---

## Índice

1. [El problema](#1-el-problema)
2. [La idea: el LLM propone, el código decide](#2-la-idea-el-llm-propone-el-código-decide)
3. [El grafo](#3-el-grafo)
4. [Los nodos uno a uno](#4-los-nodos-uno-a-uno)
5. [interrupt() y el checkpointer](#5-interrupt-y-el-checkpointer)
6. [La tabla pending_actions: auditoría e idempotencia](#6-la-tabla-pending_actions-auditoría-e-idempotencia)
7. [API: /chat/stream y /chat/actions/{id}](#7-api-chatstream-y-chatactionsid)
8. [Un Bizum de punta a punta](#8-un-bizum-de-punta-a-punta)
9. [Qué decide el LLM y qué decide el código](#9-qué-decide-el-llm-y-qué-decide-el-código)
10. [Tests](#10-tests)
11. [Archivos](#11-archivos)

---

## 1. El problema

Antes, el chat era un único bucle de tool calling con litellm. Las tools `make_bizum_transfer` y `add_investment` estaban en la lista de tools del modelo junto a las de consulta. La única barrera para que se ejecutaran sin permiso era una frase en el prompt: *"NO llames a make_bizum_transfer hasta recibir confirmación explícita"*.

En la práctica, eso dejaba estos agujeros:

| # | Problema | Consecuencia |
|---|---|---|
| 1 | La confirmación era solo una instrucción en el prompt | El modelo podía llamar a `make_bizum_transfer` directamente; nada en el código lo impedía |
| 2 | El modal "confirmaba" enviando el texto *"Sí, confirma el Bizum de X€ a Y"* como un mensaje de chat más | El LLM volvía a extraer los datos de ese texto (podían no coincidir con lo que mostraba el modal); cualquiera que escribiera esa frase, o un texto inyectado en los datos, podía disparar la operación |
| 3 | El `user_id` iba en el mensaje (`[user_id=N]`) y el modelo lo pasaba como argumento de cada tool | Un modelo confundido o un prompt injection podía leer u operar sobre la cuenta de otro usuario |
| 4 | Sin idempotencia | Un doble clic, un reintento o el propio bucle de 7 iteraciones podían ejecutar el Bizum dos veces |
| 5 | Cancelar solo cerraba el modal en el navegador | El backend nunca se enteraba de la cancelación |
| 6 | El `pending_action` del streaming se reenviaba sin validar | El frontend pintaba lo que el modelo escribiera en el JSON |
| 7 | En una inversión, el precio lo ponía el LLM y no se cargaba dinero en ninguna cuenta | Compras a precios inventados y "gratis" |
| 8 | Dos caminos de código (`_run_chat` y `process_chat_stream`) con el bucle copiado | Las correcciones había que hacerlas dos veces |

## 2. La idea: el LLM propone, el código decide

La regla del nuevo diseño: **ninguna operación que mueva dinero depende de lo que diga el LLM.**

- El modelo ya **no tiene ninguna tool que ejecute operaciones**. Solo tiene `propose_bizum` y `propose_investment`, que no tocan la base de datos: anotan la propuesta y cortan el bucle de tools.
- A partir de ahí manda el **grafo**: valida la propuesta con código determinista (límites, saldo, precio de mercado), la **para** hasta que el usuario pulse un botón y solo entonces la ejecuta, una única vez.
- La aprobación no es un mensaje de chat: es una petición `POST /chat/actions/{action_id}` asociada a una propuesta concreta, al usuario del JWT y con caducidad.

Para orquestar esto se usa [LangGraph](https://langchain-ai.github.io/langgraph/), que aporta exactamente las tres piezas necesarias: un flujo con ramas explícitas, la pausa a la espera de una persona (`interrupt()`) y la persistencia del estado mientras tanto (checkpointer).

> LangGraph se usa **sin los modelos de LangChain**. Los nodos llaman a `litellm` igual que antes, así que se mantiene el soporte multi-proveedor (Claude, Ollama, Groq, Gemini...).

## 3. El grafo

`backend/app/agent/graph.py`

```
START → agent ──(sin propuesta)──────────────────────────────→ respond → END
          │
          └─(propuesta)→ validate ─(no viable)───────────────→ respond
                            │
                         (viable)
                            ↓
                      await_approval   ← interrupt(): el grafo se para aquí
                            │
              ┌─(reject)────┴────(approve)─┐
              ↓                            ↓
           respond                      execute → respond
```

Toda pregunta pasa por el grafo, también las de solo lectura ("¿cuánto gasté en restaurantes?"). En esos casos el camino es simplemente `agent → respond`, que equivale a las dos fases de siempre (ver [agente-ia.md §5](agente-ia.md#5-el-agente-como-grafo-de-langgraph)).

### El estado

```python
class ChatState(TypedDict, total=False):
    user_id: int            # del JWT; el modelo nunca lo ve ni lo elige
    voice_mode: bool
    messages: list[dict]    # conversación en formato OpenAI/litellm
    proposal: dict | None   # propuesta en crudo del modelo
    action: dict | None     # propuesta validada por el servidor (+ action_id)
    error: str | None       # motivo por el que la propuesta no es viable
    decision: str | None    # approve | reject
    result: dict | None     # resultado de la ejecución
    final: dict | None      # respuesta final (texto + gráfico)
```

Cada nodo devuelve solo las claves que cambia; LangGraph las fusiona en el estado.

## 4. Los nodos uno a uno

### `agent` — Fase 1 (tools de lectura)

Llama a `run_tool_loop()` de `chat_agent.py`, el mismo bucle de tool calling de siempre con tres cambios:

1. **No hay tools de escritura.** `make_bizum_transfer` y `add_investment` ya no están en `TOOLS_SCHEMA` ni en `TOOL_MAP`. Si el modelo intenta llamarlas, recibe `tool not found`.
2. **Tools de propuesta.** `propose_bizum(recipient, amount, concept)` y `propose_investment(ticker, shares, investment_type)`. Cuando el modelo llama a una, el bucle guarda `{"type": "bizum" | "investment", ...args}` en `proposal` y termina. Solo se acepta una propuesta por mensaje.
3. **`user_id` inyectado por el servidor.** Ninguna tool lo expone en su schema. Al ejecutar una tool, el bucle descarta cualquier `user_id` que mande el modelo y pone el del estado:

```python
args = {k: v for k, v in args.items() if k in valid and k != "user_id"}
if "user_id" in valid:
    args["user_id"] = user_id   # sale del JWT, nunca del modelo
```

### `validate` — determinista, sin LLM

`actions.validate_proposal()` convierte la propuesta del modelo en el payload que verá el usuario y que, si lo aprueba, se ejecutará tal cual:

| Bizum | Inversión |
|---|---|
| Destinatario no vacío | Número de acciones > 0 |
| Importe > 0 y ≤ 2000 € | El ticker existe y cotiza (yfinance) |
| Existe cuenta corriente | **Precio de mercado** de yfinance (se ignora cualquier precio del modelo) |
| Saldo suficiente | Conversión a euros con el tipo de cambio `EUR{moneda}=X` |
| | Saldo suficiente para el **total en euros** |

- Si algo falla, lanza `OperationError`. El nodo guarda el motivo en `error` y el grafo salta a `respond`, donde el modelo se lo explica al usuario. No llega a aparecer ningún modal.
- Si todo está bien, crea la fila `pending_actions` en estado `pending` y guarda el payload en `action`, junto con el `action_id` (que es el `thread_id` del grafo).

### `await_approval` — la pausa

```python
def await_approval_node(state):
    decision = interrupt(pending_action_event(state["action"]))
    return {"decision": "approve" if decision == "approve" else "reject"}
```

`interrupt()` detiene el grafo. Su valor (el `pending_action` ya validado con Pydantic) es lo que recibe el frontend para pintar el modal. Ver [§5](#5-interrupt-y-el-checkpointer).

### `execute` — determinista e idempotente

`actions.execute(action_id)` lee el payload **de la base de datos** (no del modelo ni del cliente) y llama a:

- `execute_bizum()`: descuenta el importe de la cuenta corriente y registra la `Transaction` (categoría `bizum`) y el `BizumTransfer`.
- `execute_investment()`: carga el total en euros en la cuenta corriente, registra la `Transaction` (categoría `inversion`) y da de alta o actualiza la `Investment`, recalculando el precio medio.

Las dos funciones vuelven a comprobar el saldo, porque pudo cambiar entre la propuesta y la aprobación. Ninguna es una tool: el LLM no puede llamarlas. La idempotencia se explica en [§6](#6-la-tabla-pending_actions-auditoría-e-idempotencia).

### `respond` — Fase 2 (redacción)

La misma Fase 2 de siempre (`stream_response()`: texto en streaming + `---JSON---` + gráfico). La novedad es que, si hubo propuesta, el grafo le pasa al modelo **los hechos** como contexto, y el modelo solo los redacta:

| Situación | Contexto que recibe el modelo |
|---|---|
| Validación fallida | `[Sistema] La operación NO se ha realizado porque no pasa la validación: Saldo insuficiente...` |
| Usuario cancela | `[Sistema] El usuario ha cancelado la operación... No se ha movido dinero.` |
| Ejecutada | `[Sistema] ...se ha ejecutado. Resultado: {...}` con el resultado real |
| Falla al ejecutar | `[Sistema] ...ha fallado al ejecutarse: ... No se ha movido dinero.` |

Los tokens salen del nodo con `get_stream_writer()` (modo `stream_mode="custom"` de LangGraph), así que los eventos SSE que recibe el frontend tienen el mismo formato que antes.

## 5. interrupt() y el checkpointer

Una petición HTTP de chat no puede quedarse abierta esperando a que el usuario pulse un botón. Por eso el grafo se **para y se guarda**, y una segunda petición lo **reanuda**:

1. **Cada petición a `/chat/stream` es un thread nuevo**, con `thread_id = uuid4()`.
2. Al llegar a `interrupt()`, LangGraph guarda el estado completo (mensajes, propuesta validada...) en el **checkpointer** y `astream` emite un evento `__interrupt__`. El backend lo traduce en el `done` con `pending_action`, que incluye `action_id = thread_id`.
3. Cuando el usuario decide, `POST /chat/actions/{action_id}` reanuda **ese mismo thread** con `Command(resume=decision)`. `interrupt()` devuelve la decisión y el grafo sigue por `execute` o por `respond`.
4. Cuando un grafo termina sin interrupción, su thread se borra del checkpointer (`adelete_thread`) para no acumular estados.

El checkpointer es `AsyncSqliteSaver` (paquete `langgraph-checkpoint-sqlite`) sobre `data/checkpoints.sqlite`, en el mismo volumen Docker que la base de datos. Así un reinicio del backend no pierde las operaciones pendientes. Se abre en el `startup` de `main.py` (`init_graph()`) y se cierra en el `shutdown` (`close_graph()`). La ruta se configura con `CHECKPOINT_DB_PATH` (por defecto `./data/checkpoints.sqlite`).

> La decisión con la que se reanuda el grafo **no** es la que manda el cliente: `resume_chat_stream()` la lee de `pending_actions`. Solo una fila en estado `approved` lleva a `execute`.

## 6. La tabla pending_actions: auditoría e idempotencia

`PendingAction` (`backend/app/models/financial.py`, migración `7b1e4c2a9d10_pending_actions.py`):

| Columna | Contenido |
|---|---|
| `id` | `action_id` = `thread_id` del grafo (uuid) |
| `user_id` | Dueño de la operación |
| `action_type` | `bizum` \| `investment` |
| `payload` | JSON validado por el servidor (lo que vio el usuario y lo que se ejecuta) |
| `status` | `pending` → `approved` / `rejected` / `expired` → `executed` / `failed` |
| `result` | JSON con el resultado de la ejecución |
| `created_at`, `decided_at` | Para la caducidad y la auditoría |

Todas las transiciones son `UPDATE ... WHERE status = <estado anterior>`, y solo cuentan si afectan a exactamente una fila:

```python
# decide(): pending → approved | rejected
update(PendingAction).where(id == action_id, status == "pending").values(status=new_status)

# execute(): approved → executed, en la MISMA transacción que mueve el dinero
claimed = db.execute(
    update(PendingAction).where(id == action_id, status == "approved").values(status="executed")
).rowcount == 1
```

De aquí salen las garantías:

- **Una sola ejecución.** Dos aprobaciones simultáneas no pueden pasar las dos de `pending` a `approved`: la segunda recibe 409. Y aunque `execute()` se llamara dos veces, solo una reclama la fila. La otra devuelve el `result` guardado sin mover dinero.
- **Atomicidad.** El cambio a `executed` y el movimiento de dinero se confirman juntos con un único commit. Si la ejecución falla (por ejemplo, el saldo bajó entretanto), se hace rollback de ambos y la acción queda en `failed` con el motivo.
- **Caducidad.** Una propuesta caduca a los **5 minutos** (`ACTION_TTL` en `actions.py`). Aprobarla después devuelve 410 y la marca `expired`.
- **Auditoría.** Queda registrada cada propuesta, quién la decidió, cuándo y qué pasó.

## 7. API: /chat/stream y /chat/actions/{id}

### `POST /chat/stream`

Sin cambios por fuera. Cuando el agente propone una operación viable, no hay tokens de texto y el `done` lleva el `pending_action` validado:

```json
{"type": "done", "chart_type": null, "chart_data": null, "chart_title": null,
 "pending_action": {"type": "bizum_confirm", "action_id": "a5c93b0b-...",
                    "recipient": "Marta", "amount": 20.0, "concept": "Cena"}}
```

```json
{"type": "done", "pending_action": {"type": "investment_confirm", "action_id": "fd34a3f1-...",
  "ticker": "AAPL", "nombre": "Apple Inc.", "shares": 1.0,
  "price": 332.89, "currency": "USD", "total_eur": 295.97, "investment_type": "accion"}}
```

`price` y `total_eur` los calcula el servidor. El modal de inversión muestra el **total que se cargará en euros**.

### `POST /chat/actions/{action_id}` (nuevo)

Requiere JWT. Cuerpo:

```json
{"decision": "approve"}    // o "reject"
```

| Respuesta | Cuándo |
|---|---|
| `200` + SSE (`token`... `done`) | Decisión registrada. El agente responde con el resultado de la ejecución o confirma la cancelación |
| `404` | La acción no existe **o es de otro usuario** (no se distingue, para no filtrar ids) |
| `409` | La acción ya se decidió (doble clic, reintento) |
| `410` | La propuesta ha caducado (más de 5 minutos) |

Es la **única** vía para ejecutar una operación. Escribir "sí, confirma" en el chat solo genera una propuesta nueva con su propio modal.

### Frontend

`ChatBox.jsx` y `VoiceModal.jsx` llaman a `decideAction(action_id, 'approve' | 'reject')` (`services/api.js`) desde los botones del modal y pintan la respuesta con el mismo lector SSE (`readSSE`) que usa el chat.

## 8. Un Bizum de punta a punta

```
Usuario          Frontend                 Backend (FastAPI + grafo)                 BD
   │ "Bizum de 20€   │                              │                                   │
   │  a Marta"       │ POST /chat/stream ──────────►│ thread_id = uuid                  │
   │                 │                              │ agent: LLM → propose_bizum(...)   │
   │                 │                              │ validate: límite, saldo ─────────►│ lee cuenta
   │                 │                              │   crea pending_actions ──────────►│ status=pending
   │                 │                              │ await_approval: interrupt()       │
   │                 │                              │   (estado → checkpoints.sqlite)   │
   │                 │◄── done {pending_action} ────│                                   │
   │ ve el modal ◄───│                              │                                   │
   │                 │                              │                                   │
   │ pulsa Confirmar │ POST /chat/actions/{id} ────►│ decide(): pending → approved ────►│ UPDATE condicionado
   │                 │   {"decision":"approve"}     │ Command(resume) sobre thread_id   │
   │                 │                              │ execute: approved → executed      │
   │                 │                              │   + cargo + Transaction + Bizum ─►│ un solo commit
   │                 │                              │ respond: LLM redacta el resultado │
   │                 │◄── token, token... done ─────│ borra el thread del checkpointer  │
   │ "Bizum enviado  │                              │                                   │
   │  a Marta..." ◄──│                              │                                   │
```

Si el usuario pulsa **Cancelar**, el camino es el mismo con `"reject"`: `decide()` deja la fila en `rejected`, el grafo salta `execute` y `respond` confirma que no se ha movido dinero.

## 9. Qué decide el LLM y qué decide el código

| Decide el LLM | Decide el código |
|---|---|
| Entender que el usuario quiere hacer un Bizum o una compra | Si la operación es viable (límite, saldo, ticker) |
| Extraer destinatario, importe, concepto, ticker y número de acciones | El precio de compra y el coste en euros |
| Preguntar si falta algún dato | Sobre qué usuario se opera (JWT) |
| Redactar la respuesta final | Si se ejecuta (solo con aprobación explícita por `action_id`) |
| | Que se ejecute una única vez |

Si el LLM se equivoca extrayendo los datos (por ejemplo, entiende 200 € en vez de 20 €), el error es **visible**: el modal muestra exactamente lo que se ejecutará, y el usuario puede cancelar.

## 10. Tests

`backend/tests/test_action_graph.py` recorre el camino real (endpoints → grafo → `actions` → SQLite temporal) simulando solo el LLM y yfinance:

```bash
docker exec reto-unicaja-backend-1 python -m pytest tests -q
```

Qué cubren:

- Una propuesta para el grafo **sin tocar el saldo**.
- `approve` ejecuta exactamente una vez; un segundo `approve` da 409; `execute()` es idempotente por sí mismo.
- `reject` no mueve dinero.
- Otro usuario recibe 404; una acción caducada, 410.
- Saldo insuficiente o más de 2000 €: no hay interrupt ni modal.
- El LLM no puede llamar a `make_bizum_transfer`, y el `user_id` que mande se ignora.
- La inversión usa el precio de mercado (no el del LLM) y carga el total convertido a euros.
- Las preguntas de solo lectura siguen respondiendo en streaming.

## 11. Archivos

| Archivo | Responsabilidad |
|---|---|
| `backend/app/agent/graph.py` | Estado, nodos, aristas, checkpointer, `process_chat_stream` / `resume_chat_stream` / `process_chat` |
| `backend/app/agent/actions.py` | Validación, ciclo de vida de `PendingAction`, ejecución idempotente |
| `backend/app/agent/chat_agent.py` | Prompts, schemas de tools (con `propose_*`), `run_tool_loop` (Fase 1), `stream_response` (Fase 2) |
| `backend/app/agent/financial_mcp.py` | `execute_bizum`, `execute_investment`, `get_market_quote`, `get_eur_rate` (no son tools) |
| `backend/app/api/routes/chat.py` | `POST /chat/actions/{action_id}` |
| `backend/app/models/financial.py` + `alembic/versions/7b1e4c2a9d10_pending_actions.py` | Tabla `pending_actions` |
| `frontend/src/services/api.js` | `readSSE`, `decideAction` |
| `frontend/src/components/{ChatBox,VoiceModal,InvestmentConfirmModal}.jsx` | Modales que aprueban o rechazan por `action_id` |
