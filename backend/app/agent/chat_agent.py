"""
Agente conversacional usando Groq (llama-3.3-70b-versatile) con tool calling.

Flujo en dos fases:
  Fase 1 — El modelo llama tools de datos (SQLite) en un bucle hasta tener toda
            la información que necesita.
  Fase 2 — Se le pide una respuesta estructurada en JSON (response_format json_object)
            con el texto de respuesta y los datos para el gráfico.

Separar las dos fases evita problemas de validación de Llama con present_answer
como tool y aprovecha el JSON mode nativo de Groq.
"""
import asyncio
import json

from groq import Groq

from app.agent.financial_mcp import (
    get_bizum_history,
    get_category_breakdown,
    get_expenses_by_category,
    get_financial_summary,
    get_largest_expenses,
    get_monthly_evolution,
    get_places_by_category,
    get_recent_transactions,
    get_spending_analysis,
    get_transaction_count,
    make_bizum_transfer,
    search_specific_transactions,
)
from app.core.config import settings
from app.schemas.financial import ChatResponse, ChartDataPoint, PendingBizumAction

SYSTEM_PROMPT = """Eres un asistente financiero personal que responde siempre en español.

Tienes acceso a herramientas que consultan la base de datos financiera del usuario.
Cuando el usuario haga una pregunta:
1. Usa la herramienta o herramientas necesarias para obtener los datos reales.
2. Cuando tengas toda la información, responde con un JSON estructurado.

Guía de herramientas:
- get_financial_summary        → resumen general (saldo, ingresos, gastos totales)
- get_expenses_by_category     → total gastado en una categoría concreta
- get_monthly_evolution        → evolución mes a mes de una categoría
- get_category_breakdown       → desglose de TODAS las categorías en un período
- get_transaction_count        → número de transacciones (visitas/compras)
- get_places_by_category       → establecimientos concretos visitados (ej: "¿a qué restaurantes he ido?")
- get_spending_analysis        → análisis de si el usuario gasta demasiado comparado con su promedio
- search_specific_transactions → busca por nombre de comercio (ej: "Netflix", "Zara")
- get_recent_transactions      → últimos movimientos cronológicos
- get_largest_expenses         → gastos individuales más grandes en un período
- make_bizum_transfer          → envía un Bizum; SIEMPRE pide confirmación antes de ejecutar
- get_bizum_history            → historial de Bizums enviados

Regla para Bizum: cuando el usuario pida enviar un Bizum, primero responde con los
detalles (destinatario, importe, concepto) y pregunta "¿Confirmas el envío?". Solo
llama a make_bizum_transfer cuando el usuario haya confirmado explícitamente.
"""

FINAL_PROMPT = """Ahora genera la respuesta final en JSON con esta estructura exacta:
{
  "response_text": "respuesta amigable en español para el usuario",
  "chart_type": "bar | line | pie | none",
  "chart_data": "[{\\"name\\":\\"X\\",\\"value\\":0}]",
  "chart_title": "título descriptivo del gráfico, o vacío si no hay gráfico",
  "pending_action": null
}

Guía chart_type:
- "bar"  → comparar valores (top categorías, ingresos vs gastos)
- "line" → evolución temporal (gastos mes a mes)
- "pie"  → distribución porcentual (desglose de categorías)
- "none" → solo texto (listas de lugares, análisis, respuestas simples)

chart_data es un string JSON array. Si chart_type es "none" usa chart_data="[]".

En "response_text" usa Markdown enriquecido:
- **negrita** para cifras y datos clave
- listas con viñetas (-) o numeradas cuando hay múltiples items
- tablas Markdown si hay datos comparativos
- `código` para valores monetarios exactos si procede
No uses markdown en chart_title.

CASO ESPECIAL — Confirmación de Bizum:
Si el usuario quiere enviar un Bizum pero aún no has ejecutado make_bizum_transfer
(es decir, necesitas confirmación), usa "pending_action" con este formato en lugar de preguntar por texto:
{
  "pending_action": {"type": "bizum_confirm", "recipient": "Nombre", "amount": 50.0, "concept": "Concepto"},
  "response_text": "",
  "chart_type": "none",
  "chart_data": "[]",
  "chart_title": ""
}
Cuando ya hayas ejecutado make_bizum_transfer, pon pending_action=null y describe el resultado en response_text.
"""

