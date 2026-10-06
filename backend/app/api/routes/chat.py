from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.agent import actions
from app.agent.graph import process_chat, process_chat_stream, resume_chat_stream
from app.core.dependencies import get_current_user
from app.schemas.financial import ActionDecisionRequest, ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["chat"])

_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "X-Accel-Buffering": "no",
}


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
