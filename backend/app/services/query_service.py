import re
from datetime import datetime, timedelta

from sqlalchemy import extract, func
from sqlalchemy.orm import Session

from app.models.financial import Account, Transaction
from app.schemas.financial import ChartDataPoint, ChatResponse, SummaryOut, TransactionOut

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "restaurantes": ["restaurante", "restaurantes", "comer", "comida", "cafetería", "café"],
    "supermercado": ["supermercado", "mercadona", "lidl", "aldi", "carrefour", "compra"],
    "transporte": ["transporte", "metro", "bus", "gasolina", "gasolinera", "taxi", "uber", "renfe", "tren"],
    "salario": ["salario", "nómina", "sueldo", "ingreso", "cobro"],
    "alquiler": ["alquiler", "renta", "hipoteca"],
    "ocio": ["ocio", "cine", "teatro", "concierto", "spotify", "netflix", "entretenimiento"],
    "salud": ["salud", "farmacia", "médico", "dentista", "hospital", "seguro"],
    "ropa": ["ropa", "zara", "mango", "zapatos"],
    "servicios": ["electricidad", "servicios", "teléfono", "internet"],
}


def _detect_category(message: str) -> str | None:
    msg = message.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(re.search(r'\b' + re.escape(kw) + r'\b', msg) for kw in keywords):
            return category
    return None


def _detect_period(message: str) -> tuple[datetime, datetime]:
    now = datetime.now()
    msg = message.lower()

    if "último mes" in msg or "mes pasado" in msg:
        first_day = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
        last_day = now.replace(day=1) - timedelta(days=1)
        return first_day, last_day
    if "este año" in msg or "año actual" in msg:
        return now.replace(month=1, day=1), now
    if "últimos 3 meses" in msg or "trimestre" in msg:
        return now - timedelta(days=90), now

    # Por defecto: mes actual
    return now.replace(day=1), now


def get_transactions(
    db: Session,
    user_id: int,
    category: str | None = None,
    transaction_type: str | None = None,
    limit: int = 50,
) -> list[TransactionOut]:
    query = (
        db.query(Transaction)
        .filter(Transaction.user_id == user_id)
    )
    if category:
        query = query.filter(Transaction.category == category)
    if transaction_type:
        query = query.filter(Transaction.transaction_type == transaction_type)

    results = query.order_by(Transaction.date.desc()).limit(limit).all()
    return [TransactionOut.model_validate(t) for t in results]


def get_summary(db: Session, user_id: int) -> SummaryOut:
    accounts = db.query(Account).filter(Account.user_id == user_id).all()
    total_balance = sum(a.balance for a in accounts)

    income = (
        db.query(func.sum(Transaction.amount))
        .filter(
            Transaction.user_id == user_id,
            Transaction.transaction_type == "ingreso",
        )
        .scalar() or 0.0
    )
    expenses = (
        db.query(func.sum(Transaction.amount))
        .filter(
            Transaction.user_id == user_id,
            Transaction.transaction_type == "gasto",
        )
        .scalar() or 0.0
    )
    count = (
        db.query(func.count(Transaction.id))
        .filter(Transaction.user_id == user_id)
        .scalar() or 0
    )

    top_cats = (
        db.query(Transaction.category, func.sum(Transaction.amount).label("total"))
        .filter(
            Transaction.user_id == user_id,
            Transaction.transaction_type == "gasto",
        )
        .group_by(Transaction.category)
        .order_by(func.sum(Transaction.amount).desc())
        .limit(5)
        .all()
    )

    return SummaryOut(
        total_income=round(income, 2),
        total_expenses=round(expenses, 2),
        balance=round(total_balance, 2),
        transactions_count=count,
        top_categories=[{"category": cat, "total": round(total, 2)} for cat, total in top_cats],
    )


