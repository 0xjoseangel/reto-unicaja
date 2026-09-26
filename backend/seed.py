"""Populates SQLite with 12 months of realistic mock financial data."""
import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from app.core.database import SessionLocal
from app.core.security import hash_password
from app.models.financial import Account, Goal, Investment, Transaction, User

EXPENSE_CATEGORIES = {
    "restaurantes": (15, 80),
    "supermercado": (40, 120),
    "transporte": (10, 60),
    "alquiler": (650, 650),
    "ocio": (10, 50),
    "salud": (20, 100),
    "ropa": (30, 150),
    "servicios": (80, 150),
}

EXPENSE_FREQUENCY = {
    "restaurantes": 6,
    "supermercado": 4,
    "transporte": 8,
    "alquiler": 1,
    "ocio": 3,
    "salud": 1,
    "ropa": 1,
    "servicios": 1,
}

# (merchant, description) pairs per category
EXPENSE_MERCHANTS: dict[str, list[tuple[str, str]]] = {
    "restaurantes": [
        ("El Rincón de Madrid", "Menú del día"),
        ("Burger King", "Combo hamburguesa"),
        ("La Taberna", "Cena con amigos"),
        ("Sushi Bar", "Sushi combinado"),
        ("Pizzería Bella", "Pizza familiar"),
    ],
    "supermercado": [
        ("Mercadona", "Compra semanal"),
        ("Lidl", "Compra semanal"),
        ("Carrefour", "Compra mensual"),
        ("Aldi", "Compra semanal"),
        ("El Corte Inglés", "Alimentación"),
    ],
    "transporte": [
        ("Repsol", "Gasolina"),
        ("Metro Granada", "Tarjeta mensual"),
        ("Renfe", "Billete AVE"),
        ("Uber", "Viaje urbano"),
        ("EMT Granada", "Bus urbano"),
    ],
    "alquiler": [
        ("Inmobiliaria Gil", "Alquiler piso Calle Granada"),
    ],
    "ocio": [
        ("Netflix", "Suscripción mensual"),
        ("Spotify", "Premium mensual"),
        ("Cine Yelmo", "Entrada cine"),
        ("Ticketmaster", "Concierto"),
        ("La Casa del Libro", "Libros"),
    ],
    "salud": [
        ("Farmacia Central", "Medicamentos"),
        ("Clínica San Juan", "Consulta médico privado"),
        ("Dentista Marbella", "Revisión dental"),
    ],
    "ropa": [
        ("Zara", "Ropa temporada"),
        ("Mango", "Ropa temporada"),
        ("H&M", "Ropa casual"),
        ("El Corte Inglés", "Ropa y calzado"),
    ],
    "servicios": [
        ("Endesa", "Factura luz"),
        ("Aguas de Granada", "Factura agua"),
        ("Vodafone", "Factura internet y móvil"),
        ("Mapfre", "Seguro hogar"),
    ],
}


def random_day_in_month(year: int, month: int) -> datetime:
    import calendar
    max_day = calendar.monthrange(year, month)[1]
    day = random.randint(1, max_day)
    hour = random.randint(8, 22)
    minute = random.randint(0, 59)
    return datetime(year, month, day, hour, minute)


