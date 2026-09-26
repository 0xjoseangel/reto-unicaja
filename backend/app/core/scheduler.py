"""
Scheduler del dashboard proactivo. Job síncrono (APScheduler BackgroundScheduler,
no async) porque generate_dashboard_cards() ya abre su propia SessionLocal síncrona,
igual que el resto de financial_mcp.py — no hace falta un scheduler async para esto.

Arrancado/parado desde los eventos startup/shutdown de main.py. Además de la
programación automática, existe POST /dashboard/refresh para disparar el mismo
job al momento durante la demo (no se puede esperar a las 22:00 en directo).
"""
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.agent.dashboard_agent import generate_dashboard_cards
from app.core.database import SessionLocal
from app.models.financial import User

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def _generate_for_all_users() -> None:
    """Job nocturno (22:00): tarjetas budget_warning/anomaly/positive/goal_progress
    para cada usuario. El propio prompt del dashboard decide qué tipos generar según
    lo que encuentre relevante — no se fuerza un tipo por llamada."""
    db = SessionLocal()
    try:
        user_ids = [u.id for u in db.query(User.id).all()]
    finally:
        db.close()

    for user_id in user_ids:
        try:
            generate_dashboard_cards(user_id)
        except Exception:
            logger.exception("Fallo generando tarjetas de dashboard para user_id=%s", user_id)


def _generate_weekly_summary() -> None:
    """Job semanal (lunes 09:00): mismo pipeline, el prompt seguirá generando el
    mix de tarjetas que corresponda; el tipo weekly_summary es más probable que
    aparezca al inicio de semana por el contexto acumulado."""
    _generate_for_all_users()


def start_scheduler() -> None:
    scheduler.add_job(
        _generate_for_all_users,
        trigger=CronTrigger(hour=22, minute=0),
        id="nightly_dashboard_analysis",
        replace_existing=True,
    )
    scheduler.add_job(
        _generate_weekly_summary,
        trigger=CronTrigger(day_of_week="mon", hour=9, minute=0),
        id="weekly_summary",
        replace_existing=True,
    )
    scheduler.start()


def stop_scheduler() -> None:
    scheduler.shutdown(wait=False)
