"""
Generación del dashboard proactivo.

A diferencia de chat_agent.py (bucle de tool-calling porque no sabemos de antemano
qué necesita el usuario), aquí SÍ sabemos exactamente qué datos hacen falta para
detectar situaciones relevantes, así que se llaman directamente las funciones de
financial_mcp.py (sin pasar por el LLM) y se hace UNA sola llamada al modelo con
todo el contexto ya recopilado, pidiéndole que decida qué tarjetas generar.

Ver docs/dashboard-proactivo.md para el porqué de cada decisión de diseño.
"""
import json

import litellm
from pydantic import ValidationError

from app.agent.chat_agent import _build_model, _is_claude
from app.agent.financial_mcp import (
    get_category_breakdown,
    get_financial_summary,
    get_portfolio,
    get_portfolio_news,
    get_spending_analysis,
)
from app.core.database import SessionLocal
from app.models.financial import Alert, Goal
from app.schemas.financial import AlertCardIn

DASHBOARD_PROMPT = """Eres el motor de un dashboard financiero PROACTIVO. Tu trabajo no es
responder preguntas: es decidir, a partir de los datos de un usuario concreto, qué 2-4
tarjetas de información merece la pena mostrarle SIN que él pregunte nada.

Responde siempre en español, sin emojis. Cada tarjeta debe aportar algo accionable o
relevante — no generes tarjetas de relleno si los datos no muestran nada interesante
(mejor devolver menos tarjetas que tarjetas vacías de contenido).

TIPOS DE TARJETA (campo "type"):
- budget_warning → gasto alto en una categoría concreta este mes
- anomaly        → gasto puntual inusualmente alto vs. el histórico del usuario
- positive       → algo que va bien (ahorro, gasto controlado, inversión positiva) — refuerzo positivo
- goal_progress  → progreso (bueno o preocupante) hacia una meta de ahorro activa
- weekly_summary → resumen narrativo breve de la situación general

FORMATO DE TARJETA (campo "card_type"):
- "text"  → solo title + body, sin gráfico. Úsalo para resúmenes narrativos o noticias.
- "chart" → incluye chart_type ("bar"|"line"|"pie"), chart_data y chart_title.
- "stat"  → un dato numérico destacado en el body (ej: "Has gastado 340€ en ocio, un 40% más que tu media").

severity: "info" (neutral), "warning" (atención), "critical" (requiere acción pronto).

cta_prompt: una pregunta en primera persona que el usuario podría hacerle al chat para
profundizar en esta tarjeta (ej: "¿Por qué he gastado tanto en restaurantes este mes?").
Debe poder responderse con las tools existentes del chat.

Responde ÚNICAMENTE con un JSON de la forma {"cards": [...]} (sin bloques de código, sin texto extra):
{
  "cards": [
    {
      "type": "budget_warning",
      "title": "Gasto alto en restaurantes",
      "body": "Has gastado 320€ en restaurantes este mes, un 45% más que tu media habitual.",
      "severity": "warning",
      "card_type": "stat",
      "chart_type": null,
      "chart_data": null,
      "chart_title": null,
      "cta_prompt": "¿Por qué he gastado tanto en restaurantes este mes?"
    },
    {
      "type": "positive",
      "title": "Cartera en verde",
      "body": "Tu cartera de inversión ha subido un 6.2% este mes, liderada por tus posiciones en tecnología.",
      "severity": "info",
      "card_type": "chart",
      "chart_type": "pie",
      "chart_data": [{"name": "AAPL", "value": 1200.0}, {"name": "MSFT", "value": 800.0}],
      "chart_title": "Distribución de cartera",
      "cta_prompt": "¿Cómo ha evolucionado mi cartera este mes?"
    }
  ]
}
"""


def _gather_context(user_id: int) -> dict:
    """Recopila en Python puro todo lo que el LLM necesita para decidir las tarjetas.
    Sin llamadas a herramientas vía tool-calling: ya sabemos qué datos hacen falta."""
    summary = get_financial_summary(user_id=user_id)
    categories = get_category_breakdown(user_id=user_id, period="current_month")
    spending = get_spending_analysis(user_id=user_id)
    portfolio = get_portfolio(user_id=user_id)
    news = get_portfolio_news(user_id=user_id) if portfolio.get("activos") else {"noticias": []}

    db = SessionLocal()
    try:
        goals = db.query(Goal).filter(Goal.user_id == user_id, Goal.status == "active").all()
        goals_data = [
            {
                "nombre": g.name,
                "objetivo": g.target_amount,
                "actual": g.current_amount,
                "fecha_limite": g.deadline.isoformat() if g.deadline else None,
            }
            for g in goals
        ]
    finally:
        db.close()

    return {
        "resumen_financiero": summary,
        "desglose_categorias": categories,
        "analisis_gasto": spending,
        "cartera": portfolio,
        "noticias_cartera": news,
        "metas_activas": goals_data,
    }


def _parse_cards(raw: str) -> list[AlertCardIn]:
    """Parsea la respuesta del LLM de forma tolerante: una tarjeta malformada se
    descarta individualmente, no tumba el resto del batch."""
    raw = raw.strip()
    if raw.startswith("```"):
        lines = raw.splitlines()
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    # Tolerar que el modelo envuelva el array en {"cards": [...]}
    if isinstance(data, dict):
        data = data.get("cards", [])
    if not isinstance(data, list):
        return []

    cards = []
    seen_titles: set[str] = set()
    for entry in data:
        if not isinstance(entry, dict):
            continue
        try:
            card = AlertCardIn(**entry)
        except ValidationError:
            continue
        # El LLM a veces repite la misma tarjeta (mismo título) en una sola respuesta,
        # p.ej. dos variantes de "cartera en verde" — nos quedamos solo con la primera.
        key = card.title.strip().lower()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        cards.append(card)
    return cards


def generate_dashboard_cards(user_id: int) -> list[AlertCardIn]:
    """Genera y persiste las tarjetas del dashboard para un usuario. Devuelve las
    tarjetas válidas guardadas (puede ser una lista vacía si el LLM no encontró nada
    relevante o si toda la respuesta era inválida)."""
    model = _build_model()
    context = _gather_context(user_id)

    messages = [
        {"role": "system", "content": DASHBOARD_PROMPT},
        {"role": "user", "content": f"Datos del usuario:\n{json.dumps(context, ensure_ascii=False, default=str)}"},
    ]

    kwargs: dict = {"model": model, "messages": messages}
    if not _is_claude(model):
        kwargs["response_format"] = {"type": "json_object"}

    response = litellm.completion(**kwargs)
    raw = response.choices[0].message.content or "[]"
    cards = _parse_cards(raw)

    db = SessionLocal()
    try:
        # Cada regeneración sustituye el set de tarjetas actual: si no borráramos las
        # anteriores, cada refresh (incluido el automático al entrar en el dashboard)
        # se iría acumulando sobre las de antes y una misma tarjeta (p.ej. "cartera en
        # verde") podría acabar apareciendo varias veces, de generaciones distintas.
        db.query(Alert).filter(Alert.user_id == user_id).delete()
        for card in cards:
            db.add(Alert(
                user_id=user_id,
                type=card.type,
                title=card.title,
                body=card.body,
                severity=card.severity,
                card_type=card.card_type,
                chart_type=card.chart_type,
                chart_data=json.dumps([d.model_dump() for d in card.chart_data], ensure_ascii=False) if card.chart_data else None,
                chart_title=card.chart_title,
                cta_prompt=card.cta_prompt,
            ))
        db.commit()
    finally:
        db.close()

    return cards
