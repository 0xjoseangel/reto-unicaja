from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.financial import Account
from app.schemas.financial import AccountOut, SummaryOut, TransactionOut
from app.services.query_service import get_summary, get_transactions

router = APIRouter(prefix="/transactions", tags=["transactions"])


@router.get("/", response_model=list[TransactionOut])
async def list_transactions(
    category: str | None = None,
    transaction_type: str | None = None,
    limit: int = 50,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_transactions(db, user_id, category, transaction_type, limit)


@router.get("/summary", response_model=SummaryOut)
async def summary(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_summary(db, user_id)


@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    accounts = db.query(Account).filter(Account.user_id == user_id).all()
    return [AccountOut.model_validate(a) for a in accounts]
