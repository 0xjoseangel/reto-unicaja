"""
Agente conversacional multi-proveedor (Claude / Ollama / Groq) con tool calling.

Flujo en dos fases:
  Fase 1 — El modelo llama tools de datos (SQLite) en un bucle hasta tener toda
            la información que necesita.
  Fase 2 — Se le pide una respuesta estructurada en JSON con el texto de respuesta
            y los datos para el gráfico. Claude no soporta response_format json_object
            así que se usa FINAL_PROMPT con instrucción explícita de devolver JSON.
"""
import asyncio
import inspect
import json
import os

import litellm

from app.agent.financial_mcp import (
    add_investment,
    calculate_budget_distribution,
    calculate_compound_interest,
    calculate_loan,
    calculate_mortgage,
    calculate_savings_goal,
    get_account_balances,
    get_asset_details,
    get_bizum_history,
    get_category_breakdown,
    get_expenses_by_category,
    get_financial_summary,
    get_income_by_period,
    get_largest_expenses,
    get_market_overview,
    get_monthly_evolution,
    get_places_by_category,
    get_portfolio,
    get_recent_transactions,
    get_spending_analysis,
    get_transaction_count,
    make_bizum_transfer,
    search_specific_transactions,
)
from app.core.config import settings
from app.schemas.financial import (
    ChatResponse,
    ChartDataPoint,
    PendingBizumAction,
    PendingInvestmentAction,
)

SYSTEM_PROMPT = """Eres un asistente financiero personal. Responde siempre en español.

ESTILO DE RESPUESTA (obligatorio):
- Sin emojis. Nunca uses emojis en tus respuestas.
- Conciso y directo. Sin cabeceras innecesarias ni secciones redundantes.
- **Negrita** solo para cifras y datos clave.
- Listas con (-) para múltiples items. Tablas Markdown para comparativas.
- Tono profesional pero cercano.

HERRAMIENTAS DISPONIBLES:
- get_financial_summary        → saldo total, ingresos/gastos históricos, top categorías
- get_account_balances         → saldo por cuenta (corriente, ahorro)
- get_income_by_period         → ingresos en un período
- get_expenses_by_category     → gasto en una categoría y período
- get_monthly_evolution        → evolución mensual de una categoría (12 meses)
- get_category_breakdown       → desglose de todas las categorías en un período
- get_transaction_count        → número de transacciones
- get_places_by_category       → establecimientos visitados por categoría
- get_spending_analysis        → comparativa mes actual vs promedio histórico
- search_specific_transactions → buscar por comercio o concepto
- get_recent_transactions      → últimos movimientos
- get_largest_expenses         → gastos más grandes de un período
- make_bizum_transfer          → ejecuta Bizum (solo tras confirmación explícita)
- get_bizum_history            → historial de Bizums
- calculate_mortgage           → cuota e amortización de hipoteca
- calculate_loan               → cuota de préstamo personal/coche
- calculate_compound_interest  → proyección de ahorro con interés compuesto
- calculate_savings_goal       → tiempo para alcanzar un objetivo de ahorro
- calculate_budget_distribution → regla 50/30/20
- get_portfolio                → cartera de inversiones con precios reales y rentabilidad
- get_asset_details            → datos de un activo (precio, PER, dividendo, sector)
- get_market_overview          → índices globales (S&P500, IBEX, Nasdaq, Oro)
- add_investment               → registra una compra en cartera (solo tras confirmación explícita)

REGLAS CRÍTICAS:
- Nunca hagas cálculos matemáticos tú mismo. Usa siempre la herramienta correspondiente.
- Para cualquier acción de Bizum: devuelve pending_action bizum_confirm, NO llames a make_bizum_transfer hasta recibir confirmación explícita.
- Para registrar una inversión: devuelve pending_action investment_confirm, NO llames a add_investment hasta recibir confirmación explícita. Solo una inversión por pending_action.
- Si el resultado de make_bizum_transfer incluye "nuevo_saldo_total", usa ese valor como saldo actualizado.
- Para gráficos: cartera → pie (valor actual por activo); categorías → pie o bar; evolución temporal → line.

FORMATO DE SALIDA (Fase 2 — al generar la respuesta):
Escribe el texto de respuesta y termina SIEMPRE con este bloque exacto:
---JSON---
{"chart_type":"none","chart_data":[],"chart_title":"","pending_action":null}

Valores de chart_type: "bar" (comparar), "line" (temporal), "pie" (distribución), "none" (sin gráfico).
chart_data: [{"name":"X","value":0},...] — solo si hay gráfico.

Para Bizum sin confirmar, texto vacío y:
---JSON---
{"chart_type":"none","chart_data":[],"chart_title":"","pending_action":{"type":"bizum_confirm","recipient":"Nombre","amount":50.0,"concept":"Concepto"}}

Para inversión sin confirmar (UNA sola inversión, ticker real de yfinance, shares > 0), texto vacío y:
---JSON---
{"chart_type":"none","chart_data":[],"chart_title":"","pending_action":{"type":"investment_confirm","ticker":"AAPL","nombre":"Apple Inc.","shares":5,"avg_purchase_price":150.00,"investment_type":"accion"}}
"""

