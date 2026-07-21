import re

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from app.services.tts_service import synthesize
from app.services.whisper_service import transcribe

router = APIRouter(prefix="/voice", tags=["voice"])


def clean_for_tts(text: str) -> str:
    """Elimina sintaxis markdown para que Piper lea el texto limpio."""
    # Bloques de código ```...```
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Código inline `...`
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Cabeceras ## Titulo
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # Negrita/cursiva ***text***, **text**, *text*
    text = re.sub(r"\*{1,3}([^*\n]+)\*{1,3}", r"\1", text)
    # Separadores ---
    text = re.sub(r"^-{3,}$", "", text, flags=re.MULTILINE)
    # Filas de tabla | col | col |
    text = re.sub(r"^\|.*\|$", "", text, flags=re.MULTILINE)
    # Separador de tabla |---|---|
    text = re.sub(r"^\|[\s\-:|]+\|$", "", text, flags=re.MULTILINE)
    # Listas - item y * item
    text = re.sub(r"^[\-\*]\s+", "", text, flags=re.MULTILINE)
    # Listas numeradas 1. item
    text = re.sub(r"^\d+\.\s+", "", text, flags=re.MULTILINE)
    # Links [texto](url) → texto
    text = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", text)
    # Múltiples líneas vacías → salto simple
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


@router.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    data = await file.read()
    content_type = file.content_type or ""
    suffix = ".ogg" if "ogg" in content_type else ".webm"
    text = await transcribe(data, suffix)
    if not text:
        raise HTTPException(status_code=400, detail="No se detectó audio")
    return {"text": text}


class SynthRequest(BaseModel):
    text: str


@router.post("/synthesize")
async def synthesize_text(req: SynthRequest):
    clean_text = clean_for_tts(req.text)
    if not clean_text:
        raise HTTPException(status_code=400, detail="Texto vacío tras limpiar markdown")
    audio_bytes = await synthesize(clean_text)
    return Response(content=audio_bytes, media_type="audio/wav")
