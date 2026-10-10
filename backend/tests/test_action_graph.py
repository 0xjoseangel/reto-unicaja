"""
Tests del grafo de LangGraph para operaciones que mueven dinero (Bizum, inversión).

Recorren el camino real de punta a punta (endpoints → grafo → actions → BD) con una
BD SQLite temporal, como test_goal_tools.py. Lo único simulado es lo externo: el LLM
(litellm) con respuestas guionizadas y yfinance (precio y tipo de cambio).

Lo que se comprueba es la garantía central del diseño: el LLM puede proponer lo que
quiera, pero el dinero solo se mueve una vez, con los datos validados por el servidor
y después de que el usuario apruebe con POST /chat/actions/{id}.
"""
import json
import os
import tempfile
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent import actions, chat_agent, graph
from app.core.database import Base
from app.core.dependencies import get_current_user
from app.main import app
from app.models.financial import Account, BizumTransfer, Investment, PendingAction, Transaction, User


# ── LLM simulado ──────────────────────────────────────────────────────────────

def _tool_call(name: str, args: dict, call_id: str = "call_1"):
    return SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=json.dumps(args)))


def _completion(tool_calls=None, content=""):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


class FakeLLM:
    """Fase 1: devuelve en orden las respuestas de `script`. Fase 2: un texto fijo
    en streaming. Guarda los mensajes que recibe cada llamada."""

    def __init__(self):
        self.script: list = []
        self.calls: list[list[dict]] = []
        self.final_text = "Hecho."

    def completion(self, model, messages, **kwargs):
        self.calls.append(messages)
        return self.script.pop(0) if self.script else _completion()

    async def acompletion(self, model, messages, stream=False, **kwargs):
        self.calls.append(messages)
        text = self.final_text + chat_agent._MARKER + '{"chart_type":"none","chart_data":[],"chart_title":""}'

        async def gen():
            for i in range(0, len(text), 7):
                yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text[i:i + 7]))])
        return gen()


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture()
def env(monkeypatch):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    import app.agent.financial_mcp as financial_mcp
    monkeypatch.setattr(financial_mcp, "SessionLocal", TestSessionLocal)

    db = TestSessionLocal()
    users = []
    for i, balance in enumerate((100.0, 500.0)):
        u = User(name=f"User {i}", email=f"u{i}@test.com", password_hash="x", created_at=datetime.now())
        db.add(u)
        db.flush()
        db.add(Account(user_id=u.id, name="Corriente", account_type="corriente", balance=balance))
        db.add(Account(user_id=u.id, name="Ahorro", account_type="ahorro", balance=1000.0))
        users.append(u.id)
    db.commit()
    db.close()

    llm = FakeLLM()
    monkeypatch.setattr(chat_agent.litellm, "completion", llm.completion)
    monkeypatch.setattr(chat_agent.litellm, "acompletion", llm.acompletion)
    monkeypatch.setattr(graph, "_build_model", lambda: "anthropic/test")
    monkeypatch.setattr(graph, "_check_api_key", lambda model: None)
    # Persistencia de Conversation va a la misma BD temporal (no a la real), y la
    # recuperación de memoria no debe llamar a litellm.embedding por red en tests.
    monkeypatch.setattr(graph, "SessionLocal", TestSessionLocal)
    monkeypatch.setattr(graph, "retrieve_relevant_memories", lambda user_id, query, top_k=3: [])

    # yfinance: AAPL a 200 USD, 1 EUR = 1.25 USD → 1 AAPL = 160 EUR
    monkeypatch.setattr(actions, "get_market_quote", lambda t: {
        "ticker": t.upper(), "nombre": "Apple Inc.", "precio": 200.0, "moneda": "USD",
    })
    monkeypatch.setattr(actions, "get_eur_rate", lambda cur: 1.25 if cur == "USD" else 1.0)

    graph.set_graph(graph.build_graph(InMemorySaver()))

    current = {"id": users[0]}
    app.dependency_overrides[get_current_user] = lambda: current["id"]
    client = TestClient(app)  # sin `with`: no arranca startup (scheduler, checkpointer SQLite)

    yield SimpleNamespace(client=client, llm=llm, users=users, current=current, Session=TestSessionLocal)

    app.dependency_overrides.clear()
    graph.set_graph(None)
    engine.dispose()
    os.remove(path)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _events(response) -> list[dict]:
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


