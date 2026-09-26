"""
MCP Server con las herramientas financieras del proyecto.
"""
from datetime import datetime, timedelta

import yfinance as yf
from mcp.server.fastmcp import FastMCP
from sqlalchemy import extract, func, or_

from app.core.database import SessionLocal
from app.models.financial import Account, BizumTransfer, Goal, Investment, Transaction

mcp = FastMCP("financial-assistant")


# ── Helpers internos ──────────────────────────────────────────────────────────

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
        accounts = db.query(Account).filter(Account.user_id == user_id).all()
        balance = round(sum(a.balance for a in accounts), 2)

        income = db.query(func.sum(Transaction.amount)).filter(
            Transaction.user_id == user_id,
            Transaction.transaction_type == "ingreso",
        ).scalar() or 0.0

        expenses = db.query(func.sum(Transaction.amount)).filter(
            Transaction.user_id == user_id,
            Transaction.transaction_type == "gasto",
        ).scalar() or 0.0

        first = db.query(func.min(Transaction.date)).filter(
            Transaction.user_id == user_id,
        ).scalar()
        last = db.query(func.max(Transaction.date)).filter(
            Transaction.user_id == user_id,
        ).scalar()

        months = 1
        if first and last:
            delta = (last.year - first.year) * 12 + (last.month - first.month) + 1
            months = max(delta, 1)

        top = db.query(
            Transaction.category,
            func.sum(Transaction.amount).label("total"),
        ).filter(
            Transaction.user_id == user_id,
            Transaction.transaction_type == "gasto",
        ).group_by(Transaction.category).order_by(
            func.sum(Transaction.amount).desc()
        ).limit(5).all()

        return {
            "balance": balance,
            "total_income": round(income, 2),
            "total_expenses": round(expenses, 2),
            "periodo_meses": months,
            "ingreso_mensual_promedio": round(income / months, 2),
            "gasto_mensual_promedio": round(expenses / months, 2),
            "top_categories": [{"category": c, "total": round(t, 2)} for c, t in top],
            "nota": f"Los totales cubren {months} meses de historial.",
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
        start, end = _period_dates(period)
        total = db.query(func.sum(Transaction.amount)).filter(
            Transaction.user_id == user_id,
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
        rows = db.query(
            extract("year", Transaction.date).label("year"),
            extract("month", Transaction.date).label("month"),
            func.sum(Transaction.amount).label("total"),
        ).filter(
            Transaction.user_id == user_id,
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
        start, end = _period_dates(period)
        rows = db.query(
            Transaction.category,
            func.sum(Transaction.amount).label("total"),
        ).filter(
            Transaction.user_id == user_id,
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
        start, end = _period_dates(period)
        query = db.query(func.count(Transaction.id)).filter(
            Transaction.user_id == user_id,
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
    """Busca transacciones individuales por palabra clave en el comercio o descripción
    (ej: 'Netflix', 'Mercadona', 'Luz'). Usa esto cuando el usuario pregunte
    por recibos concretos o un gasto específico."""
    db = SessionLocal()
    try:
        rows = db.query(Transaction).filter(
            Transaction.user_id == user_id,
            or_(
                Transaction.merchant.ilike(f"%{keyword}%"),
                Transaction.description.ilike(f"%{keyword}%"),
            ),
        ).order_by(Transaction.date.desc()).limit(limit).all()

        if not rows:
            return {"message": f"No se encontraron transacciones para '{keyword}'"}

        return {
            "keyword_searched": keyword,
            "transactions": [
                {
                    "fecha": r.date.strftime("%Y-%m-%d"),
                    "comercio": r.merchant,
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
        rows = db.query(Transaction).filter(
            Transaction.user_id == user_id,
        ).order_by(Transaction.date.desc()).limit(limit).all()

        return {
            "recent_transactions": [
                {
                    "fecha": r.date.strftime("%Y-%m-%d"),
                    "comercio": r.merchant,
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
        start, end = _period_dates(period)
        rows = db.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.transaction_type == "gasto",
            Transaction.date >= start,
            Transaction.date <= end,
        ).order_by(Transaction.amount.desc()).limit(limit).all()

        return {
            "period": period,
            "largest_expenses": [
                {
                    "fecha": r.date.strftime("%Y-%m-%d"),
                    "comercio": r.merchant,
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
        start, end = _period_dates(period)
        rows = db.query(
            Transaction.merchant,
            func.count(Transaction.id).label("visits"),
            func.sum(Transaction.amount).label("total"),
        ).filter(
            Transaction.user_id == user_id,
            Transaction.category == category,
            Transaction.transaction_type == "gasto",
            Transaction.date >= start,
            Transaction.date <= end,
            Transaction.merchant.isnot(None),
        ).group_by(Transaction.merchant).order_by(
            func.count(Transaction.id).desc()
        ).all()

        return {
            "category": category,
            "period": period,
            "places": [
                {
                    "nombre": r.merchant,
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
        now = datetime.now()
        current_start = now.replace(day=1)
        eleven_months_ago = current_start - timedelta(days=335)

        current_rows = db.query(
            Transaction.category,
            func.sum(Transaction.amount).label("total"),
        ).filter(
            Transaction.user_id == user_id,
            Transaction.transaction_type == "gasto",
            Transaction.date >= current_start,
        ).group_by(Transaction.category).all()

        hist_rows = db.query(
            Transaction.category,
            func.sum(Transaction.amount).label("total"),
        ).filter(
            Transaction.user_id == user_id,
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
        now = datetime.now()

        transaction = Transaction(
            account_id=account.id,
            user_id=user_id,
            amount=round(amount, 2),
            transaction_type="gasto",
            category="bizum",
            merchant=recipient,
            description=concept,
            source="bizum",
            date=now,
        )
        db.add(transaction)

        bizum_record = BizumTransfer(
            user_id=user_id,
            recipient=recipient,
            amount=round(amount, 2),
            concept=concept,
            status="completed",
            executed_at=now,
        )
        db.add(bizum_record)

        db.commit()

        all_accounts = db.query(Account).filter(Account.user_id == user_id).all()
        total_balance = round(sum(a.balance for a in all_accounts), 2)

        return {
            "success": True,
            "destinatario": recipient,
            "importe": round(amount, 2),
            "concepto": concept,
            "nuevo_saldo_total": total_balance,
            "nuevo_saldo_cuenta_corriente": account.balance,
            "nota": "nuevo_saldo_total es la suma de todas tus cuentas.",
            "fecha": now.strftime("%Y-%m-%d %H:%M"),
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def calculate_mortgage(
    property_price: float,
    deposit: float,
    annual_rate_percent: float,
    years: int,
) -> dict:
    """
    Calcula la cuota mensual de una hipoteca y genera la tabla de amortización anual.
    Usa este tool SIEMPRE que el usuario pregunte por hipotecas, préstamos o cuotas.
    No hagas los cálculos tú mismo.

    Args:
        property_price: Precio total del inmueble en euros.
        deposit: Entrada inicial (señal) en euros.
        annual_rate_percent: Tipo de interés anual en porcentaje (ej: 4.0 para 4%).
        years: Plazo en años.
    """
    principal = property_price - deposit
    if principal <= 0:
        return {"error": "La entrada es mayor o igual al precio del inmueble."}
    if annual_rate_percent <= 0 or years <= 0:
        return {"error": "El tipo de interés y el plazo deben ser mayores que cero."}

    monthly_rate = annual_rate_percent / 100 / 12
    n_payments = years * 12
    factor = (1 + monthly_rate) ** n_payments
    monthly_payment = principal * monthly_rate * factor / (factor - 1)

    amortization = []
    balance = principal
    for year in range(1, years + 1):
        year_interest = 0.0
        year_capital = 0.0
        for _ in range(12):
            interest = balance * monthly_rate
            capital = monthly_payment - interest
            year_interest += interest
            year_capital += capital
            balance -= capital
            if balance < 0:
                balance = 0.0
        amortization.append({
            "año": year,
            "cuota_anual": round(monthly_payment * 12, 2),
            "intereses": round(year_interest, 2),
            "capital_amortizado": round(year_capital, 2),
            "capital_pendiente": round(max(balance, 0), 2),
        })

    total_pagado = round(monthly_payment * n_payments, 2)
    total_intereses = round(total_pagado - principal, 2)

    return {
        "principal": round(principal, 2),
        "cuota_mensual": round(monthly_payment, 2),
        "total_pagado": total_pagado,
        "total_intereses": total_intereses,
        "tabla_amortizacion": amortization,
    }


@mcp.tool()
def calculate_loan(
    principal: float,
    annual_rate_percent: float,
    years: int,
) -> dict:
    """
    Calcula la cuota mensual de un préstamo personal o cualquier financiación
    (sin precio de inmueble). Úsalo para préstamos de coche, personal, etc.
    Nunca hagas este cálculo tú mismo.

    Args:
        principal: Capital prestado en euros.
        annual_rate_percent: Tipo de interés anual en % (ej: 6.5).
        years: Plazo en años.
    """
    if principal <= 0 or annual_rate_percent <= 0 or years <= 0:
        return {"error": "Todos los valores deben ser mayores que cero."}

    monthly_rate = annual_rate_percent / 100 / 12
    n = years * 12
    factor = (1 + monthly_rate) ** n
    monthly_payment = principal * monthly_rate * factor / (factor - 1)
    total_pagado = monthly_payment * n
    total_intereses = total_pagado - principal

    return {
        "capital": round(principal, 2),
        "cuota_mensual": round(monthly_payment, 2),
        "total_pagado": round(total_pagado, 2),
        "total_intereses": round(total_intereses, 2),
        "plazo_meses": n,
    }


@mcp.tool()
def calculate_compound_interest(
    initial_amount: float,
    monthly_contribution: float,
    annual_rate_percent: float,
    years: int,
) -> dict:
    """
    Calcula el resultado de un ahorro o inversión con interés compuesto,
    con o sin aportaciones mensuales. Úsalo para preguntas como
    "si ahorro X€/mes durante Y años al Z%, ¿cuánto tendré?".
    Nunca hagas este cálculo tú mismo.

    Args:
        initial_amount: Capital inicial en euros (puede ser 0).
        monthly_contribution: Aportación mensual en euros (puede ser 0).
        annual_rate_percent: Rentabilidad anual esperada en % (ej: 4.0).
        years: Horizonte temporal en años.
    """
    monthly_rate = annual_rate_percent / 100 / 12
    n = years * 12
    balance = initial_amount

    yearly = []
    for year in range(1, years + 1):
        for _ in range(12):
            balance = balance * (1 + monthly_rate) + monthly_contribution
        yearly.append({"año": year, "saldo": round(balance, 2)})

    total_aportado = initial_amount + monthly_contribution * n
    ganancia = balance - total_aportado

    return {
        "saldo_final": round(balance, 2),
        "total_aportado": round(total_aportado, 2),
        "ganancia_por_interes": round(ganancia, 2),
        "evolucion_anual": yearly,
    }


@mcp.tool()
def calculate_savings_goal(
    goal_amount: float,
    monthly_savings: float,
    annual_rate_percent: float = 0.0,
) -> dict:
    """
    Calcula cuánto tiempo se tarda en alcanzar un objetivo de ahorro
    guardando una cantidad fija al mes, con o sin rentabilidad.
    Úsalo para preguntas como "¿cuánto tardo en ahorrar X€ guardando Y€/mes?".
    Nunca hagas este cálculo tú mismo.

    Args:
        goal_amount: Objetivo de ahorro en euros.
        monthly_savings: Cantidad que se ahorra cada mes en euros.
        annual_rate_percent: Rentabilidad anual en % (0 si es cuenta sin intereses).
    """
    if monthly_savings <= 0:
        return {"error": "El ahorro mensual debe ser mayor que cero."}
    if goal_amount <= 0:
        return {"error": "El objetivo debe ser mayor que cero."}

    monthly_rate = annual_rate_percent / 100 / 12

    if monthly_rate == 0:
        months = goal_amount / monthly_savings
    else:
        import math
        months = math.log(1 + goal_amount * monthly_rate / monthly_savings) / math.log(1 + monthly_rate)

    years = int(months // 12)
    remaining_months = round(months % 12)

    return {
        "meses_totales": round(months),
        "años": years,
        "meses_adicionales": remaining_months,
        "descripcion": f"{years} años y {remaining_months} meses" if years > 0 else f"{round(months)} meses",
    }


@mcp.tool()
def calculate_budget_distribution(monthly_income: float) -> dict:
    """
    Aplica la regla 50/30/20 para distribuir los ingresos mensuales:
    50% necesidades, 30% ocio, 20% ahorro.
    Úsalo cuando el usuario pregunte cómo distribuir su sueldo o presupuesto.
    Nunca hagas este cálculo tú mismo.

    Args:
        monthly_income: Ingresos mensuales netos en euros.
    """
    if monthly_income <= 0:
        return {"error": "Los ingresos deben ser mayores que cero."}

    return {
        "ingresos_mensuales": round(monthly_income, 2),
        "necesidades_50pct": round(monthly_income * 0.50, 2),
        "ocio_30pct": round(monthly_income * 0.30, 2),
        "ahorro_20pct": round(monthly_income * 0.20, 2),
        "descripcion": "Regla 50/30/20: necesidades / ocio / ahorro",
    }


@mcp.tool()
def get_income_by_period(period: str = "current_month", user_id: int = 1) -> dict:
    """Obtiene los ingresos del usuario en un período concreto: nómina, freelance, etc.
    Úsalo para responder '¿cuánto he cobrado este mes?', '¿cuál es mi salario este mes?',
    '¿cuánto ingresé el mes pasado?'.

    Períodos válidos: current_month, last_month, last_3_months, all_time.
    """
    db = SessionLocal()
    try:
        start, end = _period_dates(period)
        rows = db.query(
            Transaction.merchant,
            Transaction.description,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("count"),
        ).filter(
            Transaction.user_id == user_id,
            Transaction.transaction_type == "ingreso",
            Transaction.date >= start,
            Transaction.date <= end,
        ).group_by(Transaction.merchant, Transaction.description).order_by(
            func.sum(Transaction.amount).desc()
        ).all()

        total = sum(r.total for r in rows)

        return {
            "period": period,
            "total_ingresos": round(total, 2),
            "detalle": [
                {
                    "comercio": r.merchant,
                    "descripcion": r.description,
                    "total": round(r.total, 2),
                    "veces": r.count,
                }
                for r in rows
            ],
        }
    finally:
        db.close()


@mcp.tool()
def get_account_balances(user_id: int = 1) -> dict:
    """Devuelve el saldo de cada cuenta del usuario por separado (corriente, ahorro, etc.)
    y el saldo total. Úsalo cuando el usuario pregunte por el saldo de una cuenta concreta,
    o para aclarar cuánto tiene en el ahorro vs en la cuenta corriente.
    """
    db = SessionLocal()
    try:
        accounts = db.query(Account).filter(Account.user_id == user_id).all()
        cuentas = [
            {"tipo": a.account_type, "nombre": a.name, "saldo": round(a.balance, 2), "moneda": a.currency}
            for a in accounts
        ]
        total = round(sum(a.balance for a in accounts), 2)
        return {"cuentas": cuentas, "saldo_total": total}
    finally:
        db.close()


@mcp.tool()
def get_bizum_history(limit: int = 10, user_id: int = 1) -> dict:
    """Obtiene el historial de transferencias Bizum realizadas por el usuario."""
    db = SessionLocal()
    try:
        rows = db.query(BizumTransfer).filter(
            BizumTransfer.user_id == user_id,
        ).order_by(BizumTransfer.executed_at.desc()).limit(limit).all()

        return {
            "bizum_transfers": [
                {
                    "fecha": r.executed_at.strftime("%Y-%m-%d %H:%M"),
                    "destinatario": r.recipient,
                    "concepto": r.concept,
                    "importe": round(r.amount, 2),
                    "estado": r.status,
                }
                for r in rows
            ]
        }
    finally:
        db.close()


# ── Inversiones y mercados ─────────────────────────────────────────────────────

@mcp.tool()
def get_portfolio(user_id: int = 1) -> dict:
    """Obtiene la cartera de inversiones del usuario con precios actualizados del mercado
    en tiempo real (acciones, ETFs, fondos indexados). Calcula rentabilidad por activo y total.
    Úsalo para '¿cómo va mi cartera?', '¿cuánto vale mi inversión?', '¿cuánto he ganado?'."""
    db = SessionLocal()
    try:
        investments = db.query(Investment).filter(Investment.user_id == user_id).all()
        if not investments:
            return {"activos": [], "resumen": {}, "mensaje": "No tienes inversiones registradas en tu cartera."}

        activos = []
        valor_total = 0.0
        coste_total = 0.0

        for inv in investments:
            current_price = inv.avg_purchase_price
            try:
                fast = yf.Ticker(inv.ticker).fast_info
                price = fast.last_price
                if price and price == price:
                    current_price = price
            except Exception:
                pass

            valor_actual = round(current_price * inv.shares, 2)
            coste = round(inv.avg_purchase_price * inv.shares, 2)
            ganancia = round(valor_actual - coste, 2)
            ganancia_pct = round((ganancia / coste) * 100, 2) if coste > 0 else 0.0

            valor_total += valor_actual
            coste_total += coste

            activos.append({
                "ticker": inv.ticker,
                "nombre": inv.name,
                "tipo": inv.investment_type,
                "shares": inv.shares,
                "precio_compra_medio": inv.avg_purchase_price,
                "precio_actual": round(current_price, 4),
                "valor_actual": valor_actual,
                "coste_total": coste,
                "ganancia_perdida": ganancia,
                "ganancia_perdida_pct": ganancia_pct,
                "moneda": inv.currency,
            })

        coste_total = round(coste_total, 2)
        valor_total = round(valor_total, 2)
        ganancia_total = round(valor_total - coste_total, 2)
        ganancia_total_pct = round((ganancia_total / coste_total) * 100, 2) if coste_total > 0 else 0.0

        return {
            "activos": activos,
            "resumen": {
                "valor_total": valor_total,
                "coste_total": coste_total,
                "ganancia_total": ganancia_total,
                "ganancia_total_pct": ganancia_total_pct,
            },
        }
    finally:
        db.close()


@mcp.tool()
def get_asset_details(ticker: str) -> dict:
    """Obtiene información detallada de un activo financiero: precio actual, variación del día,
    PER, dividendo, rango 52 semanas, sector. Úsalo para 'dame info de Apple', '¿cómo está Tesla?'."""
    try:
        ticker = ticker.upper()
        t = yf.Ticker(ticker)
        info = t.info
        fast = t.fast_info

        price = fast.last_price or 0.0
        prev = fast.previous_close or price
        daily_pct = round(((price - prev) / prev) * 100, 2) if prev else 0.0

        return {
            "ticker": ticker,
            "nombre": info.get("longName") or info.get("shortName", ticker),
            "precio_actual": round(price, 4),
            "variacion_dia_pct": daily_pct,
            "moneda": info.get("currency", "USD"),
            "sector": info.get("sector", "N/D"),
            "industria": info.get("industry", "N/D"),
            "pe_ratio": round(info.get("trailingPE") or 0, 2),
            "dividendo_rendimiento_pct": round((info.get("dividendYield") or 0) * 100, 2),
            "rango_52_semanas_min": round(info.get("fiftyTwoWeekLow") or 0, 2),
            "rango_52_semanas_max": round(info.get("fiftyTwoWeekHigh") or 0, 2),
            "capitalizacion_mercado": info.get("marketCap"),
            "descripcion": (info.get("longBusinessSummary") or "")[:400],
        }
    except Exception as e:
        return {"error": f"No se pudo obtener información de '{ticker}': {str(e)[:120]}"}


@mcp.tool()
def get_market_overview() -> dict:
    """Obtiene el estado actual de los principales índices bursátiles y mercados globales.
    Úsalo para '¿cómo están los mercados?', '¿sube o baja la bolsa hoy?'."""
    MARKETS = [
        ("^GSPC", "S&P 500"),
        ("^IXIC", "Nasdaq"),
        ("^IBEX", "IBEX 35"),
        ("^STOXX50E", "Euro Stoxx 50"),
        ("GC=F", "Oro"),
    ]

    mercados = []
    for symbol, name in MARKETS:
        try:
            fast = yf.Ticker(symbol).fast_info
            price = fast.last_price or 0.0
            prev = fast.previous_close or price
            change_pct = round(((price - prev) / prev) * 100, 2) if prev else 0.0
            mercados.append({
                "nombre": name,
                "ticker": symbol,
                "precio": round(price, 2),
                "variacion_dia_pct": change_pct,
            })
        except Exception:
            mercados.append({"nombre": name, "ticker": symbol, "precio": None, "variacion_dia_pct": None})

    return {"mercados": mercados, "fecha": datetime.now().strftime("%Y-%m-%d %H:%M")}


@mcp.tool()
def get_portfolio_news(user_id: int = 1, max_per_ticker: int = 3) -> dict:
    """Obtiene noticias recientes de los activos que el usuario tiene en cartera, vía
    yfinance. Uso exclusivo del job de generación del dashboard proactivo (no se expone
    al chat conversacional para no gastar tokens/tiempo en cada mensaje)."""
    portfolio = get_portfolio(user_id=user_id)
    tickers = [a["ticker"] for a in portfolio.get("activos", [])]

    noticias = []
    for ticker in tickers:
        try:
            items = yf.Ticker(ticker).news or []
        except Exception:
            items = []

        for item in items[:max_per_ticker]:
            content = item.get("content", item)  # formatos antiguos de yfinance no anidan en "content"
            pub_date = content.get("pubDate") or content.get("providerPublishTime")
            noticias.append({
                "ticker": ticker,
                "titulo": content.get("title", ""),
                "fuente": (content.get("provider") or {}).get("displayName", "N/D"),
                "fecha": pub_date,
            })

    return {"noticias": noticias}


@mcp.tool()
def add_investment(
    user_id: int,
    ticker: str,
    shares: float,
    avg_purchase_price: float,
    investment_type: str = "accion",
) -> dict:
    """Registra una compra de activo financiero en la cartera del usuario.

    IMPORTANTE: DEBES haber confirmado con el usuario el ticker, número de acciones
    y precio de compra ANTES de llamar a esta función.

    Args:
        user_id: ID del usuario.
        ticker: Símbolo del activo (ej: AAPL, VOO, SAN.MC, IWDA.AS).
        shares: Número de acciones/participaciones compradas (> 0).
        avg_purchase_price: Precio de compra por acción/participación (> 0).
        investment_type: Tipo: accion, etf, fondo_indexado.
    """
    if shares <= 0 or avg_purchase_price <= 0:
        return {"success": False, "error": "El número de acciones y el precio deben ser mayores que cero."}

    ticker = ticker.upper()

    try:
        t = yf.Ticker(ticker)
        fast = t.fast_info
        info = t.info
        name = info.get("longName") or info.get("shortName") or ticker
        currency = getattr(fast, "currency", None) or info.get("currency", "USD")
        if not fast.last_price:
            return {"success": False, "error": f"Ticker '{ticker}' no encontrado o sin cotización activa."}
    except Exception as e:
        return {"success": False, "error": f"Ticker '{ticker}' no válido: {str(e)[:120]}"}

    db = SessionLocal()
    try:
        existing = db.query(Investment).filter(
            Investment.user_id == user_id,
            Investment.ticker == ticker,
        ).first()

        if existing:
            total_shares = existing.shares + shares
            new_avg = (existing.shares * existing.avg_purchase_price + shares * avg_purchase_price) / total_shares
            existing.shares = round(total_shares, 6)
            existing.avg_purchase_price = round(new_avg, 4)
            db.commit()
            return {
                "success": True,
                "ticker": ticker,
                "nombre": existing.name,
                "shares_total": round(total_shares, 6),
                "precio_medio": round(new_avg, 4),
                "moneda": currency,
                "operacion": "actualizado",
            }
        else:
            inv = Investment(
                user_id=user_id,
                ticker=ticker,
                name=name,
                investment_type=investment_type,
                shares=round(shares, 6),
                avg_purchase_price=round(avg_purchase_price, 4),
                currency=currency,
                purchase_date=datetime.now(),
            )
            db.add(inv)
            db.commit()
            return {
                "success": True,
                "ticker": ticker,
                "nombre": name,
                "shares_total": round(shares, 6),
                "precio_medio": round(avg_purchase_price, 4),
                "moneda": currency,
                "operacion": "añadido",
            }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def create_goal(
    user_id: int,
    name: str,
    target_amount: float,
    current_amount: float = 0.0,
    deadline: str | None = None,
) -> dict:
    """Crea un objetivo de ahorro nuevo para el usuario (ej: "entrada para vivienda",
    "viaje a Japón", "fondo de emergencia"). No requiere confirmación previa del usuario:
    a diferencia de un Bizum o una inversión, crear un objetivo no mueve dinero ni es
    irreversible — el usuario puede pedir que se borre o se corrija después.

    Args:
        user_id: ID del usuario.
        name: Nombre descriptivo del objetivo.
        target_amount: Importe objetivo en euros (> 0).
        current_amount: Importe ya ahorrado hacia el objetivo (>= 0, por defecto 0).
        deadline: Fecha límite en formato YYYY-MM-DD, o None si no tiene.
    """
    if target_amount <= 0:
        return {"success": False, "error": "El importe objetivo debe ser mayor que 0€."}
    if current_amount < 0:
        return {"success": False, "error": "El importe ya ahorrado no puede ser negativo."}
    if current_amount > target_amount:
        return {"success": False, "error": "El importe ya ahorrado no puede superar el objetivo."}

    deadline_dt = None
    if deadline:
        try:
            deadline_dt = datetime.strptime(deadline, "%Y-%m-%d")
        except ValueError:
            return {"success": False, "error": "La fecha límite debe tener formato YYYY-MM-DD."}

    db = SessionLocal()
    try:
        goal = Goal(
            user_id=user_id,
            name=name,
            target_amount=round(target_amount, 2),
            current_amount=round(current_amount, 2),
            deadline=deadline_dt,
            status="active",
            created_at=datetime.now(),
        )
        db.add(goal)
        db.commit()
        db.refresh(goal)

        return {
            "success": True,
            "id": goal.id,
            "nombre": goal.name,
            "objetivo": goal.target_amount,
            "ahorrado": goal.current_amount,
            "fecha_limite": goal.deadline.strftime("%Y-%m-%d") if goal.deadline else None,
            "progreso_pct": round(goal.current_amount / goal.target_amount * 100, 1),
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()


@mcp.tool()
def list_goals(user_id: int = 1, status: str = "active") -> dict:
    """Lista los objetivos de ahorro del usuario.

    Args:
        user_id: ID del usuario.
        status: Filtra por estado: active, completed, cancelled, o "all" para todos.
    """
    db = SessionLocal()
    try:
        query = db.query(Goal).filter(Goal.user_id == user_id)
        if status != "all":
            query = query.filter(Goal.status == status)
        goals = query.order_by(Goal.created_at.desc()).all()

        return {
            "objetivos": [
                {
                    "id": g.id,
                    "nombre": g.name,
                    "objetivo": g.target_amount,
                    "ahorrado": g.current_amount,
                    "progreso_pct": round(g.current_amount / g.target_amount * 100, 1) if g.target_amount else 0,
                    "fecha_limite": g.deadline.strftime("%Y-%m-%d") if g.deadline else None,
                    "estado": g.status,
                }
                for g in goals
            ]
        }
    finally:
        db.close()


@mcp.tool()
def update_goal_progress(goal_id: int, new_current_amount: float, user_id: int = 1) -> dict:
    """Actualiza el importe ahorrado de un objetivo existente. Si el nuevo importe alcanza
    o supera el objetivo, lo marca automáticamente como "completed".

    Args:
        goal_id: ID del objetivo (obtenido con list_goals).
        new_current_amount: Nuevo importe total ahorrado hacia el objetivo (>= 0).
        user_id: ID del usuario, para verificar que el objetivo le pertenece.
    """
    if new_current_amount < 0:
        return {"success": False, "error": "El importe ahorrado no puede ser negativo."}

    db = SessionLocal()
    try:
        goal = db.query(Goal).filter(Goal.id == goal_id, Goal.user_id == user_id).first()
        if not goal:
            return {"success": False, "error": f"No se encontró el objetivo {goal_id} para este usuario."}

        goal.current_amount = round(new_current_amount, 2)
        if goal.current_amount >= goal.target_amount:
            goal.status = "completed"
        db.commit()

        return {
            "success": True,
            "id": goal.id,
            "nombre": goal.name,
            "ahorrado": goal.current_amount,
            "objetivo": goal.target_amount,
            "estado": goal.status,
            "progreso_pct": round(goal.current_amount / goal.target_amount * 100, 1),
        }
    except Exception as e:
        db.rollback()
        return {"success": False, "error": str(e)}
    finally:
        db.close()
