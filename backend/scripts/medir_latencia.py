"""Mide la latencia real del chat (streaming) y de voz (STT/TTS). No benchmarkea
nada que no se pueda medir con el código real: si falta un modelo o una red, el
script lo dice explícitamente en vez de inventar una cifra.

Uso:
    DATABASE_URL="sqlite:///./data/db.sqlite3" MODEL_CACHE_DIR="./.model_cache" \
        .venv/bin/python -I scripts/medir_latencia.py
"""
import asyncio
import os
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{(BACKEND_DIR / 'data' / 'db.sqlite3').as_posix()}")
os.environ.setdefault("MODEL_CACHE_DIR", str(BACKEND_DIR / ".model_cache"))

from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402

from app.agent import graph as graph_module  # noqa: E402
from app.agent.chat_agent import _build_model, _check_api_key  # noqa: E402

USER_ID = 1

CHAT_QUESTIONS = [
    "¿Cuánto gasté en restaurantes este mes?",
    "¿Cuál es mi gasto total este mes?",
    "¿Cuáles han sido mis ingresos este mes?",
    "¿Cuánto he gastado en total en ropa desde que tengo la cuenta?",
    "¿En qué categoría gasto más dinero este mes?",
    "¿Cuántas veces he comido fuera este mes?",
    "¿Cuál ha sido mi gasto más grande este mes?",
    "¿Cuánto pagué de alquiler este mes?",
    "¿Cuál es mi saldo actual?",
    "¿Gasté más en supermercado o en restaurantes este mes?",
]


async def measure_chat() -> tuple[list[float], list[float]]:
    ttft, total = [], []
    for q in CHAT_QUESTIONS:
        t0 = time.perf_counter()
        first_token_t = None
        async for ev in graph_module._run(
            graph_module._initial_state(q, USER_ID, [], False), f"eval-lat-{time.time_ns()}", USER_ID
        ):
            if ev.get("type") == "token" and first_token_t is None:
                first_token_t = time.perf_counter()
        t1 = time.perf_counter()
        if first_token_t is not None:
            ttft.append(first_token_t - t0)
        total.append(t1 - t0)
        print(f"  TTFT={ (first_token_t - t0) if first_token_t else float('nan'):.2f}s  "
              f"total={t1 - t0:.2f}s  — {q}")
    return ttft, total


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    s = sorted(values)
    k = (len(s) - 1) * p
    f, c = int(k), min(int(k) + 1, len(s) - 1)
    return s[f] + (s[c] - s[f]) * (k - f)


async def measure_voice():
    print("\n--- Voz: TTS (Piper) ---")
    try:
        from app.services.tts_service import synthesize
        text = "Este mes has gastado ciento nueve euros con noventa y seis céntimos en restaurantes."
        t0 = time.perf_counter()
        audio = await synthesize(text)
        tts_elapsed = time.perf_counter() - t0
        print(f"  Síntesis de {len(text)} caracteres -> {len(audio)} bytes WAV en {tts_elapsed:.2f}s "
              "(incluye la descarga del modelo si es la primera vez que se ejecuta).")
    except Exception as e:  # noqa: BLE001
        print(f"  [PENDIENTE: latencia TTS] No se pudo ejecutar Piper: {e}")
        return

    print("\n--- Voz: STT (faster-whisper) ---")
    try:
        from app.services.whisper_service import transcribe
        t0 = time.perf_counter()
        text_out = await transcribe(audio, suffix=".wav")
        stt_elapsed = time.perf_counter() - t0
        print(f"  Transcripción del audio anterior ({tts_elapsed:.2f}s de audio) en {stt_elapsed:.2f}s.")
        print(f"  Texto transcrito: {text_out!r}")
    except Exception as e:  # noqa: BLE001
        print(f"  [PENDIENTE: latencia STT] No se pudo ejecutar faster-whisper: {e}")


async def main():
    key_error = _check_api_key(_build_model())
    if key_error:
        print(f"[PENDIENTE] No se puede medir el chat: {key_error}")
    else:
        graph_module.set_graph(graph_module.build_graph(InMemorySaver()))
        print(f"--- Chat en streaming ({len(CHAT_QUESTIONS)} preguntas, modelo "
              f"{os.environ.get('LITELLM_MODEL', '?')}) ---")
        run_started = datetime.now()
        ttft, total = await measure_chat()
        print("\nResumen chat:")
        print(f"  TTFT    mediana={statistics.median(ttft):.2f}s   p90={pct(ttft, 0.9):.2f}s")
        print(f"  Total   mediana={statistics.median(total):.2f}s   p90={pct(total, 0.9):.2f}s")

        # Limpieza del historial que haya quedado persistido (_run solo guarda el
        # turno "assistant"; aquí no se llamó a process_chat_stream, así que no
        # hay turno "user" que borrar).
        from app.core.database import SessionLocal
        from app.models.financial import Conversation
        db = SessionLocal()
        try:
            deleted = (
                db.query(Conversation)
                .filter(Conversation.user_id == USER_ID, Conversation.created_at >= run_started)
                .delete()
            )
            db.commit()
            print(f"  (Limpieza: borradas {deleted} filas de Conversation.)")
        finally:
            db.close()

    await measure_voice()


if __name__ == "__main__":
    asyncio.run(main())
