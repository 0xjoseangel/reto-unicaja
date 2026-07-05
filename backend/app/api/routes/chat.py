from fastapi import APIRouter

from app.agent.chat_agent import process_chat
from app.schemas.financial import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest):
    history = [m.model_dump() for m in request.history]
    return await process_chat(request.message, request.user_id, history)
