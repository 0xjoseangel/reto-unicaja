"""
Grafo de LangGraph del chat. Orquesta las dos fases del agente (chat_agent.py) y, sobre
todo, el camino de las operaciones que mueven dinero, que ya no depende del LLM:

    START → agent ──(sin propuesta)─────────────────────────────→ respond → END
              └─(propuesta)→ validate ─(no viable)──────────────→ respond
                                └─(viable)→ await_approval ─(reject)→ respond
                                                 └─(approve)→ execute → respond

- agent           Fase 1. El modelo consulta tools de lectura; para mover dinero solo
                  puede llamar a propose_bizum / propose_investment.
- validate        Determinista. Límites, saldo, precio de mercado y coste en euros.
                  Registra la PendingAction.
- await_approval  interrupt(): el grafo se para y su estado queda en el checkpointer
                  hasta que el usuario aprueba o rechaza con POST /chat/actions/{id}.
- execute         Determinista e idempotente. Mueve el dinero con los datos validados
                  del estado, nunca con lo que diga el modelo.
- respond         Fase 2. Redacta la respuesta en streaming.

Cada petición de chat es un thread nuevo (uuid). Si el grafo se interrumpe, ese uuid es
el action_id que recibe el frontend y con el que se reanuda.
"""
import json
import os
import uuid
from collections.abc import AsyncIterator
from typing import TypedDict

import aiosqlite
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from app.agent import actions
from app.agent.chat_agent import (
    SYSTEM_PROMPT,
    _build_model,
    _check_api_key,
    run_tool_loop,
    stream_response,
)
from app.agent.financial_mcp import OperationError
from app.core.config import settings
from app.models.financial import PendingAction
from app.schemas.financial import ChatResponse, PendingBizumAction, PendingInvestmentAction


class ChatState(TypedDict, total=False):
    user_id: int            # del JWT; el modelo nunca lo ve ni lo elige
    voice_mode: bool
    messages: list[dict]
    proposal: dict | None   # propuesta en crudo del modelo
    action: dict | None     # propuesta validada por el servidor (+ action_id)
    error: str | None       # motivo por el que la propuesta no es viable
    decision: str | None    # approve | reject
    result: dict | None     # resultado de la ejecución
    final: dict | None      # respuesta final (texto + gráfico)


# ── Nodos ─────────────────────────────────────────────────────────────────────

def agent_node(state: ChatState) -> dict:
    messages, proposal = run_tool_loop(state["messages"], _build_model(), state["user_id"])
    return {"messages": messages, "proposal": proposal}


def validate_node(state: ChatState, config: RunnableConfig) -> dict:
    action_id = config["configurable"]["thread_id"]
    try:
        payload = actions.validate_proposal(state["user_id"], state["proposal"])
    except OperationError as e:
        return {"error": str(e)}
    actions.create_pending(action_id, state["user_id"], payload)
    return {"action": {**payload, "action_id": action_id}}


def await_approval_node(state: ChatState) -> dict:
    # El valor del interrupt es el pending_action que pinta el modal del frontend.
    # Al reanudar con Command(resume=...), interrupt() devuelve la decisión.
    decision = interrupt(pending_action_event(state["action"]))
    return {"decision": "approve" if decision == "approve" else "reject"}


def execute_node(state: ChatState) -> dict:
    return {"result": actions.execute(state["action"]["action_id"])}


async def respond_node(state: ChatState) -> dict:
    writer = get_stream_writer()
    final = await stream_response(
        state["messages"],
        _build_model(),
        state.get("voice_mode", False),
        writer,
        context=_outcome_context(state),
    )
    writer({
        "type": "done",
        "chart_type": final["chart_type"],
        "chart_data": final["chart_data"],
        "chart_title": final["chart_title"],
        "pending_action": None,
    })
    return {"final": final}


def _outcome_context(state: ChatState) -> str | None:
    """Lo que el modelo necesita saber para redactar la respuesta cuando ha habido
    una propuesta. Los hechos los pone el grafo; el modelo solo los cuenta."""
    if not state.get("proposal"):
        return None
    if state.get("error"):
        return (
            "[Sistema] La operación propuesta NO se ha realizado porque no pasa la "
            f"validación: {state['error']} Explícaselo al usuario en una o dos frases."
        )
    if state.get("decision") == "reject":
        return (
            "[Sistema] El usuario ha cancelado la operación en la pantalla de confirmación. "
            "No se ha movido dinero. Confírmaselo en una frase."
        )
    result = state.get("result") or {}
    if result.get("success"):
        return (
            "[Sistema] El usuario ha aprobado la operación y se ha ejecutado. Resultado: "
            f"{json.dumps(result, ensure_ascii=False)}. Confírmaselo con las cifras de este "
            "resultado (si incluye nuevo_saldo_total, ese es su saldo actualizado)."
        )
    return (
        "[Sistema] El usuario ha aprobado la operación pero ha fallado al ejecutarse: "
        f"{result.get('error', 'error desconocido')} No se ha movido dinero. Explícaselo."
    )


def pending_action_event(action: dict) -> dict:
    """Convierte la propuesta validada en el pending_action del evento SSE `done`."""
    data = {k: v for k, v in action.items() if k != "type"}
    if action["type"] == "bizum":
        return PendingBizumAction(**data).model_dump()
    return PendingInvestmentAction(**data).model_dump()


# ── Aristas ───────────────────────────────────────────────────────────────────

def _after_agent(state: ChatState) -> str:
    return "validate" if state.get("proposal") else "respond"


def _after_validate(state: ChatState) -> str:
    return "await_approval" if state.get("action") else "respond"


def _after_approval(state: ChatState) -> str:
    return "execute" if state.get("decision") == "approve" else "respond"


