"""
Tests de la pieza más frágil del dashboard proactivo: el parseo/validación del JSON
que devuelve el LLM. No se testea lógica financiera existente (fuera de alcance) ni
se hacen llamadas reales a litellm — se mockea siempre.
"""
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.agent.dashboard_agent import _parse_cards, generate_dashboard_cards
from app.schemas.financial import AlertCardIn


# ── AlertCardIn: validación de esquema ──────────────────────────────────────

def test_alert_card_rejects_invalid_severity():
    with pytest.raises(ValidationError):
        AlertCardIn(type="positive", title="t", body="b", severity="urgentisimo")


def test_alert_card_rejects_invalid_chart_type():
    with pytest.raises(ValidationError):
        AlertCardIn(type="positive", title="t", body="b", chart_type="scatter")


def test_alert_card_rejects_invalid_type():
    with pytest.raises(ValidationError):
        AlertCardIn(type="not_a_real_type", title="t", body="b")


def test_alert_card_accepts_minimal_valid_card():
    card = AlertCardIn(type="weekly_summary", title="Resumen", body="Todo en orden esta semana.")
    assert card.severity == "info"
    assert card.card_type == "text"


# ── _parse_cards: tolerancia a JSON parcialmente inválido ───────────────────

def test_parse_cards_malformed_json_returns_empty():
    assert _parse_cards("esto no es json") == []


def test_parse_cards_keeps_valid_discards_invalid():
    raw = """{"cards": [
        {"type": "positive", "title": "Bien", "body": "Vas ahorrando más de lo esperado."},
        {"type": "not_valid_type", "title": "Mal", "body": "x"},
        {"type": "budget_warning", "title": "Ojo", "body": "y", "severity": "not_a_severity"}
    ]}"""
    cards = _parse_cards(raw)
    assert len(cards) == 1
    assert cards[0].title == "Bien"


def test_parse_cards_accepts_bare_array():
    raw = '[{"type": "positive", "title": "Bien", "body": "b"}]'
    cards = _parse_cards(raw)
    assert len(cards) == 1


def test_parse_cards_strips_markdown_code_fences():
    raw = '```json\n{"cards": [{"type": "positive", "title": "Bien", "body": "b"}]}\n```'
    cards = _parse_cards(raw)
    assert len(cards) == 1


def test_parse_cards_drops_duplicate_titles_in_same_batch():
    raw = """{"cards": [
        {"type": "positive", "title": "Cartera en verde", "body": "Ha subido un 6%."},
        {"type": "positive", "title": "cartera en verde", "body": "Otra variante del mismo texto."},
        {"type": "budget_warning", "title": "Gasto alto", "body": "y"}
    ]}"""
    cards = _parse_cards(raw)
    assert len(cards) == 2
    assert [c.title for c in cards] == ["Cartera en verde", "Gasto alto"]


# ── generate_dashboard_cards: litellm mockeado, sin red ─────────────────────

def _mock_litellm_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return response


@patch("app.agent.dashboard_agent.SessionLocal")
@patch("app.agent.dashboard_agent._gather_context", return_value={"resumen_financiero": {}})
@patch("app.agent.dashboard_agent.litellm.completion")
@patch("app.agent.dashboard_agent._is_claude", return_value=True)
@patch("app.agent.dashboard_agent._build_model", return_value="anthropic/claude-haiku-4-5")
def test_generate_dashboard_cards_persists_only_valid_cards(
    mock_build_model, mock_is_claude, mock_completion, mock_gather, mock_session_local
):
    mock_completion.return_value = _mock_litellm_response(
        '{"cards": ['
        '{"type": "positive", "title": "Bien", "body": "b"},'
        '{"type": "invalid", "title": "Mal", "body": "x"}'
        "]}"
    )
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    cards = generate_dashboard_cards(user_id=1)

    assert len(cards) == 1
    assert mock_db.add.call_count == 1
    mock_db.commit.assert_called_once()
    mock_db.close.assert_called_once()


@patch("app.agent.dashboard_agent.SessionLocal")
@patch("app.agent.dashboard_agent._gather_context", return_value={"resumen_financiero": {}})
@patch("app.agent.dashboard_agent.litellm.completion")
@patch("app.agent.dashboard_agent._is_claude", return_value=True)
@patch("app.agent.dashboard_agent._build_model", return_value="anthropic/claude-haiku-4-5")
def test_generate_dashboard_cards_deletes_previous_batch_before_inserting(
    mock_build_model, mock_is_claude, mock_completion, mock_gather, mock_session_local
):
    """Cada regeneración sustituye las tarjetas anteriores del usuario — si no se
    borraran, un refresh repetido (p.ej. el automático al entrar) las iría acumulando
    y una misma tarjeta podría acabar mostrada varias veces."""
    mock_completion.return_value = _mock_litellm_response(
        '{"cards": [{"type": "positive", "title": "Bien", "body": "b"}]}'
    )
    mock_db = MagicMock()
    mock_session_local.return_value = mock_db

    generate_dashboard_cards(user_id=1)

    mock_db.query.assert_called_once()
    delete_call = mock_db.query.return_value.filter.return_value.delete
    delete_call.assert_called_once()
