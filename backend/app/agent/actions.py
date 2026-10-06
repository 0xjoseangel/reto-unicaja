"""
Operaciones que mueven dinero (Bizum, compra de inversiones): validación,
aprobación y ejecución. Todo determinista, sin LLM.

El LLM solo puede *proponer* una operación (tools propose_bizum / propose_investment
en chat_agent.py). A partir de ahí el grafo (graph.py) llama a este módulo:

  validate_proposal()   → comprueba límites y saldo, y fija los precios en el servidor
  create_pending()      → registra la propuesta validada como PendingAction "pending"
  decide()              → el usuario aprueba o rechaza (endpoint /chat/actions/{id})
  execute()             → mueve el dinero, una sola vez

Las transiciones de estado son UPDATE condicionados al estado anterior, de modo que
dos peticiones simultáneas no pueden aprobar ni ejecutar la misma acción dos veces.
"""
import json
from datetime import datetime, timedelta

from sqlalchemy import update

from app.agent import financial_mcp
from app.agent.financial_mcp import (
    OperationError,
    check_bizum,
    execute_bizum,
    execute_investment,
    get_eur_rate,
    get_market_quote,
)
from app.models.financial import PendingAction

ACTION_TTL = timedelta(minutes=5)
INVESTMENT_TYPES = ("accion", "etf", "fondo_indexado")


class ActionNotFound(Exception):
    pass


class ActionAlreadyDecided(Exception):
    pass


class ActionExpired(Exception):
    pass


def _session():
    # Se resuelve en cada llamada para que los tests puedan sustituir SessionLocal
    return financial_mcp.SessionLocal()


# ── Validación ────────────────────────────────────────────────────────────────

def validate_proposal(user_id: int, proposal: dict) -> dict:
    """Valida una propuesta del LLM y devuelve el payload que verá el usuario en el
    modal y que se ejecutará si lo aprueba. Lanza OperationError si no es viable.

    Los campos que importan (importe, precio, total en euros) salen de aquí, no del
    LLM: para una inversión se ignora cualquier precio que el modelo haya inventado."""
    kind = proposal.get("type")
    db = _session()
    try:
        if kind == "bizum":
            recipient = str(proposal.get("recipient") or "").strip()
            if not recipient:
                raise OperationError("Falta el destinatario del Bizum.")
            amount = round(float(proposal.get("amount") or 0), 2)
            concept = str(proposal.get("concept") or "Bizum").strip()[:200] or "Bizum"
            check_bizum(db, user_id, amount)
            return {"type": "bizum", "recipient": recipient[:100], "amount": amount, "concept": concept}

        if kind == "investment":
            shares = float(proposal.get("shares") or 0)
            if shares <= 0:
                raise OperationError("El número de acciones debe ser mayor que cero.")
            investment_type = proposal.get("investment_type") or "accion"
            if investment_type not in INVESTMENT_TYPES:
                investment_type = "accion"
            quote = get_market_quote(str(proposal.get("ticker") or ""))
            rate = get_eur_rate(quote["moneda"])
            total_eur = round(shares * quote["precio"] / rate, 2)
            account = financial_mcp._checking_account(db, user_id)
            if account.balance < total_eur:
                raise OperationError(
                    f"Saldo insuficiente. Comprar {shares:g} {quote['ticker']} cuesta "
                    f"{total_eur}€ y tienes {round(account.balance, 2)}€ en la cuenta corriente."
                )
            return {
                "type": "investment",
                "ticker": quote["ticker"],
                "nombre": quote["nombre"],
                "shares": shares,
                "price": quote["precio"],
                "currency": quote["moneda"],
                "total_eur": total_eur,
                "investment_type": investment_type,
            }

        raise OperationError("Tipo de operación desconocido.")
    except (TypeError, ValueError):
        raise OperationError("Los datos de la operación no son válidos.")
    finally:
        db.close()


# ── Ciclo de vida de la PendingAction ─────────────────────────────────────────

def create_pending(action_id: str, user_id: int, payload: dict) -> None:
    db = _session()
    try:
        db.add(PendingAction(
            id=action_id,
            user_id=user_id,
            action_type=payload["type"],
            payload=json.dumps(payload, ensure_ascii=False),
            status="pending",
            created_at=datetime.now(),
        ))
        db.commit()
    finally:
        db.close()


def decide(action_id: str, user_id: int, decision: str) -> None:
    """Registra la decisión del usuario (approve | reject). Lanza ActionNotFound si no
    existe o es de otro usuario, ActionAlreadyDecided si ya se decidió y ActionExpired
    si la propuesta ha caducado."""
    db = _session()
    try:
        action = db.get(PendingAction, action_id)
        if not action or action.user_id != user_id:
            raise ActionNotFound()
        if action.status != "pending":
            raise ActionAlreadyDecided()

        now = datetime.now()
        if now - action.created_at > ACTION_TTL:
            db.execute(
                update(PendingAction)
                .where(PendingAction.id == action_id, PendingAction.status == "pending")
                .values(status="expired", decided_at=now)
            )
            db.commit()
            raise ActionExpired()

        new_status = "approved" if decision == "approve" else "rejected"
        res = db.execute(
            update(PendingAction)
            .where(PendingAction.id == action_id, PendingAction.status == "pending")
            .values(status=new_status, decided_at=now)
        )
        db.commit()
        if res.rowcount != 1:
            # Otra petición la decidió entre la lectura y el UPDATE
            raise ActionAlreadyDecided()
    finally:
        db.close()


def execute(action_id: str) -> dict:
    """Ejecuta una acción aprobada. Idempotente: el paso approved → executed y el
    movimiento de dinero van en la misma transacción; si la acción ya no está en
    "approved" se devuelve el resultado guardado sin volver a ejecutar."""
    db = _session()
    try:
        claimed = db.execute(
            update(PendingAction)
            .where(PendingAction.id == action_id, PendingAction.status == "approved")
            .values(status="executed")
        ).rowcount == 1
        action = db.get(PendingAction, action_id)
        if not claimed:
            db.rollback()
            if action and action.result:
                return json.loads(action.result)
            return {"success": False, "error": "La operación no está aprobada."}

        p = json.loads(action.payload)
        try:
            if p["type"] == "bizum":
                result = execute_bizum(db, action.user_id, p["recipient"], p["amount"], p["concept"])
            else:
                result = execute_investment(
                    db, action.user_id, p["ticker"], p["nombre"], p["shares"],
                    p["price"], p["currency"], p["total_eur"], p["investment_type"],
                )
        except OperationError as e:
            db.rollback()
            result = {"success": False, "error": str(e)}
            db.execute(
                update(PendingAction)
                .where(PendingAction.id == action_id, PendingAction.status == "approved")
                .values(status="failed", result=json.dumps(result, ensure_ascii=False))
            )
            db.commit()
            return result

        action.result = json.dumps(result, ensure_ascii=False)
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
