from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.agent.chat_agent import process_chat, process_chat_stream
from app.schemas.financial import ChatRequest, ChatResponse

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/", response_model=ChatResponse)
async def chat(request: ChatRequest):
    history = [m.model_dump() for m in request.history]
    return await process_chat(request.message, request.user_id, history)


@router.post("/stream")
async def chat_stream(request: ChatRequest):
    history = [m.model_dump() for m in request.history]
    return StreamingResponse(
        process_chat_stream(request.message, request.user_id, history),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
