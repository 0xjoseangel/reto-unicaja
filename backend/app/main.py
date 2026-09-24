from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, chat, transactions, voice
from app.core.config import settings
from app.core.database import Base, engine

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


@app.get("/")
async def root():
    return {"message": f"Bienvenido a {settings.app_name}", "docs": "/docs"}
