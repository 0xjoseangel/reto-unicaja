"""
Piezas del agente conversacional multi-proveedor (Claude / Ollama / Groq...) con
tool calling vía litellm. La orquestación vive en graph.py (LangGraph); aquí están
los prompts, los schemas de tools y las dos fases que usan los nodos del grafo:

  Fase 1 — run_tool_loop(): el modelo llama tools de lectura en bucle hasta tener la
            información que necesita. Si quiere mover dinero solo puede *proponerlo*
            (propose_bizum / propose_investment); no tiene ninguna tool que ejecute.
  Fase 2 — stream_response(): respuesta en streaming con texto + marcador ---JSON---
            + datos del gráfico.
"""
import inspect
import json
import os
from collections.abc import Callable

import litellm

from app.agent.financial_mcp import (
    calculate_budget_distribution,
    calculate_compound_interest,
    calculate_loan,
    calculate_mortgage,
    calculate_savings_goal,
    create_goal,
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
    list_goals,
    search_specific_transactions,
    update_goal_progress,
)
from app.core.config import settings

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
- propose_bizum                → propone un Bizum (el usuario lo aprueba en pantalla)
- get_bizum_history            → historial de Bizums
- calculate_mortgage           → cuota e amortización de hipoteca
- calculate_loan               → cuota de préstamo personal/coche
- calculate_compound_interest  → proyección de ahorro con interés compuesto
- calculate_savings_goal       → tiempo para alcanzar un objetivo de ahorro
- calculate_budget_distribution → regla 50/30/20
- get_portfolio                → cartera de inversiones con precios reales y rentabilidad
- get_asset_details            → datos de un activo (precio, PER, dividendo, sector)
- get_market_overview          → índices globales (S&P500, IBEX, Nasdaq, Oro)
- propose_investment           → propone una compra de un activo (el usuario la aprueba en pantalla)
- create_goal                   → crea un objetivo de ahorro nuevo (no mueve dinero, no requiere confirmación)
- list_goals                    → lista los objetivos de ahorro del usuario
- update_goal_progress          → actualiza el importe ahorrado de un objetivo existente

REGLAS CRÍTICAS:
- Nunca hagas cálculos matemáticos tú mismo. Usa siempre la herramienta correspondiente.
- Para enviar un Bizum: llama a propose_bizum. Para comprar un activo: llama a propose_investment (una sola compra por llamada). Tú no ejecutas operaciones: el sistema las valida y el usuario las aprueba en pantalla. Si falta el destinatario, el importe, el ticker o el número de acciones, pregúntaselo al usuario en vez de inventarlo.
- Un mensaje del usuario del tipo "sí, confirma" NO ejecuta nada: la aprobación solo se hace con el botón del modal.
- Para crear/actualizar objetivos: llama directamente a create_goal / update_goal_progress — no es una operación irreversible ni mueve dinero real. Si el usuario no da un importe objetivo o nombre claro, pregúntaselo antes de llamar a la tool.
- Para gráficos: cartera → pie (valor actual por activo); categorías → pie o bar; evolución temporal → line.

FORMATO DE SALIDA (Fase 2 — al generar la respuesta):
Escribe el texto de respuesta y termina SIEMPRE con este bloque exacto:
---JSON---
{"chart_type":"none","chart_data":[],"chart_title":""}