def seed():
    db = SessionLocal()

    if db.query(User).count() > 0:
        print("Base de datos ya tiene datos. Saltando seed.")
        db.close()
        return

    now = datetime.now()

    user = User(
        name="Jose Angel Carretero",
        email="joseangelcarretero300@gmail.com",
        password_hash=hash_password("demo1234"),
        created_at=now,
    )
    db.add(user)
    db.flush()

    checking = Account(
        user_id=user.id, name="Cuenta Corriente",
        account_type="corriente", balance=2850.40, currency="EUR",
    )
    savings = Account(
        user_id=user.id, name="Cuenta Ahorro",
        account_type="ahorro", balance=8500.00, currency="EUR",
    )
    db.add_all([checking, savings])
    db.flush()

    transactions = []

    for months_back in range(11, -1, -1):
        target = now - timedelta(days=months_back * 30)
        year, month = target.year, target.month

        # Nómina mensual
        salary = round(random.uniform(1900, 2100), 2)
        transactions.append(Transaction(
            account_id=checking.id,
            user_id=user.id,
            amount=salary,
            transaction_type="ingreso",
            category="salario",
            merchant="TechCorp S.L.",
            description="Nómina mensual",
            source="salary",
            date=datetime(year, month, 1, 9, 0),
        ))

        # Ingreso extra ocasional (freelance)
        if random.random() < 0.3:
            transactions.append(Transaction(
                account_id=savings.id,
                user_id=user.id,
                amount=round(random.uniform(100, 500), 2),
                transaction_type="ingreso",
                category="salario",
                merchant="Cliente freelance",
                description="Trabajo freelance",
                source="manual",
                date=random_day_in_month(year, month),
            ))

        # Gastos por categoría
        for category, (min_amt, max_amt) in EXPENSE_CATEGORIES.items():
            freq = EXPENSE_FREQUENCY[category]
            options = EXPENSE_MERCHANTS[category]
            for _ in range(freq):
                merchant, description = random.choice(options)
                transactions.append(Transaction(
                    account_id=checking.id,
                    user_id=user.id,
                    amount=round(random.uniform(min_amt, max_amt), 2),
                    transaction_type="gasto",
                    category=category,
                    merchant=merchant,
                    description=description,
                    source="manual",
                    date=random_day_in_month(year, month),
                ))

    db.add_all(transactions)

    # Metas de ejemplo
    goals = [
        Goal(
            user_id=user.id,
            name="Entrada para vivienda",
            target_amount=30000.00,
            current_amount=8500.00,
            deadline=datetime(2027, 12, 31),
            status="active",
            created_at=now,
        ),
        Goal(
            user_id=user.id,
            name="Fondo de emergencia (6 meses)",
            target_amount=12000.00,
            current_amount=8500.00,
            deadline=None,
            status="active",
            created_at=now,
        ),
    ]
    db.add_all(goals)

    db.commit()
    db.close()

    print(
        f"Seed completado: 1 usuario, 2 cuentas, {len(transactions)} transacciones, "
        f"{len(goals)} metas."
    )


def seed_investments():
    db = SessionLocal()
    try:
        if db.query(Investment).count() > 0:
            print("Inversiones ya seeded. Saltando.")
            return

        user = db.query(User).first()
        if not user:
            print("Error: no hay usuario. Ejecuta seed() primero.")
            return

        investments = [
            Investment(
                user_id=user.id, ticker="AAPL", name="Apple Inc.",
                investment_type="accion", shares=10, avg_purchase_price=145.00,
                currency="USD", purchase_date=datetime(2023, 3, 15),
            ),
            Investment(
                user_id=user.id, ticker="MSFT", name="Microsoft Corp.",
                investment_type="accion", shares=5, avg_purchase_price=310.00,
                currency="USD", purchase_date=datetime(2023, 6, 20),
            ),
            Investment(
                user_id=user.id, ticker="VOO", name="Vanguard S&P 500 ETF",
                investment_type="etf", shares=8, avg_purchase_price=390.00,
                currency="USD", purchase_date=datetime(2022, 11, 10),
            ),
            Investment(
                user_id=user.id, ticker="IWDA.AS", name="iShares Core MSCI World ETF",
                investment_type="fondo_indexado", shares=50, avg_purchase_price=82.00,
                currency="EUR", purchase_date=datetime(2022, 8, 5),
            ),
            Investment(
                user_id=user.id, ticker="SAN.MC", name="Banco Santander S.A.",
                investment_type="accion", shares=200, avg_purchase_price=3.80,
                currency="EUR", purchase_date=datetime(2023, 9, 1),
            ),
        ]
        db.add_all(investments)
        db.commit()
        print(f"Inversiones seeded: {len(investments)} activos registrados.")
    finally:
        db.close()


def _seed_user_transactions(db, user, checking, savings, months: int = 12):
    """Genera transacciones para un usuario dado con los parámetros de sus cuentas."""
    transactions = []
    now = datetime.now()

    for months_back in range(months - 1, -1, -1):
        target = now - timedelta(days=months_back * 30)
        year, month = target.year, target.month

        salary = round(random.uniform(1900, 2100), 2)
        transactions.append(Transaction(
            account_id=checking.id,
            user_id=user.id,
            amount=salary,
            transaction_type="ingreso",
            category="salario",
            merchant="TechCorp S.L.",
            description="Nómina mensual",
            source="salary",
            date=datetime(year, month, 1, 9, 0),
        ))

        if random.random() < 0.3:
            transactions.append(Transaction(
                account_id=savings.id,
                user_id=user.id,
                amount=round(random.uniform(100, 500), 2),
                transaction_type="ingreso",
                category="salario",
                merchant="Cliente freelance",
                description="Trabajo freelance",
                source="manual",
                date=random_day_in_month(year, month),
            ))

        for category, (min_amt, max_amt) in EXPENSE_CATEGORIES.items():
            freq = EXPENSE_FREQUENCY[category]
            options = EXPENSE_MERCHANTS[category]
            for _ in range(freq):
                merchant, description = random.choice(options)
                transactions.append(Transaction(
                    account_id=checking.id,
                    user_id=user.id,
                    amount=round(random.uniform(min_amt, max_amt), 2),
                    transaction_type="gasto",
                    category=category,
                    merchant=merchant,
                    description=description,
                    source="manual",
                    date=random_day_in_month(year, month),
                ))

    db.add_all(transactions)
    return len(transactions)


