from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.agent import actions
from app.agent.graph import process_chat, process_chat_stream, resume_chat_stream
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.financial import Conversation
from app.schemas.financial import (
    ActionDecisionRequest,
    ChatRequest,
    ChatResponse,
    ConversationMessageOut,
    ConversationSessionOut,
)

router = APIRouter(prefix="/chat", tags=["chat"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


def _history_days(db: Session, user_id: int) -> list[ConversationSessionOut]:
    """Agrupa los turnos de Conversation por día natural — no hay id de sesión/hilo
    en el modelo, así que el día es el único criterio de agrupación disponible."""
    rows = (
        db.query(Conversation)
        .filter(Conversation.user_id == user_id)
        .order_by(Conversation.created_at.asc())
        .all()
    )
    by_day: dict[str, dict] = {}
    for row in rows:
        day = row.created_at.date().isoformat()
        entry = by_day.setdefault(day, {"count": 0, "preview": ""})
        entry["count"] += 1
        if not entry["preview"] and row.role == "user":
            entry["preview"] = row.content[:140]
    return [
        ConversationSessionOut(date=day, message_count=v["count"], preview=v["preview"])
        for day, v in sorted(by_day.items(), reverse=True)
    ]


def _messages_for_day(db: Session, user_id: int, day: date) -> list[ConversationMessageOut]:
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    rows = (
        db.query(Conversation)
        .filter(
            Conversation.user_id == user_id,
            Conversation.created_at >= start,
            Conversation.created_at < end,
        )
        .order_by(Conversation.created_at.asc())
        .all()
    )
    return [ConversationMessageOut.model_validate(r) for r in rows]


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest, user_id: int = Depends(get_current_user)):
    history = [m.model_dump() for m in request.history]
    return await process_chat(request.message, user_id, history)


@router.post("/stream")
async def chat_stream(request: ChatRequest, user_id: int = Depends(get_current_user)):
    history = [m.model_dump() for m in request.history]
    return StreamingResponse(
        process_chat_stream(request.message, user_id, history, request.voice_mode),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/history", response_model=list[ConversationSessionOut])
async def list_history(user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    """Conversaciones pasadas, agrupadas por día, más reciente primero."""
    return _history_days(db, user_id)


@router.get("/history/{day}", response_model=list[ConversationMessageOut])
async def get_history_day(
    day: str,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Transcripción completa de un día concreto (formato YYYY-MM-DD)."""
    try:
        parsed_day = datetime.strptime(day, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Fecha inválida, usa YYYY-MM-DD.")
    return _messages_for_day(db, user_id, parsed_day)


@router.post("/actions/{action_id}")
async def decide_action(
    action_id: str,
    request: ActionDecisionRequest,
    user_id: int = Depends(get_current_user),
):
    """Aprueba o rechaza una operación propuesta por el agente (Bizum, inversión).

    Es la única vía para ejecutar una operación que mueve dinero. La decisión se
    registra antes de reanudar el grafo, así que un segundo intento devuelve 409."""
    try:
        actions.decide(action_id, user_id, request.decision)
    except actions.ActionNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Operación no encontrada.")
    except actions.ActionAlreadyDecided:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Esta operación ya se ha procesado.")
    except actions.ActionExpired:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="La operación ha caducado. Vuelve a pedirla.",
        )
    return StreamingResponse(
        resume_chat_stream(action_id),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
