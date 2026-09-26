# Dashboard proactivo generativo + voz flotante

Documentación técnica de la funcionalidad implementada para el punto 4 del `ROADMAP.md`,
con el pivote real explicado en detalle: no es un dashboard fijo con los mismos widgets
para todos, sino uno donde **la IA decide qué mostrarle a cada usuario**.

---

## Índice

1. [Por qué existe esto y qué pivote se hizo](#1-por-qué-existe-esto-y-qué-pivote-se-hizo)
2. [Vista de conjunto del pipeline](#2-vista-de-conjunto-del-pipeline)
3. [Backend paso a paso](#3-backend-paso-a-paso)
4. [Frontend paso a paso](#4-frontend-paso-a-paso)
5. [Decisiones de diseño y su porqué](#5-decisiones-de-diseño-y-su-porqué)
6. [Cómo probarlo](#6-cómo-probarlo)

---

## 1. Por qué existe esto y qué pivote se hizo

El `ROADMAP.md` original (punto 4) proponía un dashboard con alertas: un job nocturno
detecta anomalías y las guarda en la tabla `alerts`, y una página `/dashboard` las lista
junto a un resumen financiero fijo (saldo, gastos del mes, gráfica de categorías).

Lo que se ha construido va un paso más allá de esa idea original:

- **No hay un layout fijo de widgets.** El propio LLM decide, en cada generación, cuántas
  tarjetas mostrar, de qué tipo, con qué severidad y con qué formato (texto, gráfico o
  dato destacado). Dos usuarios con situaciones financieras distintas verán conjuntos de
  tarjetas completamente distintos.
- **El dashboard es la pantalla principal**, no una página secundaria. El chat de texto
  convencional pasa a ser la pestaña "Chat", accesible pero no la puerta de entrada.
- **La voz es un widget flotante persistente**, no un modal que solo vive dentro del chat.
  Está disponible tanto en el dashboard como en el chat, y "sabe" desde dónde se ha abierto
  para dar contexto a la conversación.

## 2. Vista de conjunto del pipeline

```
APScheduler (22:00 cada noche)          POST /dashboard/refresh (botón "Actualizar ahora")
        │                                              │
        └──────────────────┬───────────────────────────┘
                            ▼
              generate_dashboard_cards(user_id)
                            │
              ┌─────────────┴──────────────┐
              │  1. Recopilar datos         │  ← llamadas Python DIRECTAS a financial_mcp.py
              │     (sin tool-calling)      │    (get_financial_summary, get_category_breakdown,
              │                             │     get_spending_analysis, get_portfolio,
              │                             │     get_portfolio_news, metas activas)
              └─────────────┬──────────────┘
                            ▼
              ┌─────────────────────────────┐
              │  2. UNA llamada al LLM       │  ← DASHBOARD_PROMPT + todo el contexto recopilado
              │     (litellm.completion)    │    el modelo decide qué tarjetas generar
              └─────────────┬──────────────┘
                            ▼
              ┌─────────────────────────────┐
              │  3. Validación Pydantic      │  ← AlertCardIn por tarjeta; una tarjeta
              │     tolerante                │    inválida se descarta sin tumbar el batch
              └─────────────┬──────────────┘
                            ▼
              ┌─────────────────────────────┐
              │  4. Persistencia             │  ← Alert(...) por tarjeta válida en SQLite
              └─────────────┬──────────────┘
                            ▼
                    GET /dashboard/
                            │
                            ▼
                  DashboardPage.jsx (React)
                    grid de tarjetas
                            │
                     click en tarjeta
                            │
                            ▼
          view → 'chat' + initialPrompt = card.cta_prompt
                            │
                            ▼
                  ChatBox envía el prompt
                  automáticamente (contexto
                  de la tarjeta precargado)

                  ── en paralelo, desde cualquier pestaña ──

              botón flotante de voz (App.jsx)
                            │
                            ▼
      ¿view === 'dashboard'? → antepone un mensaje de
      contexto sintético ("Contexto visible: estoy
      mirando mi dashboard...") al history real
                            │
                            ▼
                     <VoiceModal history=... />
                  (sin cambios internos — solo
                   se compone el history que recibe)
```

## 3. Backend paso a paso

### 3.1. Modelo `Alert` ampliado

`backend/app/models/financial.py` — la tabla `alerts` ya existía (tipo, título, cuerpo,
severidad, vista/no vista). Se le añadieron los campos que necesita una tarjeta
**generativa** en vez de solo texto:

| Campo         | Tipo            | Para qué sirve                                          |
|---------------|-----------------|-----------------------------------------------------------|
| `card_type`   | `text\|chart\|stat` | Cómo debe renderizarse en el grid                     |
| `chart_type`  | `bar\|line\|pie\|null` | Reutiliza el mismo esquema que ya usa el chat        |
| `chart_data`  | `TEXT` (JSON)   | Serializado como string, igual que en el chat streaming |
| `chart_title` | `string\|null`  | Título del gráfico                                       |
| `cta_prompt`  | `string\|null`  | Pregunta sugerida — se precarga en el chat al hacer click |

Migración: `alembic/versions/33cc8ee0199d_alert_cards.py` (generada con
`alembic revision --autogenerate` y revisada a mano — se le añadió `server_default='text'`
a `card_type` porque, al ser `NOT NULL`, SQLite necesita un valor por defecto para
rellenar filas ya existentes en la tabla al aplicar el `ALTER`).

### 3.2. Nueva tool: `get_portfolio_news`

`backend/app/agent/financial_mcp.py`, junto a `get_asset_details`/`get_market_overview`.
Recorre los tickers de la cartera del usuario (`get_portfolio`) y llama a
`yf.Ticker(ticker).news` de `yfinance` — cero dependencias ni credenciales nuevas.

Está decorada con `@mcp.tool()` igual que el resto, pero **no** se ha añadido a
`TOOLS_SCHEMA`/`TOOL_MAP` de `chat_agent.py`: es de uso exclusivo del job de dashboard.
Si se expusiera al chat conversacional, el modelo podría llamarla en cada mensaje sobre
inversiones sin necesidad real, gastando tokens y tiempo de respuesta.

### 3.3. `dashboard_agent.py` — el corazón de la funcionalidad

`backend/app/agent/dashboard_agent.py`, función principal `generate_dashboard_cards(user_id)`:

1. **`_gather_context(user_id)`** — llama directamente (sin LLM de por medio) a las
   funciones de `financial_mcp.py` que ya sabemos que hacen falta: resumen financiero,
   desglose de categorías del mes, análisis de gasto vs. histórico, cartera de inversión,
   noticias de esa cartera, y metas activas (consultadas directo con `SessionLocal`, como
   hace cualquier tool del proyecto).

   Esto es la diferencia clave con `chat_agent.py`: el chat no sabe de antemano qué
   pregunta hará el usuario, así que necesita un bucle de tool-calling donde el LLM decide
   qué llamar. Aquí sí sabemos exactamente qué datos son relevantes para detectar
   situaciones, así que ahorrarnos ese bucle es más rápido y barato.

2. **Una única llamada a `litellm.completion`** con `DASHBOARD_PROMPT` (few-shot con 2
   ejemplos de tarjeta) y todo el contexto recopilado como JSON en el mensaje de usuario.
   El modelo devuelve `{"cards": [...]}`. Se usa `response_format json_object` en
   proveedores que lo soportan (no Claude, igual que en `chat_agent.py`).

3. **`_parse_cards(raw)`** — parseo tolerante: si el JSON completo es inválido, se
   devuelve una lista vacía (no se revienta el job); si el array tiene tarjetas
   individuales inválidas (`type` fuera de enum, `severity` mal escrita...), esas se
   descartan una a una vía `pydantic.ValidationError`, conservando las válidas.

4. **Persistencia** — cada tarjeta válida se guarda como una fila `Alert` nueva, abriendo
   su propia `SessionLocal()` (mismo patrón que el resto de `financial_mcp.py`, para poder
   llamarse tanto desde el scheduler como desde un endpoint sin pelearse con
   `Depends(get_db)` de FastAPI).

### 3.3bis. Objetivos creados desde el chat — cerrando el círculo con `Goal`

Cuando se construyó el dashboard, la tabla `goals` ya existía en el esquema (Fase de
reestructuración de BD) y `_gather_context` ya la leía para generar tarjetas
`goal_progress` — pero nada escribía en ella: no había forma de que un usuario creara un
objetivo real. Para cerrar ese círculo se añadieron tres tools nuevas en
`financial_mcp.py`, esta vez sí expuestas al chat conversacional (a diferencia de
`get_portfolio_news`):

- **`create_goal(user_id, name, target_amount, current_amount=0, deadline=None)`** — crea
  la fila `Goal`. Valida que `target_amount > 0` y que `current_amount` no sea negativo ni
  supere el objetivo.
- **`list_goals(user_id, status="active")`** — para que el modelo pueda consultar objetivos
  existentes (por ejemplo, antes de actualizar uno, necesita su `id`).
- **`update_goal_progress(goal_id, new_current_amount, user_id)`** — actualiza el ahorro
  acumulado; si iguala o supera `target_amount`, marca el objetivo como `completed`
  automáticamente.

**Por qué no llevan `pending_action` de confirmación** (a diferencia de
`make_bizum_transfer`/`add_investment`): esas dos sí mueven dinero real o registran una
posición de inversión — son irreversibles o representan un compromiso económico. Crear un
objetivo es solo una etiqueta de planificación: no descuenta saldo, no genera una
`Transaction`, y el usuario puede pedir que se corrija sin ninguna consecuencia. Por eso se
registran en `TOOLS_SCHEMA`/`TOOL_MAP` de `chat_agent.py` como cualquier tool de lectura,
con la única instrucción en el prompt de preguntar primero si falta nombre o importe.

El efecto práctico: un objetivo creado por chat aparece automáticamente la próxima vez que
se regenere el dashboard (botón "Actualizar ahora" o job nocturno), porque
`_gather_context` ya consulta `Goal` sin cambios adicionales — la tabla siempre fue la
misma, solo faltaba quien escribiera en ella.

Tests en `backend/tests/test_goal_tools.py`: usan una BD SQLite temporal real (no mocks de
sesión) porque estas tools hacen `filter`/`order_by` cuya lógica interesa probar de verdad,
no solo simular. Cubren validaciones de importes, fechas mal formadas, filtrado por
`status`, y el marcado automático a `completed`.

### 3.4. `scheduler.py` — generación programada

`backend/app/core/scheduler.py`, `APScheduler` con `BackgroundScheduler` (síncrono, porque
`generate_dashboard_cards` ya es síncrono):

- **Job nocturno** (22:00, todos los días) — recorre todos los usuarios y regenera sus
  tarjetas.
- **Job semanal** (lunes 09:00) — mismo pipeline; el propio prompt tiende a generar más
  contenido tipo `weekly_summary` al inicio de semana por el contexto acumulado, así que
  no hace falta forzar un tipo de tarjeta distinto por código.

Arrancado en el evento `startup` de `main.py`, apagado en `shutdown`.

### 3.5. Router `dashboard.py`

`backend/app/api/routes/dashboard.py`:

- `GET /dashboard/` → resumen financiero rápido + tarjetas activas (no expiradas),
  ordenadas por severidad (`critical` → `warning` → `info`) y luego por fecha.
- `POST /dashboard/refresh` → dispara `generate_dashboard_cards` **de forma síncrona** y
  devuelve el dashboard actualizado. Pensado para la demo en directo (no se puede esperar
  a las 22:00 delante del jurado).
- `PATCH /dashboard/alerts/{id}/seen` → marca una tarjeta como vista.

### 3.6. Schemas nuevos

`backend/app/schemas/financial.py` — `AlertCardIn` (lo que valida la salida del LLM antes
de guardar, sin `id`) y `AlertCardOut` (lo que sirve el endpoint, con `id`/`seen`/
`generated_at`). Ambos reutilizan `ChartDataPoint`, que ya existía para el chat.

## 4. Frontend paso a paso

### 4.1. `App.jsx` — pestañas + voz global

- Estado `view` (`'dashboard' | 'chat'`) sustituye al render fijo de `<ChatBox />`.
- `ChatBox` se mantiene **siempre montado** (oculto con `hidden` cuando no es la pestaña
  activa, no desmontado) para no perder su historial de conversación ni el "handler" de
  voz que registra, al cambiar de pestaña.
- El `<VoiceModal>` se ha subido de `ChatBox.jsx` a `App.jsx`: ahora vive un nivel por
  encima de las pestañas y hay un botón flotante (FAB) siempre visible en la esquina
  inferior derecha, además del botón de micrófono que ya existía dentro del chat.
- `ChatBox` reporta su `history` a `App.jsx` vía la prop `onHistoryChange` (guardado en un
  `ref`, no en estado, para no forzar renders de `App` en cada mensaje). Así, sea cual sea
  la pestaña activa, `App.jsx` siempre tiene el historial real del chat disponible para
  pasárselo a la voz.

### 4.2. `DashboardPage.jsx` (nuevo)

- Al montar, `GET /dashboard/` vía `apiGet` (mismo patrón que el resto de `services/api.js`).
- Cabecera con saldo / ingresos / gastos del resumen rápido.
- Grid de tarjetas — cada una según `card_type`:
  - `text` → título + cuerpo.
  - `stat` → título + cuerpo destacado en tamaño grande.
  - `chart` → título + cuerpo + `<InlineChart>` **reutilizado tal cual** (mismas props
    `chartType`/`chartData`/`chartTitle` que ya usa el chat).
  - Borde de color según `severity` (`critical` rojo, `warning` ámbar, `info` neutro).
- Botón "Actualizar ahora" → `POST /dashboard/refresh`.
- Click en cualquier tarjeta → `onOpenCard(card)`, que en `App.jsx` cambia a la pestaña
  "Chat" y precarga `card.cta_prompt` como `initialPrompt`.

### 4.3. `ChatBox.jsx` — cambios

- Ya no gestiona su propio `voiceOpen`/`<VoiceModal>`; recibe `onOpenVoice` (llamado sin
  argumentos — `App.jsx` ya tiene el historial vía el `ref` del punto 4.1) y
  `registerVoiceCompleteHandler` (para que la voz, que ahora vive en `App.jsx`, pueda
  seguir insertando el resultado de una vuelta hablada en los mensajes de este chat).
- Nueva prop `initialPrompt`: si llega con valor, se envía automáticamente como si el
  usuario lo hubiera escrito (mismo camino que un click en una sugerencia), y se notifica
  de vuelta a `App.jsx` (`onInitialPromptConsumed`) para no reenviarlo en renders futuros.

### 4.4. Contexto de voz según la pestaña

`App.jsx`, función `openVoice()`: si `view === 'dashboard'`, antepone al `history` real un
mensaje `user` sintético ("Contexto visible: estoy mirando mi dashboard financiero con
tarjetas generadas por la IA") antes de pasarlo a `<VoiceModal>`. Esto permite preguntas
como "¿por qué me sale esa alerta de restaurantes?" sin que el usuario tenga que
especificar de qué está hablando — sin tocar ni una línea de `VoiceModal.jsx` ni del
backend, porque `VoiceModal` ya aceptaba un `history` arbitrario como prop.

## 5. Decisiones de diseño y su porqué

- **No se usa LangGraph aquí.** El punto 1 del roadmap (LangGraph para confirmaciones de
  Bizum/inversión) sigue siendo un problema distinto: garantizar que una operación
  irreversible pase por confirmación humana. Generar tarjetas de dashboard no ejecuta
  ninguna operación irreversible — solo lee datos y escribe alertas — así que no necesita
  un grafo con `interrupt()`. Una función Python síncrona con una única llamada al LLM es
  suficiente, más simple, y más barata en tokens.
- **Las tarjetas reutilizan el esquema de gráfica del chat** (`ChartDataPoint`,
  `chart_type: bar|line|pie`) en vez de inventar un formato nuevo — así `InlineChart.jsx`
  se reutiliza sin cambios.
- **No se añadió `react-router`.** El frontend no tenía routing antes de esto; un estado
  `view` en `App.jsx` es suficiente para dos pestañas. Si algún día hace falta
  deep-linking, se puede migrar entonces.
- **`yfinance.Ticker(ticker).news`** en vez de una API de noticias nueva — cero
  credenciales ni dependencias adicionales, y `yfinance` ya estaba en `requirements.txt`.
- **Tests mínimos, no un framework nuevo.** El proyecto no tenía ningún test antes de esto.
  Se añadió `pytest` (dependencia de desarrollo) con un único fichero
  (`backend/tests/test_dashboard_agent.py`) centrado en lo más frágil de la funcionalidad
  nueva: que el JSON que devuelve el LLM se valide y parsee correctamente, incluyendo casos
  de JSON malformado o con campos inválidos. La lógica financiera existente (cálculos de
  saldo, hipotecas, etc.) queda explícitamente fuera de alcance de esta tarea.

## 6. Cómo probarlo

```bash
# 1. Aplicar la migración nueva sobre la BD de desarrollo
cd backend && .venv/bin/python -m alembic upgrade head

# 2. Tests del parseo de tarjetas (mockean litellm, no hacen red)
.venv/bin/python -m pytest tests/ -v

# 3. Arrancar el backend y disparar una generación manual
docker compose up
# → POST /dashboard/refresh (autenticado) desde /docs (Swagger)

# 4. En el navegador
# - Cargar la app: debería abrir en la pestaña "Dashboard"
# - Confirmar que aparecen tarjetas (alguna de texto, alguna con gráfico)
# - Click en una tarjeta → cambia a "Chat" con la pregunta sugerida ya enviada
# - Botón flotante de voz desde el dashboard → preguntar algo sobre una tarjeta
#   visible y comprobar que la respuesta tiene el contexto correcto
```