def build_graph(checkpointer):
    g = StateGraph(ChatState)
    g.add_node("agent", agent_node)
    g.add_node("validate", validate_node)
    g.add_node("await_approval", await_approval_node)
    g.add_node("execute", execute_node)
    g.add_node("respond", respond_node)

    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", _after_agent, ["validate", "respond"])
    g.add_conditional_edges("validate", _after_validate, ["await_approval", "respond"])
    g.add_conditional_edges("await_approval", _after_approval, ["execute", "respond"])
    g.add_edge("execute", "respond")
    g.add_edge("respond", END)
    return g.compile(checkpointer=checkpointer)


# ── Ciclo de vida (startup/shutdown de main.py) ───────────────────────────────

_graph = None
_conn: aiosqlite.Connection | None = None


async def init_graph(path: str | None = None) -> None:
    global _graph, _conn
    path = path or settings.checkpoint_db_path
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    _conn = await aiosqlite.connect(path)
    saver = AsyncSqliteSaver(_conn)
    await saver.setup()
    _graph = build_graph(saver)


async def close_graph() -> None:
    global _graph, _conn
    if _conn is not None:
        await _conn.close()
    _graph, _conn = None, None


def set_graph(graph) -> None:
    """Para tests: usar un grafo compilado con otro checkpointer (InMemorySaver)."""
    global _graph
    _graph = graph


def _get_graph():
    if _graph is None:
        raise RuntimeError("El grafo del chat no está inicializado (init_graph).")
    return _graph


# ── Ejecución ─────────────────────────────────────────────────────────────────

async def _run(graph_input, thread_id: str) -> AsyncIterator[dict]:
    """Ejecuta (o reanuda) el grafo y produce los eventos para el cliente:
    token / done. Si el grafo se para en await_approval, el `done` lleva el
    pending_action y el estado se conserva para reanudarlo; si termina, se borra."""
    graph = _get_graph()
    cfg = {"configurable": {"thread_id": thread_id}}
    interrupted = False
    async for mode, chunk in graph.astream(graph_input, cfg, stream_mode=["custom", "updates"]):
        if mode == "custom":
            yield chunk
        elif "__interrupt__" in chunk:
            interrupted = True
            yield {
                "type": "done",
                "chart_type": None,
                "chart_data": None,
                "chart_title": None,
                "pending_action": chunk["__interrupt__"][0].value,
            }
    if not interrupted:
        await graph.checkpointer.adelete_thread(thread_id)


def _friendly_error(e: Exception) -> str:
    err = str(e)
    if "429" in err or "rate_limit" in err.lower():
        return "El modelo está ocupado ahora mismo. Espera unos segundos e inténtalo de nuevo."
    if "401" in err or "invalid_api_key" in err.lower() or "authentication" in err.lower():
        return "API key inválida. Revisa el archivo backend/.env"
    return f"Error inesperado: {err[:200]}"


async def _sse(events: AsyncIterator[dict]):
    try:
        async for ev in events:
            yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'text': _friendly_error(e)}, ensure_ascii=False)}\n\n"


def _initial_state(message: str, user_id: int, history: list[dict], voice_mode: bool) -> ChatState:
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": message})
    return {"user_id": user_id, "voice_mode": voice_mode, "messages": messages}


async def process_chat_stream(message: str, user_id: int, history: list[dict] | None = None, voice_mode: bool = False):
    """SSE de una pregunta nueva: eventos token + done (o error)."""
    key_error = _check_api_key(_build_model())
    if key_error:
        yield f"data: {json.dumps({'type': 'error', 'text': key_error}, ensure_ascii=False)}\n\n"
        return
    state = _initial_state(message, user_id, history or [], voice_mode)
    async for chunk in _sse(_run(state, str(uuid.uuid4()))):
        yield chunk


async def resume_chat_stream(action_id: str):
    """SSE tras aprobar/rechazar una operación. La decisión ya está registrada en la
    PendingAction (actions.decide); aquí se reanuda el grafo para ejecutarla (o no)
    y redactar la respuesta."""
    graph = _get_graph()
    cfg = {"configurable": {"thread_id": action_id}}
    snapshot = await graph.aget_state(cfg)
    if not snapshot.next:
        yield f"data: {json.dumps({'type': 'error', 'text': 'La operación ya no está disponible.'}, ensure_ascii=False)}\n\n"
        return
    decision = await _decision_from_db(action_id)
    async for chunk in _sse(_run(Command(resume=decision), action_id)):
        yield chunk


async def _decision_from_db(action_id: str) -> str:
    # La decisión se lee de la BD (fuente de verdad), no de lo que mande el cliente
    # al reanudar: solo "approved" lleva a execute.
    db = actions._session()
    try:
        action = db.get(PendingAction, action_id)
        return "approve" if action and action.status == "approved" else "reject"
    finally:
        db.close()


async def process_chat(message: str, user_id: int, history: list[dict] | None = None) -> ChatResponse:
    """Versión sin streaming (POST /chat/): mismo grafo, eventos agregados."""
    key_error = _check_api_key(_build_model())
    if key_error:
        return ChatResponse(response=key_error)
    text, done = "", {}
    try:
        async for ev in _run(_initial_state(message, user_id, history or [], False), str(uuid.uuid4())):
            if ev["type"] == "token":
                text += ev["text"]
            elif ev["type"] == "done":
                done = ev
    except Exception as e:
        return ChatResponse(response=_friendly_error(e))
    return ChatResponse(
        response=text.strip(),
        chart_type=done.get("chart_type"),
        chart_data=done.get("chart_data"),
        chart_title=done.get("chart_title"),
        pending_action=done.get("pending_action"),
    )