TEST_USERS = [
    {
        # Perfil "alto patrimonio": mucho colchón, ingresos altos y estables, cartera de
        # inversión relevante, gasto elevado pero controlado — el dashboard debería
        # priorizar progreso de metas y alertas de oportunidad de inversión, no avisos de gasto.
        "name": "Alejandro Fernández Ruiz",
        "email": "alejandro.fernandez@test.com",
        "password": "test1234",
        "balance_checking": 15420.90,
        "balance_savings": 92000.00,
        "expense_multiplier": 2.1,
        "salary_range": (6500, 7200),
        "salary_category": "salario",
        "salary_merchant": "Consultora Fernández & Asociados",
        "salary_description": "Nómina mensual (socio)",
        "category_multipliers": {"restaurantes": 3.0, "ropa": 2.5, "ocio": 2.0},
        "goals": [
            {"name": "Segunda vivienda en la costa", "target": 220000.0, "current": 92000.0, "deadline": "2028-06-30"},
            {"name": "Jubilación anticipada", "target": 500000.0, "current": 145000.0, "deadline": "2040-01-01"},
        ],
        "investments": [
            {"ticker": "AAPL", "name": "Apple Inc.", "investment_type": "accion", "shares": 80, "avg_purchase_price": 140.00, "currency": "USD", "purchase_date": "2021-04-10"},
            {"ticker": "MSFT", "name": "Microsoft Corp.", "investment_type": "accion", "shares": 45, "avg_purchase_price": 260.00, "currency": "USD", "purchase_date": "2021-09-15"},
            {"ticker": "VOO", "name": "Vanguard S&P 500 ETF", "investment_type": "etf", "shares": 120, "avg_purchase_price": 350.00, "currency": "USD", "purchase_date": "2020-11-02"},
            {"ticker": "IWDA.AS", "name": "iShares Core MSCI World ETF", "investment_type": "fondo_indexado", "shares": 400, "avg_purchase_price": 70.00, "currency": "EUR", "purchase_date": "2019-05-20"},
            {"ticker": "SAN.MC", "name": "Banco Santander S.A.", "investment_type": "accion", "shares": 3000, "avg_purchase_price": 3.10, "currency": "EUR", "purchase_date": "2020-02-10"},
        ],
    },
    {
        # Perfil "estudiante sin un duro": ingreso muy bajo e irregular (beca + trabajo
        # parcial), casi sin ahorro, gasto mínimo — el dashboard debería priorizar avisos
        # de presupuesto ajustado, no oportunidades de inversión.
        "name": "Lucía Moreno Díaz",
        "email": "lucia.moreno@test.com",
        "password": "test1234",
        "balance_checking": 42.15,
        "balance_savings": 0.00,
        "expense_multiplier": 0.35,
        "salary_range": (350, 480),
        "salary_category": "beca",
        "salary_merchant": "Universidad de Granada",
        "salary_description": "Beca + trabajo parcial",
        "category_multipliers": {"alquiler": 0.55, "restaurantes": 0.3, "ropa": 0.2, "salud": 0.2},
        "goals": [
            {"name": "Portátil nuevo para clase", "target": 900.0, "current": 45.0, "deadline": "2026-02-01"},
        ],
        "investments": [],
    },
    {
        # Perfil "pensionista": ingreso fijo bajo pero muy estable (pensión), ahorro
        # acumulado de toda la vida laboral, gasto conservador salvo en salud — el
        # dashboard debería mostrar estabilidad, no anomalías, y priorizar salud/ocio.
        "name": "Manuel Torres Jiménez",
        "email": "manuel.torres@test.com",
        "password": "test1234",
        "balance_checking": 2180.60,
        "balance_savings": 48500.00,
        "expense_multiplier": 0.6,
        "salary_range": (1250, 1250),
        "salary_category": "pension",
        "salary_merchant": "Seguridad Social",
        "salary_description": "Pensión de jubilación",
        "category_multipliers": {"salud": 2.8, "ocio": 0.7, "ropa": 0.4, "transporte": 0.5},
        "goals": [
            {"name": "Crucero por el Mediterráneo", "target": 6000.0, "current": 3400.0, "deadline": "2026-05-01"},
        ],
        "investments": [],
    },
]


