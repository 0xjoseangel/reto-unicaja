from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class TransactionOut(BaseModel):
    id: int
    account_id: int
    amount: float
    transaction_type: str
    category: str
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
    user_id: int = 1
    history: list[HistoryMessage] = []


class PendingBizumAction(BaseModel):
    type: Literal["bizum_confirm"]
    recipient: str
    amount: float
    concept: str


class PendingInvestmentAction(BaseModel):
    type: Literal["investment_confirm"]
    ticker: str
    nombre: str
    shares: float
    avg_purchase_price: float
    investment_type: str


class ChatResponse(BaseModel):
    response: str
    chart_type: Literal["bar", "line", "pie"] | None = None
    chart_data: list[ChartDataPoint] | None = None
    chart_title: str | None = None
    pending_action: PendingBizumAction | PendingInvestmentAction | None = None
