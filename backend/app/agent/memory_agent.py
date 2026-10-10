"""
Memoria de usuario: hechos y preferencias extraídos de conversaciones pasadas,
embebidos y recuperados por similitud para personalizar al chat.

A diferencia del dashboard (una llamada al LLM por usuario y listo), esto son dos
piezas separadas en el tiempo:

  1. extract_and_store_memories(user_id) — job periódico (scheduler.py). Lee las
     últimas Conversation de un usuario, le pide al LLM que extraiga frases cortas
     de hechos/preferencias, las embebe (litellm.embedding) y las guarda en
     UserProfileVector.
  2. retrieve_relevant_memories(user_id, query) — en caliente, antes de cada turno
     de chat (graph.py). Embebe el mensaje del usuario y devuelve los 2-3 chunks
     más parecidos (similitud coseno en Python puro — nada de BD vectorial, el
     volumen de datos de este proyecto es minúsculo).

Ver docs/memoria-usuario.md para el porqué de cada decisión de diseño.
"""
import json
import logging
import math

import litellm

from app.agent.chat_agent import _build_model, _is_claude
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.financial import Conversation, UserProfileVector

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = settings.embedding_model


def _embed(text: str) -> list[float]:
    """Embebe un texto con litellm. _build_model() se llama solo por su efecto
    secundario (deja GEMINI_API_KEY en el entorno); el modelo de embeddings es
    fijo, no el de chat."""
    _build_model()
    response = litellm.embedding(model=EMBEDDING_MODEL, input=text)
    return response.data[0]["embedding"]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def retrieve_relevant_memories(user_id: int, query: str, top_k: int = 3) -> list[str]:
    """Hasta top_k chunk_text ordenados por similitud con query. Lista vacía si el
    usuario no tiene memorias, o si falla el embedding (nunca debe tumbar un turno
    de chat por esto)."""
    try:
        query_vec = _embed(query)
    except Exception:
        logger.exception("Fallo al embeber el mensaje para recuperar memoria (user_id=%s)", user_id)
        return []

    db = SessionLocal()
    try:
        rows = db.query(UserProfileVector).filter(UserProfileVector.user_id == user_id).all()
    finally:
        db.close()

    scored = []
    for row in rows:
        if not row.embedding:
            continue
        try:
            vec = json.loads(row.embedding)
        except json.JSONDecodeError:
            continue
        scored.append((_cosine_similarity(query_vec, vec), row.chunk_text))

    scored.sort(key=lambda t: t[0], reverse=True)
    return [text for _, text in scored[:top_k]]


EXTRACTION_PROMPT = """Analiza esta conversación entre un usuario y un asistente
financiero. Extrae, si los hay, hechos o preferencias breves y reutilizables sobre
el USUARIO (no sobre el asistente): objetivos, prioridades, aversión/apetito al
riesgo, hábitos de gasto, situación personal relevante.

Responde ÚNICAMENTE con un JSON {"facts": ["frase corta 1", "frase corta 2", ...]}
(lista vacía si no hay nada reseñable; no inventes nada que no esté en el texto)."""


def _extract_facts(conversation_text: str) -> list[str]:
    model = _build_model()
    messages = [
        {"role": "system", "content": EXTRACTION_PROMPT},
        {"role": "user", "content": conversation_text},
    ]
    kwargs: dict = {"model": model, "messages": messages}
    if not _is_claude(model):
        kwargs["response_format"] = {"type": "json_object"}
    response = litellm.completion(**kwargs)
    raw = (response.choices[0].message.content or "{}").strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    facts = data.get("facts", []) if isinstance(data, dict) else []
    return [f.strip() for f in facts if isinstance(f, str) and f.strip()]


def extract_and_store_memories(user_id: int, lookback: int = 20) -> list[str]:
    """Job por usuario: lee las últimas `lookback` filas de Conversation, extrae
    hechos nuevos y los guarda embebidos. Devuelve los hechos guardados (para
    tests/logging)."""
    db = SessionLocal()
    try:
        rows = (
            db.query(Conversation)
            .filter(Conversation.user_id == user_id)
            .order_by(Conversation.created_at.desc())
            .limit(lookback)
            .all()
        )
    finally:
        db.close()

    if not rows:
        return []

    conversation_text = "\n".join(f"{r.role}: {r.content}" for r in reversed(rows))
    facts = _extract_facts(conversation_text)
    if not facts:
        return []

    db = SessionLocal()
    try:
        for fact in facts:
            try:
                embedding = _embed(fact)
            except Exception:
                logger.exception("Fallo al embeber un hecho de memoria (user_id=%s)", user_id)
                continue
            db.add(UserProfileVector(
                user_id=user_id,
                chunk_text=fact,
                embedding=json.dumps(embedding),
                source="conversation",
            ))
        db.commit()
    finally:
        db.close()
    return facts
