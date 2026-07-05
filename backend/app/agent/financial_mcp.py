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

@mcp.tool()
def search_specific_transactions(
    keyword: str,
    limit: int = 5,
    user_id: int = 1,
) -> dict:
    """Busca transacciones individuales por palabra clave en la descripción
    (ej: 'Netflix', 'Mercadona', 'Luz'). Usa esto cuando el usuario pregunte
    por recibos concretos o un gasto específico."""
    db = SessionLocal()
    try:
        ids = _account_ids(db, user_id)
        rows = db.query(Transaction).filter(
            Transaction.account_id.in_(ids),
            Transaction.description.ilike(f"%{keyword}%"),
        ).order_by(Transaction.date.desc()).limit(limit).all()

        if not rows:
            return {"message": f"No se encontraron transacciones para '{keyword}'"}

        return {
            "keyword_searched": keyword,
            "transactions": [
                {
                    "fecha": r.date.strftime("%Y-%m-%d"),
                    "descripcion": r.description,
                    "monto": round(r.amount, 2),
                    "categoria": r.category,
                }
                for r in rows
            ],
        }
    finally:
        db.close()


@mcp.tool()
def get_recent_transactions(limit: int = 5, user_id: int = 1) -> dict:
    """Obtiene los movimientos más recientes del usuario. Útil para responder
    a '¿Cuáles son mis últimos gastos?' o para dar contexto de los últimos días."""
    db = SessionLocal()
    try:
        ids = _account_ids(db, user_id)
        rows = db.query(Transaction).filter(
            Transaction.account_id.in_(ids),
        ).order_by(Transaction.date.desc()).limit(limit).all()

        return {
            "recent_transactions": [
                {
                    "fecha": r.date.strftime("%Y-%m-%d"),
                    "descripcion": r.description,
                    "monto": round(r.amount, 2),
                    "tipo": r.transaction_type,
                    "categoria": r.category,
                }
                for r in rows
            ]
        }
    finally:
        db.close()


@mcp.tool()
def get_largest_expenses(
    period: str = "current_month",
    limit: int = 3,
    user_id: int = 1,
) -> dict:
    """Encuentra los gastos individuales más grandes en un período.
    Útil para responder por qué el usuario tiene poco saldo o dónde se le fue el dinero."""
    db = SessionLocal()
    try:
        ids = _account_ids(db, user_id)
        start, end = _period_dates(period)
        rows = db.query(Transaction).filter(
            Transaction.account_id.in_(ids),
            Transaction.transaction_type == "gasto",
            Transaction.date >= start,
            Transaction.date <= end,
        ).order_by(Transaction.amount.desc()).limit(limit).all()

        return {
            "period": period,
            "largest_expenses": [
                {
                    "fecha": r.date.strftime("%Y-%m-%d"),
                    "descripcion": r.description,
                    "monto": round(r.amount, 2),
                    "categoria": r.category,
                }
                for r in rows
            ],
        }
    finally:
        db.close()


@mcp.tool()
def get_places_by_category(
    category: str,
    period: str = "all_time",
    user_id: int = 1,
) -> dict:
    """Lista los establecimientos o lugares concretos visitados en una categoría,
    con cuántas veces se fue y cuánto se gastó en total en cada uno.
    Úsalo para responder '¿a qué restaurantes he ido?', '¿en qué supermercados compro?', etc.

    Categorías válidas: restaurantes, supermercado, transporte, alquiler,
    ocio, salud, ropa, servicios.
    Períodos válidos: current_month, last_month, last_3_months, all_time.
    """
    db = SessionLocal()
    try:
        ids = _account_ids(db, user_id)
        start, end = _period_dates(period)
        rows = db.query(
            Transaction.description,
            func.count(Transaction.id).label("visits"),
            func.sum(Transaction.amount).label("total"),
        ).filter(
            Transaction.account_id.in_(ids),
            Transaction.category == category,
            Transaction.transaction_type == "gasto",
            Transaction.date >= start,
            Transaction.date <= end,
        ).group_by(Transaction.description).order_by(
            func.count(Transaction.id).desc()
        ).all()

        return {
            "category": category,
            "period": period,
            "places": [
                {
                    "nombre": r.description,
                    "visitas": r.visits,
                    "total_gastado": round(r.total, 2),
                }
                for r in rows
            ],
        }
    finally:
        db.close()


