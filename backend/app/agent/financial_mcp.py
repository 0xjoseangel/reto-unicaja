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

        # Período cubierto por los datos
        first = db.query(func.min(Transaction.date)).filter(
            Transaction.account_id.in_(ids),
        ).scalar()
        last = db.query(func.max(Transaction.date)).filter(
            Transaction.account_id.in_(ids),
        ).scalar()

        months = 1
        if first and last:
            delta = (last.year - first.year) * 12 + (last.month - first.month) + 1
            months = max(delta, 1)

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

        # Saldo total = suma de TODAS las cuentas del usuario
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
            "fecha": transaction.date.strftime("%Y-%m-%d %H:%M"),
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

    # Fórmula de cuota fija (sistema francés)
    factor = (1 + monthly_rate) ** n_payments
    monthly_payment = principal * monthly_rate * factor / (factor - 1)

    # Tabla de amortización año a año
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
        ids = _account_ids(db, user_id)
        start, end = _period_dates(period)

        rows = db.query(
            Transaction.description,
            func.sum(Transaction.amount).label("total"),
            func.count(Transaction.id).label("count"),
        ).filter(
            Transaction.account_id.in_(ids),
            Transaction.transaction_type == "ingreso",
            Transaction.date >= start,
            Transaction.date <= end,
        ).group_by(Transaction.description).order_by(
            func.sum(Transaction.amount).desc()
        ).all()

        total = sum(r.total for r in rows)

        return {
            "period": period,
            "total_ingresos": round(total, 2),
            "detalle": [
                {"descripcion": r.description, "total": round(r.total, 2), "veces": r.count}
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
            {"tipo": a.account_type, "saldo": round(a.balance, 2)}
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