# ── Definición de tools en formato OpenAI ────────────────────────────────────

_PERIOD = ["current_month", "last_month", "last_3_months", "all_time"]
_CAT = (
    "Categoría del gasto: restaurantes, supermercado, transporte, "
    "alquiler, ocio, salud, ropa, servicios, salario."
)

TOOLS_SCHEMA = [
    {
        "type": "function",
        "function": {
            "name": "get_financial_summary",
            "description": "Resumen financiero: saldo total, ingresos, gastos y top categorías.",
            "parameters": {"type": "object", "properties": {"user_id": {"type": "integer"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_expenses_by_category",
            "description": "Total gastado en una categoría en un período.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": _CAT},
                    "period": {"type": "string", "enum": _PERIOD},
                    "user_id": {"type": "integer"},
                },
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_monthly_evolution",
            "description": "Evolución mensual de gastos en una categoría durante 12 meses.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": _CAT},
                    "user_id": {"type": "integer"},
                },
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_category_breakdown",
            "description": "Desglose de gastos por todas las categorías en un período.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {"type": "string", "enum": _PERIOD},
                    "user_id": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transaction_count",
            "description": "Cuenta transacciones en un período, opcionalmente por categoría.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": _CAT},
                    "period": {"type": "string", "enum": _PERIOD},
                    "user_id": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_places_by_category",
            "description": "Establecimientos visitados en una categoría con visitas y gasto total. Para '¿a qué restaurantes he ido?'",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": _CAT},
                    "period": {"type": "string", "enum": _PERIOD},
                    "user_id": {"type": "integer"},
                },
                "required": ["category"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_spending_analysis",
            "description": "Analiza si el usuario gasta demasiado comparando mes actual con promedio histórico.",
            "parameters": {
                "type": "object",
                "properties": {"user_id": {"type": "integer"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_specific_transactions",
            "description": "Busca transacciones por nombre de comercio o concepto (ej: 'Netflix', 'Zara').",
            "parameters": {
                "type": "object",
                "properties": {
                    "keyword": {"type": "string"},
                    "limit": {"type": "integer"},
                    "user_id": {"type": "integer"},
                },
                "required": ["keyword"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_transactions",
            "description": "Últimos movimientos del usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "user_id": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_largest_expenses",
            "description": "Gastos individuales más grandes en un período.",
            "parameters": {
                "type": "object",
                "properties": {
                    "period": {"type": "string", "enum": _PERIOD},
                    "limit": {"type": "integer"},
                    "user_id": {"type": "integer"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "make_bizum_transfer",
            "description": (
                "Ejecuta una transferencia Bizum desde la cuenta corriente del usuario. "
                "IMPORTANTE: DEBES confirmar con el usuario el destinatario y el importe "
                "ANTES de llamar a esta función. Si no hay confirmación explícita, pregunta primero."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {"type": "string", "description": "Nombre o teléfono del destinatario."},
                    "amount": {"type": "number", "description": "Cantidad en euros. Máximo 2000€."},
                    "concept": {"type": "string", "description": "Concepto o motivo del Bizum."},
                    "user_id": {"type": "integer"},
                },
                "required": ["recipient", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_bizum_history",
            "description": "Historial de transferencias Bizum realizadas por el usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {"type": "integer"},
                    "user_id": {"type": "integer"},
                },
            },
        },
    },
]

TOOL_MAP = {
    "get_financial_summary": get_financial_summary,
    "get_expenses_by_category": get_expenses_by_category,
    "get_monthly_evolution": get_monthly_evolution,
    "get_category_breakdown": get_category_breakdown,
    "get_transaction_count": get_transaction_count,
    "get_places_by_category": get_places_by_category,
    "get_spending_analysis": get_spending_analysis,
    "search_specific_transactions": search_specific_transactions,
    "get_recent_transactions": get_recent_transactions,
    "get_largest_expenses": get_largest_expenses,
    "make_bizum_transfer": make_bizum_transfer,
    "get_bizum_history": get_bizum_history,
}


# ── Bucle agente ──────────────────────────────────────────────────────────────

def _run_chat(message: str, user_id: int, history: list[dict]) -> ChatResponse:
    client = Groq(api_key=settings.groq_api_key)

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Inyectar historial previo (solo pares user/assistant en texto plano)
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": f"[user_id={user_id}] {message}"})

    # ── Fase 1: recopilación de datos con tools ───────────────────────────────
    for _ in range(7):
        try:
            response = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=messages,
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
            )
        except Exception as e:
            err_str = str(e)
            # El modelo falló al formatear la llamada → salir con los datos que tengamos
            if "tool_use_failed" in err_str or "tool call validation" in err_str:
                break
            raise

        assistant_msg = response.choices[0].message
        tool_calls = assistant_msg.tool_calls or []

        assistant_dict: dict = {
            "role": "assistant",
            "content": assistant_msg.content or "",
        }
        if tool_calls:
            assistant_dict["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                }
                for tc in tool_calls
            ]
        messages.append(assistant_dict)

        if not tool_calls:
            break

        for tc in tool_calls:
            name = tc.function.name
            args = json.loads(tc.function.arguments)
            # Coercionar enteros que el modelo a veces envía como string
            for key in ("user_id", "limit"):
                if key in args and isinstance(args[key], str):
                    try:
                        args[key] = int(args[key])
                    except ValueError:
                        pass
            func = TOOL_MAP.get(name)
            result = func(**args) if func else {"error": f"tool '{name}' not found"}
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    # ── Fase 2: respuesta estructurada en JSON ────────────────────────────────
    messages.append({"role": "user", "content": FINAL_PROMPT})

    final_response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=messages,
        response_format={"type": "json_object"},
    )

    raw = final_response.choices[0].message.content or "{}"
    data = json.loads(raw)

    chart_type = data.get("chart_type", "none")
    raw_data = data.get("chart_data", "[]")
    chart_title = data.get("chart_title") or None

    try:
        data_list = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
        if not isinstance(data_list, list):
            data_list = []
    except (json.JSONDecodeError, TypeError):
        data_list = []

    # Normalizar claves: el modelo a veces usa month/total, category/amount, etc.
    _NAME_KEYS = ("name", "month", "categoria", "category", "nombre", "label")
    _VALUE_KEYS = ("value", "total", "amount", "monto", "valor")

    def _extract(d: dict, keys: tuple) -> str | float | None:
        for k in keys:
            if k in d:
                return d[k]
        return None

    normalized = []
    for d in data_list:
        n = _extract(d, _NAME_KEYS)
        v = _extract(d, _VALUE_KEYS)
        if n is not None and v is not None:
            try:
                normalized.append(ChartDataPoint(name=str(n), value=float(v)))
            except (TypeError, ValueError):
                pass

    chart_data = normalized or None

    pending_action = None
    raw_pending = data.get("pending_action")
    if isinstance(raw_pending, dict) and raw_pending.get("type") == "bizum_confirm":
        try:
            pending_action = PendingBizumAction(
                type="bizum_confirm",
                recipient=str(raw_pending["recipient"]),
                amount=float(raw_pending["amount"]),
                concept=str(raw_pending.get("concept", "Bizum")),
            )
        except (KeyError, ValueError, TypeError):
            pass

    return ChatResponse(
        response=data.get("response_text", ""),
        chart_type=chart_type if chart_type != "none" else None,
        chart_data=chart_data,
        chart_title=chart_title,
        pending_action=pending_action,
    )


async def process_chat(message: str, user_id: int = 1, history: list[dict] | None = None) -> ChatResponse:
    if not settings.groq_api_key:
        return ChatResponse(
            response="API key de Groq no configurada. Añade GROQ_API_KEY al archivo backend/.env"
        )

    try:
        return await asyncio.to_thread(_run_chat, message, user_id, history or [])
    except Exception as e:
        err = str(e)
        if "429" in err or "rate_limit" in err.lower():
            return ChatResponse(
                response="El modelo está ocupado ahora mismo. Espera unos segundos e inténtalo de nuevo."
            )
        if "401" in err or "invalid_api_key" in err.lower():
            return ChatResponse(
                response="API key de Groq inválida. Revisa el archivo backend/.env"
            )
        return ChatResponse(response=f"Error inesperado: {err[:200]}")
