from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.financial import Account, Transaction
from app.schemas.financial import SummaryOut, TransactionOut


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
