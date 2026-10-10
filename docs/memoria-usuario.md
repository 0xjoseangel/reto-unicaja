# Memoria de usuario (RAG casero sobre el historial de chat)

Documentación técnica de la persistencia de conversaciones y la memoria de usuario:
un pipeline que guarda el historial de chat, extrae de él hechos y preferencias con
el LLM, y los recupera por similitud para personalizar las respuestas del chat.

---

## Índice

1. [Por qué existe esto](#1-por-qué-existe-esto)
2. [Vista de conjunto del pipeline](#2-vista-de-conjunto-del-pipeline)
3. [Backend paso a paso](#3-backend-paso-a-paso)
4. [Decisiones de diseño y su porqué](#4-decisiones-de-diseño-y-su-porqué)
5. [Cómo probarlo](#5-cómo-probarlo)
6. [Archivos](#6-archivos)

---

## 1. Por qué existe esto

El esquema de BD tiene, desde la primera migración (`92f98a144664_initial_schema.py`),
dos tablas pensadas exactamente para esto y que nunca se habían usado:
`Conversation` (un turno de chat: `user_id`, `role`, `content`) y
`UserProfileVector` (un chunk de texto con su `embedding` serializado como JSON).
Hasta ahora el chat era completamente efímero: solo vivía en el estado de React y,
mientras duraba una operación pendiente de aprobación, en el checkpointer SQLite de
LangGraph.

Esta funcionalidad cierra ese círculo con un **RAG casero** (sin librería de
vectores, sin base de datos vectorial): se guarda cada turno, un job nocturno le
pide al LLM que extraiga frases cortas de hechos/preferencias del usuario, se
embeben con `litellm.embedding` y se recuperan por similitud coseno (calculada en
Python puro) antes de cada pregunta nueva del chat, para inyectarlas en el prompt.

## 2. Vista de conjunto del pipeline

```
Cada petición de chat nueva                    Cada turno que termina (no interrumpido)
        │                                                    │
        ▼                                                    ▼
_save_message(user_id, "user", message)        _save_message(user_id, "assistant", texto_final)
        │                                                    │
        └──────────────────────┬─────────────────────────────┘
                                ▼
                        tabla `conversations`

                  ── por separado, una vez al día ──

              APScheduler (23:00, una hora después del dashboard)
                                │
                                ▼
                _extract_memories_for_all_users()
                                │
                                ▼
              extract_and_store_memories(user_id)
                                │
                  ┌─────────────┴──────────────┐
                  │ 1. Últimas 20 Conversation   │
                  │ 2. LLM extrae hechos cortos  │  ← EXTRACTION_PROMPT
                  │ 3. litellm.embedding por hecho│
                  │ 4. UserProfileVector nuevo    │
                  └──────────────────────────────┘

                  ── antes de cada pregunta nueva del chat ──

                   graph.py::_initial_state()
                                │
                                ▼
                  _build_system_prompt(user_id, message)
                                │
                                ▼
                 retrieve_relevant_memories(user_id, message)
                                │
                  ┌─────────────┴──────────────┐
                  │ embed(message)               │
                  │ cosine_similarity contra      │
                  │ todos los UserProfileVector   │
                  │ del usuario → top 2-3         │
                  └─────────────┬──────────────┘
                                ▼
          "Lo que sabes de este usuario:\n- ...\n\n" + SYSTEM_PROMPT
```

## 3. Backend paso a paso

### 3.1. Persistencia en `graph.py`

`_run()` (el único punto por el que pasan `process_chat`, `process_chat_stream` y
`resume_chat_stream`) ya distinguía "terminó de verdad" (`not interrupted`, borra el
thread del checkpointer) de "se quedó esperando aprobación" (`interrupted`). Se
reutiliza esa misma condición: `_run` acumula el texto de los eventos `token` y, si
no hubo interrupción, llama a `_save_message(user_id, "assistant", texto)`.

El mensaje del **usuario** se guarda aparte, en `process_chat`/`process_chat_stream`,
porque solo existe una vez por petición nueva — el resume no trae mensaje nuevo,
solo una decisión approve/reject. `resume_chat_stream` obtiene el `user_id` del
snapshot del checkpointer que ya consulta (`graph.aget_state(cfg)`), sin ninguna
consulta adicional.

Si el grafo se interrumpe esperando aprobación, no se persiste nada del asistente en
ese momento (no hay texto final). Cuando el usuario decide, `resume_chat_stream`
vuelve a pasar por `_run` con el mismo `thread_id`; esta vez no se interrumpe, así
que persiste automáticamente el texto de confirmación/cancelación — sin código
especial para el caso resume.

`_save_message` falla en silencio (con `logger.exception`) si la BD da un error: un
problema de persistencia nunca debe tumbar una respuesta de chat ya generada.

### 3.2. `memory_agent.py` — embeddings, extracción, similitud

Reutiliza `_build_model()`/`_is_claude()` de `chat_agent.py` sin modificarlo (mismo
import que ya hace `dashboard_agent.py`):

- **`_embed(text)`** — llama a `_build_model()` solo por su efecto secundario (deja
  `GEMINI_API_KEY` en el entorno) y después `litellm.embedding(model="gemini/text-
  embedding-004", input=text)`.
- **`_cosine_similarity(a, b)`** — Python puro, sin numpy; protegida contra división
  por cero si algún vector es todo ceros.
- **`retrieve_relevant_memories(user_id, query, top_k=3)`** — embebe `query`, trae
  todos los `UserProfileVector` del usuario, los ordena por similitud y devuelve los
  `top_k` `chunk_text`. Devuelve `[]` si no hay memorias o si falla el embedding
  (nunca debe tumbar un turno de chat).
- **`_extract_facts(conversation_text)`** — una llamada a `litellm.completion` con
  `EXTRACTION_PROMPT`, pidiendo `{"facts": [...]}`; JSON malformado o con tipos
  inesperados se filtra, nunca revienta.
- **`extract_and_store_memories(user_id, lookback=20)`** — job por usuario: lee las
  últimas 20 `Conversation`, extrae hechos, embebe cada uno y los guarda como
  `UserProfileVector(source="conversation")`.

### 3.3. Scheduler

`scheduler.py` registra `_extract_memories_for_all_users` a las 23:00 (una hora
después del job del dashboard, para no competir por el mismo rato), con el mismo
patrón de los jobs existentes: recorre todos los `user_id`, llama al job por
usuario dentro de un `try/except` + `logger.exception` para que el fallo de un
usuario no pare el resto del batch.

### 3.4. Inyección en el prompt del chat

`graph.py::_build_system_prompt(user_id, message)` llama a
`retrieve_relevant_memories` y, si devuelve algo, antepone un bloque
`"Lo que sabes de este usuario:\n- ..."` al `SYSTEM_PROMPT`. Se usa en
`_initial_state()`, que es el único lugar donde se construye el mensaje de sistema
para una pregunta *nueva* — el resume no pasa por aquí, reanuda el estado ya fijado
en el checkpointer.

## 4. Decisiones de diseño y su porqué

- **Hechos extraídos por LLM, no turnos crudos.** Guardar el texto literal de cada
  mensaje como memoria mezclaría ruido conversacional con la señal útil. Pedirle al
  LLM que resuma en frases cortas de hechos/preferencias da chunks más densos y más
  útiles para inyectar en un prompt corto.
- **Similitud coseno en Python puro, no una librería vectorial.** El dataset de este
  proyecto (unos pocos usuarios, decenas de chunks cada uno) es minúsculo — una
  dependencia de BD vectorial sería sobre-ingeniería para el tamaño real del
  problema.
- **Memoria solo en el chat, nunca en el dashboard.** El dashboard ya recopila su
  propio contexto directo de las tablas financieras (`_gather_context` en
  `dashboard_agent.py`); no necesita "lo que el usuario dijo en el chat" para decidir
  qué tarjetas mostrar.
- **Sin deduplicación ni límite de crecimiento de `UserProfileVector`.** Fuera de
  alcance por tiempo de hackathon — el coste de tener algún chunk repetido es solo
  "un poco de redundancia en el prompt", no un bug. Limitación conocida.
- **`lookback=20` sin estado de "hasta dónde se procesó".** Más simple que mantener
  una tabla de progreso; a cambio puede re-extraer hechos ya vistos con el tiempo.
  Decisión consciente, aceptable para la escala de este proyecto.
- **Sin endpoint `/memory/refresh`.** La memoria no se "ve" directamente como el
  dashboard — no hace falta forzarla en directo para la demo. Si se necesita, se
  llama a `extract_and_store_memories(user_id)` desde una shell de Python.

## 5. Cómo probarlo

```bash
# Tests (mockean litellm.completion y litellm.embedding, sin red real)
cd backend && .venv/bin/pytest tests/test_memory_agent.py tests/test_graph_memory.py -v

# Suite completa, para confirmar que no rompe nada existente
.venv/bin/pytest tests/ -v

# Prueba manual end-to-end con el backend arrancado:
# 1. Mandar varios mensajes de chat (p.ej. "prefiero ahorrar antes que invertir")
# 2. Forzar el job de extracción manualmente:
.venv/bin/python -c "
from app.agent.memory_agent import extract_and_store_memories
print(extract_and_store_memories(user_id=1))
"
# 3. Comprobar la tabla:
sqlite3 data/db.sqlite3 "select chunk_text, source from user_profile_vectors where user_id=1;"
# 4. Volver a preguntar algo relacionado en el chat y comprobar que la respuesta
#    tiene en cuenta esa preferencia (aunque no se cite literalmente).
```

## 6. Archivos

| Archivo | Responsabilidad |
|---|---|
| `backend/app/agent/memory_agent.py` | Embeddings, extracción de hechos, similitud coseno, job por usuario. |
| `backend/app/agent/graph.py` | Persistencia de `Conversation` (`_save_message`, `_run`) e inyección de memoria (`_build_system_prompt`, `_initial_state`). |
| `backend/app/core/scheduler.py` | Job nocturno `_extract_memories_for_all_users`, registrado a las 23:00. |
| `backend/app/core/config.py` | Campo `embedding_model` (`"gemini/text-embedding-004"` por defecto). |
| `backend/tests/test_memory_agent.py` | Tests de `memory_agent.py`, todo mockeado. |
| `backend/tests/test_graph_memory.py` | Test de `_build_system_prompt`. |
