"""
Agente conversacional que combina:
  - MCP (tools financieros definidos en financial_mcp.py)
  - Gemini (decide qué tool llamar y genera la respuesta)

Flujo de una petición:
  1. Se envía el mensaje del usuario a Gemini junto con las definiciones de tools.
  2. Gemini responde con una llamada a tool (function_call).
  3. El agente ejecuta la función Python correspondiente (consulta SQLite).
  4. El resultado se devuelve a Gemini como function_response.
  5. Gemini llama a present_answer con la respuesta estructurada final.
  6. El agente extrae chart_type + chart_data y construye el ChatResponse.
"""
import asyncio
import json

from google import genai
from google.genai import types

from app.agent.financial_mcp import (
    get_category_breakdown,
    get_expenses_by_category,
    get_financial_summary,
    get_monthly_evolution,
    get_transaction_count,
)
from app.core.config import settings
from app.schemas.financial import ChatResponse, ChartDataPoint

SYSTEM_PROMPT = """Eres un asistente financiero personal que responde siempre en español.

Tienes acceso a herramientas que consultan la base de datos financiera del usuario.
Cuando el usuario haga una pregunta:
1. Usa la herramienta más adecuada para obtener los datos reales.
2. Analiza los datos recibidos.
3. Llama SIEMPRE a present_answer para entregar la respuesta final estructurada.

Guía para el campo chart_type en present_answer:
- "bar"  → comparar dos o más valores (ej: ingresos vs gastos)
- "line" → evolución a lo largo del tiempo (ej: gastos mensuales)
- "pie"  → distribución porcentual (ej: desglose por categorías)
- "none" → respuesta solo de texto, sin gráfico

chart_data debe ser un JSON array: [{"name": "...", "value": número}, ...]
Si no hay gráfico, usa chart_data="[]".
"""


# ── Tool especial: salida estructurada ────────────────────────────────────────

def present_answer(
    response_text: str,
    chart_type: str,
    chart_data: str,
    chart_title: str,
) -> dict:
    """Presenta la respuesta final al usuario. DEBES llamar a esta función al terminar.

    Args:
        response_text: Respuesta en lenguaje natural para mostrar en el chat.
        chart_type: Tipo de gráfico — 'bar', 'line', 'pie' o 'none'.
        chart_data: JSON array con los datos del gráfico: '[{"name":"X","value":0}]'
        chart_title: Título descriptivo del gráfico (vacío si chart_type es 'none').
    """
    return {
        "response_text": response_text,
        "chart_type": chart_type,
        "chart_data": chart_data,
        "chart_title": chart_title,
    }


TOOL_MAP = {
    "get_financial_summary": get_financial_summary,
    "get_expenses_by_category": get_expenses_by_category,
    "get_monthly_evolution": get_monthly_evolution,
    "get_category_breakdown": get_category_breakdown,
    "get_transaction_count": get_transaction_count,
    "present_answer": present_answer,
}

ALL_TOOLS = list(TOOL_MAP.values())


# ── Bucle agente ──────────────────────────────────────────────────────────────

def _run_chat(message: str, user_id: int) -> ChatResponse:
    """Ejecuta el bucle agente de forma síncrona (se llama desde asyncio.to_thread)."""
    client = genai.Client(api_key=settings.google_api_key)

    # Desactivamos AFC (Automatic Function Calling) para gestionar el bucle manualmente.
    # Esto nos permite capturar el resultado de present_answer y construir el ChatResponse.
    config = types.GenerateContentConfig(
        tools=ALL_TOOLS,
        system_instruction=SYSTEM_PROMPT,
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    chat = client.chats.create(model="gemini-2.5-flash", config=config)

    full_message = f"[user_id={user_id}] {message}"
    response = chat.send_message(full_message)

    final_answer: dict | None = None

    for _ in range(6):
        parts = response.candidates[0].content.parts if (
            response.candidates and response.candidates[0].content
        ) else []

        fn_calls = [p.function_call for p in (parts or []) if p.function_call]

        if not fn_calls:
            break

        result_parts = []
        for fc in fn_calls:
            func = TOOL_MAP.get(fc.name)
            result = func(**dict(fc.args)) if func else {"error": f"tool '{fc.name}' not found"}

            if fc.name == "present_answer":
                final_answer = result

            result_parts.append(
                types.Part.from_function_response(
                    name=fc.name,
                    response={"result": json.dumps(result, ensure_ascii=False)},
                )
            )

        if final_answer:
            break

        response = chat.send_message(result_parts)

    # ── Construir ChatResponse ────────────────────────────────────────────────
    if final_answer:
        chart_type = final_answer.get("chart_type", "none")
        raw_data = final_answer.get("chart_data", "[]")
        chart_title = final_answer.get("chart_title") or None

        try:
            data_list = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
        except (json.JSONDecodeError, TypeError):
            data_list = []

        chart_data = (
            [ChartDataPoint(name=str(d["name"]), value=float(d["value"])) for d in data_list]
            if data_list else None
        )

        return ChatResponse(
            response=final_answer.get("response_text", ""),
            chart_type=chart_type if chart_type != "none" else None,
            chart_data=chart_data,
            chart_title=chart_title,
        )

    # Fallback: texto plano si Gemini no llamó a present_answer
    parts = response.candidates[0].content.parts if (
        response.candidates and response.candidates[0].content
    ) else []
    text = "".join(p.text for p in (parts or []) if hasattr(p, "text") and p.text)
    return ChatResponse(response=text or "No pude procesar tu consulta. Inténtalo de nuevo.")


async def process_chat(message: str, user_id: int = 1) -> ChatResponse:
    if not settings.google_api_key:
        return ChatResponse(
            response="API key de Google no configurada. Añade GOOGLE_API_KEY al archivo backend/.env"
        )

    # Intenta con Gemini hasta 2 veces (con pausa entre intentos)
    last_err = ""
    for attempt in range(2):
        try:
            return await asyncio.to_thread(_run_chat, message, user_id)
        except Exception as e:
            last_err = str(e)
            is_rate_limit = "429" in last_err or "RESOURCE_EXHAUSTED" in last_err
            if is_rate_limit and attempt == 0:
                await asyncio.sleep(25)  # espera el tiempo que pide Google (~20s)
                continue
            break

    # Gemini no disponible → fallback al servicio de keywords
    if "429" in last_err or "RESOURCE_EXHAUSTED" in last_err:
        from app.core.database import SessionLocal
        from app.services.query_service import process_chat as keyword_chat
        db = SessionLocal()
        try:
            result = keyword_chat(db, message, user_id)
            result.response = "⚡ (modo básico) " + result.response
            return result
        finally:
            db.close()

    if "403" in last_err or "API_KEY" in last_err.upper():
        return ChatResponse(
            response="API key de Google inválida o sin permisos. Revisa el archivo backend/.env"
        )
    return ChatResponse(response=f"Error inesperado: {last_err[:200]}")
