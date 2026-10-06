import asyncio
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.graph import close_graph, init_graph
from app.api.routes import auth, chat, dashboard, transactions, voice
from app.core.config import settings
from app.core.database import Base, engine
from app.core.scheduler import start_scheduler, stop_scheduler
from app.services import tts_service, whisper_service

logger = logging.getLogger(__name__)

app = FastAPI(title=settings.app_name, version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(chat.router)
app.include_router(voice.router)
app.include_router(dashboard.router)


def _warm_voice_models() -> None:
    """Carga Whisper y Piper al arrancar. Sin esto, la primera frase del modo voz
    tarda ~10 s más (se cargaban en la primera petición)."""
    try:
        whisper_service._get_model()
        tts_service._get_voice()
    except Exception:
        logger.exception("No se pudieron precargar los modelos de voz")


@app.on_event("startup")
async def _on_startup() -> None:
    await init_graph()
    start_scheduler()
    # En segundo plano: no retrasa el arranque del servidor
    asyncio.get_running_loop().run_in_executor(None, _warm_voice_models)


@app.on_event("shutdown")
async def _on_shutdown() -> None:
    stop_scheduler()
    await close_graph()


@app.get("/")
async def root():
    return {"message": f"Bienvenido a {settings.app_name}", "docs": "/docs"}