@mcp.tool()
def get_spending_analysis(user_id: int = 1) -> dict:
    """Analiza si el usuario está gastando demasiado en alguna categoría comparando
    el mes actual con su promedio histórico de los últimos 11 meses.
    Devuelve cada categoría marcada como 'alto', 'normal' o 'bajo'.
    Úsalo para responder '¿estoy gastando demasiado?', '¿en qué me paso del presupuesto?'
    o '¿mi gasto este mes es normal?'
    """
    db = SessionLocal()
    try:
        ids = _account_ids(db, user_id)
        now = datetime.now()
        current_start = now.replace(day=1)
        eleven_months_ago = current_start - timedelta(days=335)

        current_rows = db.query(
            Transaction.category,
            func.sum(Transaction.amount).label("total"),
        ).filter(
            Transaction.account_id.in_(ids),
            Transaction.transaction_type == "gasto",
            Transaction.date >= current_start,
        ).group_by(Transaction.category).all()

        hist_rows = db.query(
            Transaction.category,
            func.sum(Transaction.amount).label("total"),
        ).filter(
            Transaction.account_id.in_(ids),
            Transaction.transaction_type == "gasto",
            Transaction.date >= eleven_months_ago,
            Transaction.date < current_start,
        ).group_by(Transaction.category).all()

        hist_avg = {r.category: round(r.total / 11, 2) for r in hist_rows}
        current_dict = {r.category: round(r.total, 2) for r in current_rows}

        analysis = []
        for cat, curr_total in current_dict.items():
            avg = hist_avg.get(cat, 0)
            pct_change = round(((curr_total - avg) / avg) * 100, 1) if avg > 0 else 100.0
            analysis.append({
                "categoria": cat,
                "mes_actual": curr_total,
                "promedio_mensual": avg,
                "variacion_pct": pct_change,
                "estado": "alto" if pct_change > 20 else ("bajo" if pct_change < -20 else "normal"),
            })

        analysis.sort(key=lambda x: x["variacion_pct"], reverse=True)

        return {"analisis": analysis, "meses_comparados": 11}
    finally:
        db.close()


@mcp.tool()
def make_bizum_transfer(
    recipient: str,
    amount: float,
    concept: str = "Bizum",
    user_id: int = 1,
) -> dict:
    """Ejecuta una transferencia Bizum desde la cuenta corriente del usuario.
    Valida que haya saldo suficiente. Límite: 2000€ por operación.

    IMPORTANTE: Antes de llamar a esta función DEBES haber confirmado con el
    usuario el destinatario y el importe exacto.

    Args:
        recipient: Nombre o teléfono del destinatario.
        amount: Cantidad en euros (debe ser > 0 y <= 2000).
        concept: Concepto o motivo del Bizum.
        user_id: ID del usuario.
    """
    if amount <= 0:
        return {"success": False, "error": "El importe debe ser mayor que 0€."}
    if amount > 2000:
        return {"success": False, "error": "El límite por transferencia Bizum es 2000€."}

    db = SessionLocal()
    try:
        account = db.query(Account).filter(
            Account.user_id == user_id,
            Account.account_type == "corriente",
        ).first()

        if not account:
            return {"success": False, "error": "No se encontró cuenta corriente."}

        if account.balance < amount:
            return {
                "success": False,
                "error": (
                    f"Saldo insuficiente. Tienes {round(account.balance, 2)}€ disponibles "
                    f"y quieres enviar {round(amount, 2)}€."
                ),
                "saldo_disponible": round(account.balance, 2),
            }

        account.balance = round(account.balance - amount, 2)
        transaction = Transaction(
            account_id=account.id,
            amount=round(amount, 2),
            transaction_type="gasto",
            category="bizum",
            description=f"Bizum a {recipient} — {concept}",
            date=datetime.now(),
        )
        db.add(transaction)
        db.commit()
        db.refresh(transaction)

        return {
            "success": True,
            "destinatario": recipient,
            "importe": round(amount, 2),
            "concepto": concept,
            "nuevo_saldo": account.balance,
            "fecha": transaction.date.strftime("%Y-%m-%d %H:%M"),
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def get_bizum_history(limit: int = 10, user_id: int = 1) -> dict:
    """Obtiene el historial de transferencias Bizum realizadas por el usuario."""
    db = SessionLocal()
    try:
        ids = _account_ids(db, user_id)
        rows = db.query(Transaction).filter(
            Transaction.account_id.in_(ids),
            Transaction.category == "bizum",
        ).order_by(Transaction.date.desc()).limit(limit).all()

        return {
            "bizum_transfers": [
                {
                    "fecha": r.date.strftime("%Y-%m-%d %H:%M"),
                    "descripcion": r.description,
                    "importe": round(r.amount, 2),
                }
                for r in rows
            ]
        }
    finally:
        db.close()