def seed_test_users():
    """Añade usuarios de prueba adicionales a la BD existente."""
    db = SessionLocal()
    now = datetime.now()
    created = 0

    for profile in TEST_USERS:
        existing = db.query(User).filter(User.email == profile["email"]).first()
        if existing:
            print(f"  Usuario {profile['email']} ya existe. Saltando.")
            continue

        user = User(
            name=profile["name"],
            email=profile["email"],
            password_hash=hash_password(profile["password"]),
            created_at=now,
        )
        db.add(user)
        db.flush()

        checking = Account(
            user_id=user.id,
            name="Cuenta Corriente",
            account_type="corriente",
            balance=profile["balance_checking"],
            currency="EUR",
        )
        savings = Account(
            user_id=user.id,
            name="Cuenta Ahorro",
            account_type="ahorro",
            balance=profile["balance_savings"],
            currency="EUR",
        )
        db.add_all([checking, savings])
        db.flush()

        # Ajustar salario y gastos según el perfil — cada categoría puede tener su propio
        # multiplicador (category_multipliers) además del multiplicador general, para que
        # perfiles como el pensionista (mucho gasto en salud) o el estudiante (casi nada en
        # ropa/ocio) no se queden en una simple escala uniforme.
        mult = profile["expense_multiplier"]
        overrides = profile.get("category_multipliers", {})
        sal_min, sal_max = profile["salary_range"]
        adjusted_categories = {
            cat: (round(mn * overrides.get(cat, mult)), round(mx * overrides.get(cat, mult)))
            for cat, (mn, mx) in EXPENSE_CATEGORIES.items()
        }

        transactions = []
        for months_back in range(11, -1, -1):
            target = now - timedelta(days=months_back * 30)
            year, month = target.year, target.month

            salary = round(random.uniform(sal_min, sal_max), 2)
            transactions.append(Transaction(
                account_id=checking.id,
                user_id=user.id,
                amount=salary,
                transaction_type="ingreso",
                category=profile.get("salary_category", "salario"),
                merchant=profile.get("salary_merchant", "Empresa S.A."),
                description=profile.get("salary_description", "Nómina mensual"),
                source="salary",
                date=datetime(year, month, 1, 9, 0),
            ))

            for category, (min_amt, max_amt) in adjusted_categories.items():
                freq = EXPENSE_FREQUENCY[category]
                options = EXPENSE_MERCHANTS[category]
                for _ in range(freq):
                    merchant, description = random.choice(options)
                    transactions.append(Transaction(
                        account_id=checking.id,
                        user_id=user.id,
                        amount=round(random.uniform(max(1, min_amt), max(2, max_amt)), 2),
                        transaction_type="gasto",
                        category=category,
                        merchant=merchant,
                        description=description,
                        source="manual",
                        date=random_day_in_month(year, month),
                    ))

        db.add_all(transactions)

        goals = []
        for g in profile["goals"]:
            deadline = datetime.strptime(g["deadline"], "%Y-%m-%d") if g.get("deadline") else None
            goals.append(Goal(
                user_id=user.id,
                name=g["name"],
                target_amount=g["target"],
                current_amount=g["current"],
                deadline=deadline,
                status="active",
                created_at=now,
            ))
        db.add_all(goals)

        investments = [
            Investment(
                user_id=user.id,
                ticker=inv["ticker"],
                name=inv["name"],
                investment_type=inv["investment_type"],
                shares=inv["shares"],
                avg_purchase_price=inv["avg_purchase_price"],
                currency=inv["currency"],
                purchase_date=datetime.strptime(inv["purchase_date"], "%Y-%m-%d"),
            )
            for inv in profile.get("investments", [])
        ]
        db.add_all(investments)

        db.commit()

        print(
            f"  Creado: {profile['name']} ({profile['email']}) — "
            f"{len(transactions)} transacciones, {len(goals)} metas, {len(investments)} inversiones"
        )
        created += 1

    db.close()
    if created == 0:
        print("Todos los usuarios de prueba ya existían.")
    else:
        print(f"\nTotal: {created} usuario(s) de prueba añadido(s).")


if __name__ == "__main__":
    seed()
    seed_investments()
    print("\nSeedando usuarios de prueba...")
    seed_test_users()