FINAL_PROMPT = """Genera la respuesta final en JSON (sin bloques de código):
{"response_text":"...","chart_type":"none","chart_data":"[]","chart_title":"","pending_action":null}

response_text en español, sin emojis, con **negrita** para cifras, listas (-) y tablas si procede.
chart_data es un string JSON array: "[{\\"name\\":\\"X\\",\\"value\\":0}]"
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
            "description": "Resumen financiero: saldo total de todas las cuentas, ingresos totales históricos, gastos totales históricos y top categorías.",
            "parameters": {"type": "object", "properties": {"user_id": {"type": "integer"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_account_balances",
            "description": "Saldo de cada cuenta por separado (corriente, ahorro, etc.) y saldo total. Úsalo cuando el usuario pregunte por una cuenta específica o cuando necesites distinguir entre cuentas.",
            "parameters": {"type": "object", "properties": {"user_id": {"type": "integer"}}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_income_by_period",
            "description": "Ingresos del usuario en un período concreto (nómina, freelance, etc.). Úsalo para '¿cuánto he cobrado este mes?', '¿cuál es mi salario?', '¿cuánto ingresé el mes pasado?'.",
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
    {
        "type": "function",
        "function": {
            "name": "calculate_mortgage",
            "description": "Cuota mensual y amortización de hipoteca. Úsalo SIEMPRE para hipotecas. Nunca calcules tú mismo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "property_price": {"type": "number", "description": "Precio total del inmueble en euros."},
                    "deposit": {"type": "number", "description": "Entrada inicial en euros."},
                    "annual_rate_percent": {"type": "number", "description": "Tipo de interés anual en % (ej: 4.0)."},
                    "years": {"type": "integer", "description": "Plazo en años."},
                },
                "required": ["property_price", "deposit", "annual_rate_percent", "years"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_loan",
            "description": "Cuota mensual de préstamo personal, coche u otra financiación sin inmueble. Nunca calcules tú mismo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "principal": {"type": "number", "description": "Capital prestado en euros."},
                    "annual_rate_percent": {"type": "number", "description": "Tipo de interés anual en %."},
                    "years": {"type": "integer", "description": "Plazo en años."},
                },
                "required": ["principal", "annual_rate_percent", "years"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_compound_interest",
            "description": "Proyección de ahorro o inversión con interés compuesto y aportaciones mensuales. Nunca calcules tú mismo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "initial_amount": {"type": "number", "description": "Capital inicial en euros (puede ser 0)."},
                    "monthly_contribution": {"type": "number", "description": "Aportación mensual en euros (puede ser 0)."},
                    "annual_rate_percent": {"type": "number", "description": "Rentabilidad anual esperada en %."},
                    "years": {"type": "integer", "description": "Horizonte temporal en años."},
                },
                "required": ["initial_amount", "monthly_contribution", "annual_rate_percent", "years"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_savings_goal",
            "description": "Tiempo necesario para ahorrar una cantidad fija guardando X€/mes. Nunca calcules tú mismo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_amount": {"type": "number", "description": "Objetivo de ahorro en euros."},
                    "monthly_savings": {"type": "number", "description": "Ahorro mensual en euros."},
                    "annual_rate_percent": {"type": "number", "description": "Rentabilidad anual en % (0 si no hay intereses)."},
                },
                "required": ["goal_amount", "monthly_savings"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_budget_distribution",
            "description": "Distribuye ingresos mensuales con la regla 50/30/20 (necesidades/ocio/ahorro). Nunca calcules tú mismo.",
            "parameters": {
                "type": "object",
                "properties": {
                    "monthly_income": {"type": "number", "description": "Ingresos mensuales netos en euros."},
                },
                "required": ["monthly_income"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_portfolio",
            "description": "Cartera de inversiones del usuario con precios actualizados del mercado y rentabilidad. Para '¿cómo va mi cartera?', '¿cuánto vale mi inversión?', '¿cuánto he ganado o perdido?'.",
            "parameters": {
                "type": "object",
                "properties": {"user_id": {"type": "integer"}},
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_asset_details",
            "description": "Información detallada de un activo: precio actual, variación del día, PER, dividendo, rango 52 semanas, sector. Para 'dame info de Apple', '¿cómo está Tesla?', '¿cuál es el PER de Inditex?'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Símbolo del activo (ej: AAPL, SAN.MC, IWDA.AS)."},
                },
                "required": ["ticker"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_market_overview",
            "description": "Estado actual de los principales índices bursátiles: S&P 500, Nasdaq, IBEX 35, Euro Stoxx 50, Oro. Para '¿cómo están los mercados hoy?', '¿sube o baja la bolsa?'.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "add_investment",
            "description": (
                "Registra una compra de activo financiero en la cartera del usuario. "
                "IMPORTANTE: DEBES pedir confirmación al usuario antes de llamar a esta función. "
                "Solo llámala cuando el usuario haya confirmado explícitamente."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "user_id": {"type": "integer"},
                    "ticker": {"type": "string", "description": "Símbolo del activo (ej: AAPL, VOO, SAN.MC)."},
                    "shares": {"type": "number", "description": "Número de acciones/participaciones compradas."},
                    "avg_purchase_price": {"type": "number", "description": "Precio de compra por acción."},
                    "investment_type": {"type": "string", "enum": ["accion", "etf", "fondo_indexado"]},
                },
                "required": ["user_id", "ticker", "shares", "avg_purchase_price"],
            },
        },
    },
]

TOOL_MAP = {
    "get_financial_summary": get_financial_summary,
    "get_account_balances": get_account_balances,
    "get_income_by_period": get_income_by_period,
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
    "calculate_mortgage": calculate_mortgage,
    "calculate_loan": calculate_loan,
    "calculate_compound_interest": calculate_compound_interest,
    "calculate_savings_goal": calculate_savings_goal,
    "calculate_budget_distribution": calculate_budget_distribution,
    "get_portfolio": get_portfolio,
    "get_asset_details": get_asset_details,
    "get_market_overview": get_market_overview,
    "add_investment": add_investment,
}


# ── Cliente litellm ───────────────────────────────────────────────────────────

def _build_model() -> str:
    if settings.ai_provider == "claude":
        os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
        return f"anthropic/{settings.claude_model}"
    if settings.ai_provider == "ollama":
        os.environ["OLLAMA_API_BASE"] = settings.ollama_base_url
        return f"ollama/{settings.ollama_model}"
    # groq (legado)
    os.environ["GROQ_API_KEY"] = settings.groq_api_key
    return "groq/llama-3.3-70b-versatile"


# ── Bucle agente ──────────────────────────────────────────────────────────────

def _run_chat(message: str, user_id: int, history: list[dict]) -> ChatResponse:
    model = _build_model()

    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]

    # Inyectar historial previo (solo pares user/assistant en texto plano)
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    messages.append({"role": "user", "content": f"[user_id={user_id}] {message}"})

    # ── Fase 1: recopilación de datos con tools ───────────────────────────────
    for _ in range(7):
        try:
            response = litellm.completion(
                model=model,
                messages=messages,
                tools=TOOLS_SCHEMA,
                tool_choice="auto",
            )
        except Exception as e:
            err_str = str(e)
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
            if func:
                # Filtrar parámetros que el modelo haya inventado y no existan en la firma
                valid = inspect.signature(func).parameters
                args = {k: v for k, v in args.items() if k in valid}
                result = func(**args)
            else:
                result = {"error": f"tool '{name}' not found"}
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    # ── Fase 2: respuesta estructurada en JSON ────────────────────────────────
    messages.append({"role": "user", "content": FINAL_PROMPT})

    kwargs: dict = {"model": model, "messages": messages}
    # Claude no soporta response_format; para Groq/Ollama lo mantenemos como ayuda
    if settings.ai_provider != "claude":
        kwargs["response_format"] = {"type": "json_object"}

    final_response = litellm.completion(**kwargs)

    raw = final_response.choices[0].message.content or "{}"

    # Limpiar posibles bloques de código markdown que algunos modelos añaden
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

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
    if isinstance(raw_pending, dict):
        action_type = raw_pending.get("type")
        try:
            if action_type == "bizum_confirm":
                pending_action = PendingBizumAction(
                    type="bizum_confirm",
                    recipient=str(raw_pending["recipient"]),
                    amount=float(raw_pending["amount"]),
                    concept=str(raw_pending.get("concept", "Bizum")),
                )
            elif action_type == "investment_confirm":
                pending_action = PendingInvestmentAction(
                    type="investment_confirm",
                    ticker=str(raw_pending["ticker"]),
                    nombre=str(raw_pending.get("nombre", raw_pending["ticker"])),
                    shares=float(raw_pending["shares"]),
                    avg_purchase_price=float(raw_pending["avg_purchase_price"]),
                    investment_type=str(raw_pending.get("investment_type", "accion")),
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


# ── Prompts para streaming ────────────────────────────────────────────────────

_MARKER = "\n---JSON---\n"

COMBINED_PROMPT = "Escribe ahora la respuesta al usuario."

COMBINED_PROMPT_VOICE = """Escribe ahora la respuesta al usuario en MODO VOZ.

