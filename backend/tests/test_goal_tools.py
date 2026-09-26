"""
Tests de los tools de objetivos (create_goal / list_goals / update_goal_progress),
la pieza que permite al chat crear y gestionar metas de ahorro reales en la BD.

Usan una BD SQLite temporal real (no mocks de la sesión) porque estos tools hacen
consultas con filter/order_by que son frágiles de simular con MagicMock encadenados
— aquí interesa más probar el comportamiento real (validaciones, filtros por estado,
marcado automático como "completed") que aislar la capa de persistencia.
"""
import os
import tempfile
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base
from app.models.financial import User


@pytest.fixture()
def goal_tools(monkeypatch):
    """Crea una BD SQLite temporal, la registra como SessionLocal de financial_mcp,
    inserta un usuario de prueba y devuelve las funciones de tool ya listas para usar."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    import app.agent.financial_mcp as financial_mcp
    monkeypatch.setattr(financial_mcp, "SessionLocal", TestSessionLocal)

    db = TestSessionLocal()
    user = User(name="Test User", email="test@example.com", password_hash="x", created_at=datetime.now())
    db.add(user)
    db.commit()
    db.refresh(user)
    user_id = user.id
    db.close()

    yield financial_mcp, user_id

    os.remove(path)


# ── create_goal ───────────────────────────────────────────────────────────────

def test_create_goal_success(goal_tools):
    financial_mcp, user_id = goal_tools
    result = financial_mcp.create_goal(user_id=user_id, name="Viaje a Japón", target_amount=3000.0, current_amount=500.0)

    assert result["success"] is True
    assert result["nombre"] == "Viaje a Japón"
    assert result["objetivo"] == 3000.0
    assert result["ahorrado"] == 500.0
    assert result["progreso_pct"] == pytest.approx(16.7, abs=0.1)


def test_create_goal_with_deadline(goal_tools):
    financial_mcp, user_id = goal_tools
    result = financial_mcp.create_goal(
        user_id=user_id, name="Casa", target_amount=50000.0, deadline="2028-01-15",
    )
    assert result["success"] is True
    assert result["fecha_limite"] == "2028-01-15"


def test_create_goal_rejects_negative_target(goal_tools):
    financial_mcp, user_id = goal_tools
    result = financial_mcp.create_goal(user_id=user_id, name="x", target_amount=-100.0)
    assert result["success"] is False


def test_create_goal_rejects_current_greater_than_target(goal_tools):
    financial_mcp, user_id = goal_tools
    result = financial_mcp.create_goal(user_id=user_id, name="x", target_amount=100.0, current_amount=500.0)
    assert result["success"] is False


def test_create_goal_rejects_bad_date_format(goal_tools):
    financial_mcp, user_id = goal_tools
    result = financial_mcp.create_goal(user_id=user_id, name="x", target_amount=100.0, deadline="15/01/2028")
    assert result["success"] is False


# ── list_goals ────────────────────────────────────────────────────────────────

def test_list_goals_returns_only_active_by_default(goal_tools):
    financial_mcp, user_id = goal_tools
    financial_mcp.create_goal(user_id=user_id, name="Activo", target_amount=1000.0)
    created = financial_mcp.create_goal(user_id=user_id, name="Completado", target_amount=100.0, current_amount=100.0)
    financial_mcp.update_goal_progress(goal_id=created["id"], new_current_amount=100.0, user_id=user_id)

    result = financial_mcp.list_goals(user_id=user_id, status="active")
    names = [g["nombre"] for g in result["objetivos"]]
    assert "Activo" in names
    assert "Completado" not in names


def test_list_goals_all_includes_every_status(goal_tools):
    financial_mcp, user_id = goal_tools
    financial_mcp.create_goal(user_id=user_id, name="Activo", target_amount=1000.0)
    result = financial_mcp.list_goals(user_id=user_id, status="all")
    assert len(result["objetivos"]) == 1


# ── update_goal_progress ────────────────────────────────────────────────────────

def test_update_goal_progress_marks_completed_when_reached(goal_tools):
    financial_mcp, user_id = goal_tools
    created = financial_mcp.create_goal(user_id=user_id, name="Meta", target_amount=1000.0, current_amount=200.0)

    result = financial_mcp.update_goal_progress(goal_id=created["id"], new_current_amount=1000.0, user_id=user_id)
    assert result["success"] is True
    assert result["estado"] == "completed"


def test_update_goal_progress_stays_active_when_not_reached(goal_tools):
    financial_mcp, user_id = goal_tools
    created = financial_mcp.create_goal(user_id=user_id, name="Meta", target_amount=1000.0)

    result = financial_mcp.update_goal_progress(goal_id=created["id"], new_current_amount=300.0, user_id=user_id)
    assert result["estado"] == "active"


def test_update_goal_progress_unknown_goal_fails(goal_tools):
    financial_mcp, user_id = goal_tools
    result = financial_mcp.update_goal_progress(goal_id=99999, new_current_amount=100.0, user_id=user_id)
    assert result["success"] is False


def test_update_goal_progress_rejects_negative_amount(goal_tools):
    financial_mcp, user_id = goal_tools
    created = financial_mcp.create_goal(user_id=user_id, name="Meta", target_amount=1000.0)
    result = financial_mcp.update_goal_progress(goal_id=created["id"], new_current_amount=-50.0, user_id=user_id)
    assert result["success"] is False
