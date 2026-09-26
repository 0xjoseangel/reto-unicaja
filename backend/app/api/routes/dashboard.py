import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.agent.dashboard_agent import generate_dashboard_cards
from app.agent.financial_mcp import get_financial_summary
from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.models.financial import Alert
from app.schemas.financial import AlertCardOut, ChartDataPoint

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


def _to_card_out(alert: Alert) -> AlertCardOut:
    chart_data = None
    if alert.chart_data:
        try:
            chart_data = [ChartDataPoint(**d) for d in json.loads(alert.chart_data)]
        except (json.JSONDecodeError, TypeError, ValueError):
            chart_data = None

    return AlertCardOut(
        id=alert.id,
        type=alert.type,
        title=alert.title,
        body=alert.body,
        severity=alert.severity,
        card_type=alert.card_type,
        chart_type=alert.chart_type,
        chart_data=chart_data,
        chart_title=alert.chart_title,
        cta_prompt=alert.cta_prompt,
        seen=alert.seen,
        generated_at=alert.generated_at,
    )


def _active_cards(db: Session, user_id: int) -> list[AlertCardOut]:
    now = datetime.now()
    alerts = (
        db.query(Alert)
        .filter(Alert.user_id == user_id)
        .filter(or_(Alert.expires_at.is_(None), Alert.expires_at > now))
        .all()
    )
    alerts.sort(key=lambda a: (_SEVERITY_ORDER.get(a.severity, 3), -a.generated_at.timestamp()))
    return [_to_card_out(a) for a in alerts]


@router.get("/")
async def get_dashboard(user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    summary = get_financial_summary(user_id=user_id)
    return {
        "resumen": summary,
        "tarjetas": _active_cards(db, user_id),
    }


@router.post("/refresh")
async def refresh_dashboard(user_id: int = Depends(get_current_user), db: Session = Depends(get_db)):
    generate_dashboard_cards(user_id)
    db.expire_all()
    summary = get_financial_summary(user_id=user_id)
    return {
        "resumen": summary,
        "tarjetas": _active_cards(db, user_id),
    }


@router.patch("/alerts/{alert_id}/seen")
async def mark_alert_seen(
    alert_id: int,
    user_id: int = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    alert = db.query(Alert).filter(Alert.id == alert_id, Alert.user_id == user_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    alert.seen = True
    db.commit()
    return {"ok": True}
