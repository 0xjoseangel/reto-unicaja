from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class TransactionOut(BaseModel):
    id: int
    account_id: int
    amount: float
    transaction_type: str
    category: str
    merchant: str | None = None
    description: str | None
    date: datetime

    model_config = {"from_attributes": True}


class AccountOut(BaseModel):
    id: int
    name: str
    account_type: str
    balance: float

    model_config = {"from_attributes": True}


class SummaryOut(BaseModel):
    total_income: float
    total_expenses: float
    balance: float
    transactions_count: int
    top_categories: list[dict]


class ChartDataPoint(BaseModel):
    name: str
    value: float


class HistoryMessage(BaseModel):
    role: str   # "user" | "assistant"
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[HistoryMessage] = []
    voice_mode: bool = False


class PendingBizumAction(BaseModel):
    """Bizum validado por el servidor y pendiente de aprobación. Se aprueba o
    rechaza con POST /chat/actions/{action_id}."""
    type: Literal["bizum_confirm"] = "bizum_confirm"
    action_id: str
    recipient: str
    amount: float
    concept: str


class PendingInvestmentAction(BaseModel):
    """Compra validada por el servidor: precio de mercado y coste en euros los
    calcula el backend, no el LLM."""
    type: Literal["investment_confirm"] = "investment_confirm"
    action_id: str
    ticker: str
    nombre: str
    shares: float
    price: float
    currency: str
    total_eur: float
    investment_type: str


class ActionDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]


class ChatResponse(BaseModel):
    response: str
    chart_type: Literal["bar", "line", "pie"] | None = None
    chart_data: list[ChartDataPoint] | None = None
    chart_title: str | None = None
    pending_action: PendingBizumAction | PendingInvestmentAction | None = None


# ── Historial de conversaciones pasadas ─────────────────────────────────────

class ConversationSessionOut(BaseModel):
    """Una conversación pasada, agrupada por día natural (Conversation no tiene
    un id de sesión/hilo propio)."""
    date: str   # "YYYY-MM-DD"
    message_count: int
    preview: str


class ConversationMessageOut(BaseModel):
    role: str   # "user" | "assistant"
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Dashboard proactivo ─────────────────────────────────────────────────────

class AlertCardIn(BaseModel):
    """Lo que genera el LLM para una tarjeta del dashboard. Se valida antes de guardar
    en la tabla `alerts` — una tarjeta inválida se descarta sin tumbar el resto del batch."""
    type: Literal["budget_warning", "anomaly", "positive", "goal_progress", "weekly_summary"]
    title: str
    body: str
    severity: Literal["info", "warning", "critical"] = "info"
    card_type: Literal["text", "chart", "stat"] = "text"
    chart_type: Literal["bar", "line", "pie"] | None = None
    chart_data: list[ChartDataPoint] | None = None
    chart_title: str | None = None
    cta_prompt: str | None = None


class AlertCardOut(BaseModel):
    """Lo que sirve GET /dashboard/ — igual que AlertCardIn más los campos de persistencia."""
    id: int
    type: Literal["budget_warning", "anomaly", "positive", "goal_progress", "weekly_summary"]
    title: str
    body: str
    severity: Literal["info", "warning", "critical"]
    card_type: Literal["text", "chart", "stat"]
    chart_type: Literal["bar", "line", "pie"] | None = None
    chart_data: list[ChartDataPoint] | None = None
    chart_title: str | None = None
    cta_prompt: str | None = None
    seen: bool
    generated_at: datetime
