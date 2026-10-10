"""
Tests de GET /chat/history y GET /chat/history/{day}: agrupan los turnos de
`Conversation` por día natural (no hay id de sesión/hilo en el modelo) y devuelven
la transcripción completa de un día concreto.
"""
import os
import tempfile
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.database import Base, get_db
from app.core.dependencies import get_current_user
from app.main import app
from app.models.financial import Conversation, User


@pytest.fixture()
def env():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db = TestSessionLocal()
    user = User(name="Test", email="test@test.com", password_hash="x", created_at=datetime.now())
    db.add(user)
    db.commit()
    user_id = user.id
    db.close()

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_current_user] = lambda: user_id
    client = TestClient(app)

    yield client, TestSessionLocal, user_id

    app.dependency_overrides.clear()
    engine.dispose()
    os.remove(path)


def _add_message(Session, user_id, role, content, when):
    db = Session()
    db.add(Conversation(user_id=user_id, role=role, content=content, created_at=when))
    db.commit()
    db.close()


def test_list_history_groups_by_day_newest_first(env):
    client, Session, user_id = env
    today = datetime.now()
    yesterday = today - timedelta(days=1)

    _add_message(Session, user_id, "user", "hola ayer", yesterday)
    _add_message(Session, user_id, "assistant", "respuesta ayer", yesterday)
    _add_message(Session, user_id, "user", "hola hoy", today)

    resp = client.get("/chat/history")
    assert resp.status_code == 200
    days = resp.json()
    assert [d["date"] for d in days] == [today.date().isoformat(), yesterday.date().isoformat()]
    assert days[0]["message_count"] == 1
    assert days[1]["message_count"] == 2
    assert days[1]["preview"] == "hola ayer"


def test_list_history_empty_when_no_conversations(env):
    client, _, _ = env
    resp = client.get("/chat/history")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_history_day_returns_ordered_transcript(env):
    client, Session, user_id = env
    day = datetime(2026, 1, 5, 10, 0, 0)
    _add_message(Session, user_id, "user", "primero", day)
    _add_message(Session, user_id, "assistant", "segundo", day + timedelta(minutes=1))

    resp = client.get("/chat/history/2026-01-05")
    assert resp.status_code == 200
    messages = resp.json()
    assert [m["content"] for m in messages] == ["primero", "segundo"]
    assert [m["role"] for m in messages] == ["user", "assistant"]


def test_get_history_day_only_returns_that_users_messages(env):
    client, Session, user_id = env
    other_db = Session()
    other = User(name="Other", email="other@test.com", password_hash="x", created_at=datetime.now())
    other_db.add(other)
    other_db.commit()
    other_id = other.id
    other_db.close()

    day = datetime(2026, 2, 1, 9, 0, 0)
    _add_message(Session, user_id, "user", "mío", day)
    _add_message(Session, other_id, "user", "de otro usuario", day)

    resp = client.get("/chat/history/2026-02-01")
    assert resp.status_code == 200
    assert [m["content"] for m in resp.json()] == ["mío"]


def test_get_history_day_rejects_invalid_date_format(env):
    client, _, _ = env
    resp = client.get("/chat/history/not-a-date")
    assert resp.status_code == 400