def process_chat(db: Session, message: str, user_id: int) -> ChatResponse:
    msg = message.lower()
    accounts = db.query(Account).filter(Account.user_id == user_id).all()
    start_date, end_date = _detect_period(message)
    category = _detect_category(message)

    # --- Intento: gastos por categoría a lo largo del tiempo ---
    if category and any(w in msg for w in ["mensual", "por mes", "evolución", "histórico", "meses"]):
        rows = (
            db.query(
                extract("month", Transaction.date).label("month"),
                extract("year", Transaction.date).label("year"),
                func.sum(Transaction.amount).label("total"),
            )
            .filter(
                Transaction.user_id == user_id,
                Transaction.category == category,
            )
            .group_by("year", "month")
            .order_by("year", "month")
            .all()
        )
        MONTH_NAMES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]
        data = [ChartDataPoint(name=MONTH_NAMES[int(r.month) - 1], value=round(r.total, 2)) for r in rows]
        total = sum(p.value for p in data)
        return ChatResponse(
            response=f"Evolución mensual de gastos en {category}: total acumulado {total:.2f}€.",
            chart_type="line",
            chart_data=data,
            chart_title=f"Evolución de gastos en {category}",
        )

    # --- Intento: ¿cuánto gasté en X categoría? ---
    if category:
        total = (
            db.query(func.sum(Transaction.amount))
            .filter(
                Transaction.user_id == user_id,
                Transaction.category == category,
                Transaction.transaction_type == "gasto",
                Transaction.date >= start_date,
                Transaction.date <= end_date,
            )
            .scalar() or 0.0
        )
        period_label = "este mes" if start_date.day == 1 and end_date.month == datetime.now().month else "en el período seleccionado"
        return ChatResponse(
            response=f"Has gastado {total:.2f}€ en {category} {period_label}.",
            chart_type=None,
        )

    # --- Intento: resumen / balance / saldo ---
    if any(w in msg for w in ["saldo", "balance", "resumen", "resúmen", "cuánto tengo", "cuanto tengo"]):
        summary = get_summary(db, user_id)
        data = [
            ChartDataPoint(name="Ingresos", value=summary.total_income),
            ChartDataPoint(name="Gastos", value=summary.total_expenses),
        ]
        return ChatResponse(
            response=(
                f"Tu saldo actual es {summary.balance:.2f}€. "
                f"Ingresos totales: {summary.total_income:.2f}€. "
                f"Gastos totales: {summary.total_expenses:.2f}€."
            ),
            chart_type="bar",
            chart_data=data,
            chart_title="Ingresos vs Gastos",
        )

    # --- Intento: desglose de gastos por categoría ---
    if any(w in msg for w in ["categoría", "categoria", "en qué gasto", "en que gasto", "desglose", "distribución"]):
        rows = (
            db.query(Transaction.category, func.sum(Transaction.amount).label("total"))
            .filter(
                Transaction.user_id == user_id,
                Transaction.transaction_type == "gasto",
                Transaction.date >= start_date,
                Transaction.date <= end_date,
            )
            .group_by(Transaction.category)
            .order_by(func.sum(Transaction.amount).desc())
            .all()
        )
        data = [ChartDataPoint(name=r.category, value=round(r.total, 2)) for r in rows]
        total = sum(p.value for p in data)
        return ChatResponse(
            response=f"Este mes has gastado {total:.2f}€ en total, distribuidos por categorías.",
            chart_type="pie",
            chart_data=data,
            chart_title="Distribución de gastos por categoría",
        )

    # --- Intento: ingresos ---
    if any(w in msg for w in ["ingreso", "ingresos", "cobré", "cobre", "salario", "nómina"]):
        total = (
            db.query(func.sum(Transaction.amount))
            .filter(
                Transaction.user_id == user_id,
                Transaction.transaction_type == "ingreso",
                Transaction.date >= start_date,
                Transaction.date <= end_date,
            )
            .scalar() or 0.0
        )
        return ChatResponse(
            response=f"Has recibido {total:.2f}€ en ingresos este mes.",
            chart_type=None,
        )

    # --- Fallback ---
    return ChatResponse(
        response=(
            "No he entendido bien tu consulta. Puedes preguntarme cosas como:\n"
            "• '¿Cuánto gasté en restaurantes este mes?'\n"
            "• '¿Cuál es mi saldo actual?'\n"
            "• '¿En qué categorías gasto más?'\n"
            "• 'Evolución mensual de gastos en transporte'"
        ),
        chart_type=None,
    )
