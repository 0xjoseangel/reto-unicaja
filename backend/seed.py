"""Populates SQLite with 12 months of realistic mock financial data."""
import os
import random
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))

from app.core.database import Base, SessionLocal, engine
from app.models.financial import Account, Transaction, User

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

EXPENSE_DESCRIPTIONS = {
    "restaurantes": ["El Rincón de Madrid", "Burger King", "La Taberna", "Sushi Bar", "Pizzería Bella"],
    "supermercado": ["Mercadona", "Lidl", "Carrefour", "Aldi", "El Corte Inglés alimentación"],
    "transporte": ["Gasolinera Repsol", "Metro mensual", "Renfe AVE", "Uber", "Bus urbano"],
    "alquiler": ["Alquiler piso Calle Granada"],
    "ocio": ["Netflix", "Spotify Premium", "Cine Yelmo", "Concierto", "Librería"],
    "salud": ["Farmacia Central", "Consulta médico privado", "Dentista"],
    "ropa": ["Zara", "Mango", "H&M", "El Corte Inglés moda"],
    "servicios": ["Endesa luz", "Aguas de Granada", "Vodafone internet", "Seguro hogar"],
}


def random_day_in_month(year: int, month: int) -> datetime:
    import calendar
    max_day = calendar.monthrange(year, month)[1]
    day = random.randint(1, max_day)
    hour = random.randint(8, 22)
    minute = random.randint(0, 59)
    return datetime(year, month, day, hour, minute)


def seed():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    if db.query(User).count() > 0:
        print("Base de datos ya tiene datos. Saltando seed.")
        db.close()
        return

    user = User(name="Jose Angel Carretero", email="joseangelcarretero300@gmail.com")
    db.add(user)
    db.flush()

    checking = Account(user_id=user.id, name="Cuenta Corriente", account_type="corriente", balance=2850.40)
    savings = Account(user_id=user.id, name="Cuenta Ahorro", account_type="ahorro", balance=8500.00)
    db.add_all([checking, savings])
    db.flush()

    now = datetime.now()
    transactions = []

    for months_back in range(11, -1, -1):
        target = now - timedelta(days=months_back * 30)
        year, month = target.year, target.month

        # Nómina mensual
        salary = random.uniform(1900, 2100)
        transactions.append(Transaction(
            account_id=checking.id,
            amount=round(salary, 2),
            transaction_type="ingreso",
            category="salario",
            description="Nómina empresa TechCorp",
            date=datetime(year, month, 1, 9, 0),
        ))

        # Ingreso extra ocasional
        if random.random() < 0.3:
            transactions.append(Transaction(
                account_id=savings.id,
                amount=round(random.uniform(100, 500), 2),
                transaction_type="ingreso",
                category="salario",
                description="Trabajo freelance",
                date=random_day_in_month(year, month),
            ))

        # Gastos por categoría
        for category, (min_amt, max_amt) in EXPENSE_CATEGORIES.items():
            freq = EXPENSE_FREQUENCY[category]
            for _ in range(freq):
                amount = round(random.uniform(min_amt, max_amt), 2)
                description = random.choice(EXPENSE_DESCRIPTIONS[category])
                transactions.append(Transaction(
                    account_id=checking.id,
                    amount=amount,
                    transaction_type="gasto",
                    category=category,
                    description=description,
                    date=random_day_in_month(year, month),
                ))

    db.add_all(transactions)
    db.commit()
    db.close()

    total = len(transactions)
    print(f"Seed completado: 1 usuario, 2 cuentas, {total} transacciones generadas.")


if __name__ == "__main__":
    seed()
