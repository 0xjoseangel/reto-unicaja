"""
MCP Server con las herramientas financieras del proyecto.

Cada función decorada con @mcp.tool() queda registrada en el servidor MCP
y puede ser descubierta por cualquier cliente MCP compatible.
Las funciones son también callables normales de Python — el decorador solo las registra,
no las envuelve ni cambia su comportamiento.
"""
from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP
from sqlalchemy import extract, func

from app.core.database import SessionLocal
from app.models.financial import Account, Transaction

mcp = FastMCP("financial-assistant")


# ── Helpers internos ──────────────────────────────────────────────────────────

def _account_ids(db, user_id: int) -> list[int]:
    return [a.id for a in db.query(Account).filter(Account.user_id == user_id).all()]


def _period_dates(period: str) -> tuple[datetime, datetime]:
    now = datetime.now()
    match period:
        case "last_month":
            start = (now.replace(day=1) - timedelta(days=1)).replace(day=1)
            end = now.replace(day=1) - timedelta(days=1)
        case "last_3_months":
            start, end = now - timedelta(days=90), now
        case "all_time":
            start, end = datetime(2000, 1, 1), now
        case _:  # current_month por defecto
            start, end = now.replace(day=1), now
    return start, end


MONTH_NAMES = ["Ene", "Feb", "Mar", "Abr", "May", "Jun",
               "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"]


# ── Tools MCP ─────────────────────────────────────────────────────────────────

@mcp.tool()
def get_financial_summary(user_id: int = 1) -> dict:
    """Obtiene el resumen financiero del usuario: saldo total, ingresos totales,
    gastos totales y las 5 categorías en las que más gasta."""
    db = SessionLocal()
    try:
        ids = _account_ids(db, user_id)
        accounts = db.query(Account).filter(Account.user_id == user_id).all()
        balance = round(sum(a.balance for a in accounts), 2)

        income = db.query(func.sum(Transaction.amount)).filter(
            Transaction.account_id.in_(ids),
            Transaction.transaction_type == "ingreso",
        ).scalar() or 0.0

        expenses = db.query(func.sum(Transaction.amount)).filter(
            Transaction.account_id.in_(ids),
            Transaction.transaction_type == "gasto",
        ).scalar() or 0.0

        top = db.query(
            Transaction.category,
            func.sum(Transaction.amount).label("total"),
        ).filter(
            Transaction.account_id.in_(ids),
            Transaction.transaction_type == "gasto",
        ).group_by(Transaction.category).order_by(
            func.sum(Transaction.amount).desc()
        ).limit(5).all()

        return {
            "balance": balance,
            "total_income": round(income, 2),
            "total_expenses": round(expenses, 2),
            "top_categories": [{"category": c, "total": round(t, 2)} for c, t in top],
        }
    finally:
        db.close()


@mcp.tool()
def get_expenses_by_category(
    category: str,
    period: str = "current_month",
    user_id: int = 1,
) -> dict:
    """Obtiene el total gastado en una categoría específica.

    Categorías válidas: restaurantes, supermercado, transporte, alquiler,
    ocio, salud, ropa, servicios, salario.
    Períodos válidos: current_month, last_month, last_3_months, all_time.
    """
    db = SessionLocal()
    try:
        ids = _account_ids(db, user_id)
        start, end = _period_dates(period)

        total = db.query(func.sum(Transaction.amount)).filter(
            Transaction.account_id.in_(ids),
            Transaction.category == category,
            Transaction.transaction_type == "gasto",
            Transaction.date >= start,
            Transaction.date <= end,
        ).scalar() or 0.0

        return {"category": category, "total": round(total, 2), "period": period}
    finally:
        db.close()


@mcp.tool()
def get_monthly_evolution(category: str, user_id: int = 1) -> dict:
    """Obtiene la evolución mensual de gastos en una categoría a lo largo de
    los últimos 12 meses. Ideal para detectar tendencias."""
    db = SessionLocal()
    try:
        ids = _account_ids(db, user_id)

        rows = db.query(
            extract("year", Transaction.date).label("year"),
            extract("month", Transaction.date).label("month"),
            func.sum(Transaction.amount).label("total"),
        ).filter(
            Transaction.account_id.in_(ids),
            Transaction.category == category,
            Transaction.transaction_type == "gasto",
        ).group_by("year", "month").order_by("year", "month").all()

        return {
            "category": category,
            "monthly_data": [
                {"month": MONTH_NAMES[int(r.month) - 1], "total": round(r.total, 2)}
                for r in rows
            ],
        }
    finally:
        db.close()


@mcp.tool()
def get_category_breakdown(period: str = "current_month", user_id: int = 1) -> dict:
    """Obtiene el desglose de gastos por todas las categorías en un período.
    Útil para responder '¿en qué gasto más?' o ver la distribución completa.

    Períodos válidos: current_month, last_month, last_3_months, all_time.
    """
    db = SessionLocal()
    try:
        ids = _account_ids(db, user_id)
        start, end = _period_dates(period)

        rows = db.query(
            Transaction.category,
            func.sum(Transaction.amount).label("total"),
        ).filter(
            Transaction.account_id.in_(ids),
            Transaction.transaction_type == "gasto",
            Transaction.date >= start,
            Transaction.date <= end,
        ).group_by(Transaction.category).order_by(
            func.sum(Transaction.amount).desc()
        ).all()

        return {
            "period": period,
            "categories": [{"category": c, "total": round(t, 2)} for c, t in rows],
        }
    finally:
        db.close()


@mcp.tool()
def get_transaction_count(
    category: str | None = None,
    period: str = "current_month",
    user_id: int = 1,
) -> dict:
    """Cuenta el número de transacciones (visitas, compras, pagos) en un período.
    Si se especifica category, filtra por esa categoría (ej: restaurantes, supermercado).
    Si no se especifica, cuenta todas las transacciones de gasto.

    Categorías válidas: restaurantes, supermercado, transporte, alquiler,
    ocio, salud, ropa, servicios, salario.
    Períodos válidos: current_month, last_month, last_3_months, all_time.
    """
    db = SessionLocal()
    try:
        ids = _account_ids(db, user_id)
        start, end = _period_dates(period)

        query = db.query(func.count(Transaction.id)).filter(
            Transaction.account_id.in_(ids),
            Transaction.transaction_type == "gasto",
            Transaction.date >= start,
            Transaction.date <= end,
        )
        if category:
            query = query.filter(Transaction.category == category)

        count = query.scalar() or 0

        return {"category": category or "todas", "count": count, "period": period}
    finally:
        db.close()