REGLAS ESTRICTAS PARA MODO VOZ:
- Responde de forma completamente conversacional, como si hablaras en voz alta.
- PROHIBIDO usar markdown: sin asteriscos, sin guiones de lista, sin almohadillas, sin tablas, sin comillas de código.
- Las cifras exprésalas de forma natural: "dos mil trescientos euros", "un 8 por ciento".
- Máximo 3 o 4 frases. La respuesta se leerá en voz alta: que sea breve y fluida.
- Si hay varios puntos, únelos con "y", "además" o "por otro lado" en lugar de hacer lista.
- El bloque JSON al final es obligatorio igual que siempre (para pintar el gráfico en pantalla).

Ejemplo correcto: "Tu cartera vale doce mil euros, con una ganancia total del ocho por ciento. El activo que mejor va es Apple, con un veinte por ciento de rentabilidad."
Ejemplo incorrecto: "**Cartera:** - Apple: +20% - Microsoft: +5%"
"""


async def _run_tool_loop_async(messages: list[dict], model: str) -> list[dict]:
    """Phase 1: tool-calling loop ejecutado en un thread. Devuelve los mensajes actualizados."""
    def _sync() -> list[dict]:
        msgs = list(messages)
        for _ in range(7):
            try:
                response = litellm.completion(
                    model=model, messages=msgs, tools=TOOLS_SCHEMA, tool_choice="auto",
                )
            except Exception as e:
                err_str = str(e)
                if "tool_use_failed" in err_str or "tool call validation" in err_str:
                    break
                raise

            assistant_msg = response.choices[0].message
            tool_calls = assistant_msg.tool_calls or []

            assistant_dict: dict = {"role": "assistant", "content": assistant_msg.content or ""}
            if tool_calls:
                assistant_dict["tool_calls"] = [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in tool_calls
                ]
            msgs.append(assistant_dict)

            if not tool_calls:
                break

            for tc in tool_calls:
                name = tc.function.name
                args = json.loads(tc.function.arguments)
                for key in ("user_id", "limit"):
                    if key in args and isinstance(args[key], str):
                        try:
                            args[key] = int(args[key])
                        except ValueError:
                            pass
                func = TOOL_MAP.get(name)
                if func:
                    valid = inspect.signature(func).parameters
                    args = {k: v for k, v in args.items() if k in valid}
                    result = func(**args)
                else:
                    result = {"error": f"tool '{name}' not found"}
                msgs.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })
        return msgs

    return await asyncio.to_thread(_sync)


def _parse_chart(raw_chart: list | str) -> list[dict]:
    _NAME_KEYS = ("name", "month", "categoria", "category", "nombre", "label")
    _VALUE_KEYS = ("value", "total", "amount", "monto", "valor")
    if isinstance(raw_chart, str):
        try:
            raw_chart = json.loads(raw_chart)
        except Exception:
            return []
    normalized = []
    for item in (raw_chart if isinstance(raw_chart, list) else []):
        if not isinstance(item, dict):
            continue
        n = next((item[k] for k in _NAME_KEYS if k in item), None)
        v = next((item[k] for k in _VALUE_KEYS if k in item), None)
        if n is not None and v is not None:
            try:
                normalized.append({"name": str(n), "value": float(v)})
            except (TypeError, ValueError):
                pass
    return normalized


async def process_chat_stream(message: str, user_id: int = 1, history: list[dict] | None = None, voice_mode: bool = False):
    """Async generator — SSE: tokens de texto + evento done. Una sola llamada al modelo en Phase 2."""
    if settings.ai_provider == "claude" and not settings.anthropic_api_key:
        yield f"data: {json.dumps({'type': 'error', 'text': 'API key de Anthropic no configurada'})}\n\n"
        return
    if settings.ai_provider == "groq" and not settings.groq_api_key:
        yield f"data: {json.dumps({'type': 'error', 'text': 'API key de Groq no configurada'})}\n\n"
        return

    model = _build_model()
    messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
    for msg in (history or []):
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": f"[user_id={user_id}] {message}"})

    # Phase 1: tool-calling loop en thread
    try:
        messages = await _run_tool_loop_async(messages, model)
    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'text': str(e)[:200]})}\n\n"
        return

    # Phase 2: streaming combinado — texto + separador + JSON en una sola llamada
    prompt = COMBINED_PROMPT_VOICE if voice_mode else COMBINED_PROMPT
    combined_messages = messages + [{"role": "user", "content": prompt}]
    accumulated = ""   # todo el contenido acumulado del stream
    text_yielded = 0   # cuántos caracteres de texto hemos enviado ya
    json_found = False
    json_raw = ""

    try:
        stream = await litellm.acompletion(model=model, messages=combined_messages, stream=True)
        async for chunk in stream:
            delta = chunk.choices[0].delta.content or ""
            if not delta:
                continue
            accumulated += delta

            if json_found:
                # Ya encontramos el marcador, acumulamos el JSON
                json_raw += delta
                continue

            marker_idx = accumulated.find(_MARKER)
            if marker_idx != -1:
                # Encontramos el marcador — enviamos el texto que quedaba pendiente
                text_before = accumulated[:marker_idx]
                pending_text = text_before[text_yielded:]
                if pending_text:
                    yield f"data: {json.dumps({'type': 'token', 'text': pending_text}, ensure_ascii=False)}\n\n"
                json_found = True
                json_raw = accumulated[marker_idx + len(_MARKER):]
            else:
                # Todavía no hay marcador — enviamos lo que es seguro
                # Guardamos los últimos len(_MARKER) chars por si el marcador está partido entre chunks
                safe_end = max(text_yielded, len(accumulated) - len(_MARKER))
                if safe_end > text_yielded:
                    pending_text = accumulated[text_yielded:safe_end]
                    yield f"data: {json.dumps({'type': 'token', 'text': pending_text}, ensure_ascii=False)}\n\n"
                    text_yielded = safe_end

        # Stream terminado — enviar texto restante si el marcador nunca apareció
        if not json_found:
            remaining = accumulated[text_yielded:]
            if remaining:
                yield f"data: {json.dumps({'type': 'token', 'text': remaining}, ensure_ascii=False)}\n\n"

    except Exception as e:
        yield f"data: {json.dumps({'type': 'error', 'text': str(e)[:200]})}\n\n"
        return

    # Parsear JSON del gráfico
    raw = json_raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    try:
        data = json.loads(raw)
    except Exception:
        data = {}

    chart_type = data.get("chart_type", "none")
    normalized = _parse_chart(data.get("chart_data", []))

    done_event = {
        "type": "done",
        "chart_type": chart_type if chart_type != "none" else None,
        "chart_data": normalized if normalized else None,
        "chart_title": data.get("chart_title") or None,
        "pending_action": data.get("pending_action"),
    }
    yield f"data: {json.dumps(done_event, ensure_ascii=False)}\n\n"


async def process_chat(message: str, user_id: int = 1, history: list[dict] | None = None) -> ChatResponse:
    if settings.ai_provider == "claude" and not settings.anthropic_api_key:
        return ChatResponse(
            response="API key de Anthropic no configurada. Añade ANTHROPIC_API_KEY al archivo backend/.env"
        )
    if settings.ai_provider == "groq" and not settings.groq_api_key:
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
        if "401" in err or "invalid_api_key" in err.lower() or "authentication" in err.lower():
            return ChatResponse(
                response="API key inválida. Revisa el archivo backend/.env"
            )
        return ChatResponse(response=f"Error inesperado: {err[:200]}")