def _done(response) -> dict:
    return next(e for e in _events(response) if e["type"] == "done")


def _chat(env, message="Envía 20€ a Ana"):
    return env.client.post("/chat/stream", json={"message": message, "history": []})


def _checking_balance(env, user_id) -> float:
    db = env.Session()
    try:
        return db.query(Account).filter_by(user_id=user_id, account_type="corriente").one().balance
    finally:
        db.close()


def _count(env, model) -> int:
    db = env.Session()
    try:
        return db.query(model).count()
    finally:
        db.close()


def _propose_bizum(env, amount=20.0, **extra):
    env.llm.script = [_completion([_tool_call("propose_bizum", {"recipient": "Ana", "amount": amount, "concept": "Cena", **extra})])]
    return _done(_chat(env))["pending_action"]


# ── Bizum ─────────────────────────────────────────────────────────────────────

def test_proposal_interrupts_without_touching_money(env):
    pending = _propose_bizum(env)

    assert pending["type"] == "bizum_confirm"
    assert pending["amount"] == 20.0 and pending["recipient"] == "Ana"
    assert pending["action_id"]
    assert _checking_balance(env, env.users[0]) == 100.0
    assert _count(env, BizumTransfer) == 0


def test_approve_executes_exactly_once(env):
    pending = _propose_bizum(env)

    res = env.client.post(f"/chat/actions/{pending['action_id']}", json={"decision": "approve"})
    assert res.status_code == 200
    assert any(e["type"] == "token" for e in _events(res))
    assert _checking_balance(env, env.users[0]) == 80.0
    assert _count(env, BizumTransfer) == 1

    again = env.client.post(f"/chat/actions/{pending['action_id']}", json={"decision": "approve"})
    assert again.status_code == 409
    assert _checking_balance(env, env.users[0]) == 80.0
    assert _count(env, BizumTransfer) == 1


def test_execute_is_idempotent_on_its_own(env):
    pending = _propose_bizum(env)
    actions.decide(pending["action_id"], env.users[0], "approve")

    first = actions.execute(pending["action_id"])
    second = actions.execute(pending["action_id"])

    assert first == second
    assert _checking_balance(env, env.users[0]) == 80.0
    assert _count(env, BizumTransfer) == 1