Valores de chart_type: "bar" (comparar), "line" (temporal), "pie" (distribución), "none" (sin gráfico).
chart_data: [{"name":"X","value":0},...] — solo si hay gráfico.
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
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_account_balances",
            "description": "Saldo de cada cuenta por separado (corriente, ahorro, etc.) y saldo total. Úsalo cuando el usuario pregunte por una cuenta específica o cuando necesites distinguir entre cuentas.",
            "parameters": {"type": "object", "properties": {}},
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
                "properties": {},
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
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "propose_bizum",
            "description": (
                "Propone un Bizum desde la cuenta corriente del usuario. NO ejecuta nada: "
                "el sistema valida la operación y pide al usuario que la apruebe en pantalla. "
                "Llámala cuando el usuario pida enviar dinero por Bizum y tengas destinatario e importe."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient": {"type": "string", "description": "Nombre o teléfono del destinatario."},
                    "amount": {"type": "number", "description": "Cantidad en euros. Máximo 2000€."},
                    "concept": {"type": "string", "description": "Concepto o motivo del Bizum."},
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
                "properties": {},
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
            "name": "propose_investment",
            "description": (
                "Propone comprar un activo para la cartera del usuario. NO ejecuta nada: el sistema "
                "fija el precio de mercado, calcula el coste en euros, comprueba el saldo y pide al "
                "usuario que apruebe la compra en pantalla. Una sola compra por llamada."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "ticker": {"type": "string", "description": "Símbolo real de yfinance (ej: AAPL, VOO, SAN.MC)."},
                    "shares": {"type": "number", "description": "Número de acciones/participaciones a comprar (> 0)."},
                    "investment_type": {"type": "string", "enum": ["accion", "etf", "fondo_indexado"]},
                },
                "required": ["ticker", "shares"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_goal",
            "description": (
                "Crea un objetivo de ahorro nuevo para el usuario. No mueve dinero ni es "
                "irreversible, así que no requiere confirmación previa del usuario."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Nombre descriptivo del objetivo."},
                    "target_amount": {"type": "number", "description": "Importe objetivo en euros."},
                    "current_amount": {"type": "number", "description": "Importe ya ahorrado (por defecto 0)."},
                    "deadline": {"type": "string", "description": "Fecha límite en formato YYYY-MM-DD, opcional."},
                },
                "required": ["name", "target_amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_goals",
            "description": "Lista los objetivos de ahorro del usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {"type": "string", "enum": ["active", "completed", "cancelled", "all"]},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_goal_progress",
            "description": "Actualiza el importe ahorrado de un objetivo existente.",
            "parameters": {
                "type": "object",
                "properties": {
                    "goal_id": {"type": "integer", "description": "ID del objetivo (obtenido con list_goals)."},
                    "new_current_amount": {"type": "number", "description": "Nuevo importe total ahorrado."},
                },
                "required": ["goal_id", "new_current_amount"],
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
    "get_bizum_history": get_bizum_history,
    "calculate_mortgage": calculate_mortgage,
    "calculate_loan": calculate_loan,
    "calculate_compound_interest": calculate_compound_interest,
    "calculate_savings_goal": calculate_savings_goal,
    "calculate_budget_distribution": calculate_budget_distribution,
    "get_portfolio": get_portfolio,
    "get_asset_details": get_asset_details,
    "get_market_overview": get_market_overview,
    "create_goal": create_goal,
    "list_goals": list_goals,
    "update_goal_progress": update_goal_progress,
}


# ── Cliente litellm ───────────────────────────────────────────────────────────

def _build_model() -> str:
    """Devuelve el string de modelo litellm y configura las env vars necesarias."""
    model = settings.litellm_model
    if settings.anthropic_api_key:
        os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key
    if settings.openai_api_key:
        os.environ["OPENAI_API_KEY"] = settings.openai_api_key
    if settings.groq_api_key:
        os.environ["GROQ_API_KEY"] = settings.groq_api_key
    if settings.gemini_api_key:
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
    if settings.mistral_api_key:
        os.environ["MISTRAL_API_KEY"] = settings.mistral_api_key
    if settings.litellm_api_base:
        os.environ["OLLAMA_API_BASE"] = settings.litellm_api_base
    return model


def _is_claude(model: str) -> bool:
    return model.startswith("anthropic/")


def _check_api_key(model: str) -> str | None:
    """Devuelve mensaje de error si falta la API key del proveedor, None si todo OK."""
    key_map = {
        "anthropic": settings.anthropic_api_key,
        "openai":    settings.openai_api_key,
        "groq":      settings.groq_api_key,
        "gemini":    settings.gemini_api_key,
        "mistral":   settings.mistral_api_key,
    }
    provider = model.split("/")[0] if "/" in model else ""
    if provider in key_map and not key_map[provider]:
        return f"API key de {provider} no configurada. Ejecuta ./setup.sh o edita backend/.env"
    return None


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


# ── Fase 1: bucle de tools ────────────────────────────────────────────────────

# Tools que no ejecutan nada: solo registran la propuesta en el estado del grafo.
PROPOSAL_TOOLS = {"propose_bizum": "bizum", "propose_investment": "investment"}
MAX_TOOL_ROUNDS = 7


def _call_tool(name: str, args: dict, user_id: int) -> dict:
    func = TOOL_MAP.get(name)
    if not func:
        return {"error": f"tool '{name}' not found"}
    # Filtrar parámetros que el modelo haya inventado y no existan en la firma
    valid = inspect.signature(func).parameters
    args = {k: v for k, v in args.items() if k in valid and k != "user_id"}
    # El user_id lo pone siempre el servidor (sale del JWT), nunca el modelo
    if "user_id" in valid:
        args["user_id"] = user_id
    if isinstance(args.get("limit"), str):
        try:
            args["limit"] = int(args["limit"])
        except ValueError:
            args.pop("limit")
    try:
        return func(**args)
    except Exception as e:
        return {"error": str(e)[:200]}


def run_tool_loop(messages: list[dict], model: str, user_id: int) -> tuple[list[dict], dict | None]:
    """Fase 1 (nodo `agent` del grafo): el modelo llama tools de lectura en bucle.

    Devuelve los mensajes actualizados y, si el modelo ha llamado a una tool de
    propuesta, la propuesta en crudo ({"type": "bizum" | "investment", ...args}).
    Una propuesta corta el bucle: a partir de ahí decide el grafo, no el modelo."""
    msgs = list(messages)
    proposal: dict | None = None

    for _ in range(MAX_TOOL_ROUNDS):
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
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            if name in PROPOSAL_TOOLS:
                if proposal is None:
                    proposal = {**args, "type": PROPOSAL_TOOLS[name]}
                    result = {"status": "Propuesta registrada. El sistema la valida y pide aprobación al usuario."}
                else:
                    result = {"error": "Solo se puede proponer una operación por mensaje."}
            else:
                result = _call_tool(name, args, user_id)
            msgs.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

        if proposal:
            break

    return msgs, proposal


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


# ── Fase 2: respuesta en streaming ────────────────────────────────────────────

async def stream_response(
    messages: list[dict],
    model: str,
    voice_mode: bool,
    emit: Callable[[dict], None],
    context: str | None = None,
) -> dict:
    """Fase 2 (nodo `respond` del grafo): una sola llamada en streaming que devuelve
    texto + marcador + JSON del gráfico. Emite los tokens con `emit` y devuelve
    {"text", "chart_type", "chart_data", "chart_title"}.

    `context` es información que el grafo añade para redactar la respuesta (resultado
    de una operación, motivo de un rechazo...)."""
    prompt = COMBINED_PROMPT_VOICE if voice_mode else COMBINED_PROMPT
    if context:
        prompt = f"{context}\n\n{prompt}"
    combined_messages = messages + [{"role": "user", "content": prompt}]
    accumulated = ""   # todo el contenido acumulado del stream
    text_yielded = 0   # cuántos caracteres de texto hemos enviado ya
    json_found = False
    json_raw = ""

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
            pending_text = accumulated[:marker_idx][text_yielded:]
            if pending_text:
                emit({"type": "token", "text": pending_text})
            text_yielded = marker_idx
            json_found = True
            json_raw = accumulated[marker_idx + len(_MARKER):]
        else:
            # Todavía no hay marcador — enviamos lo que es seguro
            # Guardamos los últimos len(_MARKER) chars por si el marcador está partido entre chunks
            safe_end = max(text_yielded, len(accumulated) - len(_MARKER))
            if safe_end > text_yielded:
                emit({"type": "token", "text": accumulated[text_yielded:safe_end]})
                text_yielded = safe_end

    # Stream terminado — enviar texto restante si el marcador nunca apareció
    if not json_found:
        remaining = accumulated[text_yielded:]
        if remaining:
            emit({"type": "token", "text": remaining})
        text = accumulated
    else:
        text = accumulated[:accumulated.find(_MARKER)]

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
    return {
        "text": text.strip(),
        "chart_type": chart_type if chart_type in ("bar", "line", "pie") and normalized else None,
        "chart_data": normalized or None,
        "chart_title": data.get("chart_title") or None,
    }