def test_unexpected_execute_error_marks_failed_not_stuck(env, monkeypatch):
    """Un fallo que no es OperationError (p.ej. un error de BD) no debe dejar la
    PendingAction congelada en "approved" sin forma de reintentar: se marca
    "failed" igual que un fallo de validación conocido, y el dinero no se mueve."""
    pending = _propose_bizum(env)
    actions.decide(pending["action_id"], env.users[0], "approve")

    monkeypatch.setattr(actions, "execute_bizum", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    result = actions.execute(pending["action_id"])

    assert result["success"] is False
    assert _checking_balance(env, env.users[0]) == 100.0
    assert _count(env, BizumTransfer) == 0

    db = env.Session()
    try:
        assert db.get(PendingAction, pending["action_id"]).status == "failed"
    finally:
        db.close()


def test_reject_moves_no_money(env):
    pending = _propose_bizum(env)

    res = env.client.post(f"/chat/actions/{pending['action_id']}", json={"decision": "reject"})
    assert res.status_code == 200
    assert _checking_balance(env, env.users[0]) == 100.0
    assert _count(env, BizumTransfer) == 0
    # El modelo redacta la respuesta sabiendo que se canceló
    assert "cancelado" in env.llm.calls[-1][-1]["content"]


def test_other_user_cannot_decide(env):
    pending = _propose_bizum(env)

    env.current["id"] = env.users[1]
    res = env.client.post(f"/chat/actions/{pending['action_id']}", json={"decision": "approve"})
    assert res.status_code == 404
    assert _checking_balance(env, env.users[0]) == 100.0


def test_expired_action_returns_410(env):
    pending = _propose_bizum(env)
    db = env.Session()
    db.get(PendingAction, pending["action_id"]).created_at = datetime.now() - timedelta(minutes=10)
    db.commit()
    db.close()

    res = env.client.post(f"/chat/actions/{pending['action_id']}", json={"decision": "approve"})
    assert res.status_code == 410
    assert _count(env, BizumTransfer) == 0


def test_unknown_action_returns_404(env):
    res = env.client.post("/chat/actions/no-existe", json={"decision": "approve"})
    assert res.status_code == 404


def test_insufficient_balance_stops_before_interrupt(env):
    env.llm.script = [_completion([_tool_call("propose_bizum", {"recipient": "Ana", "amount": 150.0})])]
    done = _done(_chat(env))

    assert done["pending_action"] is None
    assert _count(env, PendingAction) == 0
    assert "Saldo insuficiente" in env.llm.calls[-1][-1]["content"]


def test_bizum_over_limit_stops_before_interrupt(env):
    env.current["id"] = env.users[1]
    env.llm.script = [_completion([_tool_call("propose_bizum", {"recipient": "Ana", "amount": 2500.0})])]
    done = _done(_chat(env))

    assert done["pending_action"] is None
    assert "límite" in env.llm.calls[-1][-1]["content"]


def test_llm_cannot_call_write_tools(env):
    env.llm.script = [_completion([_tool_call("make_bizum_transfer", {"recipient": "Ana", "amount": 20.0})])]
    _chat(env)

    tool_msgs = [m for m in env.llm.calls[-1] if m.get("role") == "tool"]
    assert "not found" in tool_msgs[0]["content"]
    assert _checking_balance(env, env.users[0]) == 100.0
    assert "make_bizum_transfer" not in chat_agent.TOOL_MAP
    assert "add_investment" not in chat_agent.TOOL_MAP


def test_user_id_from_llm_is_ignored(env):
    # El modelo intenta leer los saldos del usuario 2
    env.llm.script = [_completion([_tool_call("get_account_balances", {"user_id": env.users[1]})])]
    _chat(env)

    tool_msgs = [m for m in env.llm.calls[-1] if m.get("role") == "tool"]
    balances = json.loads(tool_msgs[0]["content"])
    assert "100.0" in json.dumps(balances) and "500.0" not in json.dumps(balances)


def test_no_tool_schema_exposes_user_id():
    for tool in chat_agent.TOOLS_SCHEMA:
        assert "user_id" not in json.dumps(tool), tool["function"]["name"]


# ── Inversión ─────────────────────────────────────────────────────────────────

def test_investment_uses_market_price_and_charges_eur(env):
    env.current["id"] = env.users[1]
    # El modelo intenta colar un precio de 1€: debe ignorarse
    env.llm.script = [_completion([_tool_call(
        "propose_investment", {"ticker": "aapl", "shares": 2, "avg_purchase_price": 1.0},
    )])]
    pending = _done(_chat(env))["pending_action"]

    assert pending["type"] == "investment_confirm"
    assert pending["ticker"] == "AAPL"
    assert pending["price"] == 200.0 and pending["currency"] == "USD"
    assert pending["total_eur"] == 320.0

    res = env.client.post(f"/chat/actions/{pending['action_id']}", json={"decision": "approve"})
    assert res.status_code == 200
    assert _checking_balance(env, env.users[1]) == 180.0

    db = env.Session()
    inv = db.query(Investment).filter_by(user_id=env.users[1], ticker="AAPL").one()
    tx = db.query(Transaction).filter_by(user_id=env.users[1], category="inversion").one()
    db.close()
    assert inv.shares == 2 and inv.avg_purchase_price == 200.0
    assert tx.amount == 320.0


def test_investment_without_balance_stops(env):
    # 1 AAPL = 160€ y el usuario 1 tiene 100€
    env.llm.script = [_completion([_tool_call("propose_investment", {"ticker": "AAPL", "shares": 1})])]
    done = _done(_chat(env))

    assert done["pending_action"] is None
    assert _count(env, Investment) == 0


# ── Solo lectura ──────────────────────────────────────────────────────────────

def test_read_only_question_streams_answer(env):
    env.llm.final_text = "Tienes 100€."
    env.llm.script = [
        _completion([_tool_call("get_account_balances", {})]),
        _completion(content=""),
    ]
    events = _events(_chat(env, "¿Cuánto tengo?"))

    text = "".join(e["text"] for e in events if e["type"] == "token")
    assert text == "Tienes 100€."
    assert events[-1]["type"] == "done" and events[-1]["pending_action"] is None
