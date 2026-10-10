"""
Tests de memory_agent.py: similitud coseno, parseo tolerante de hechos extraídos
por el LLM, y recuperación/extracción con litellm siempre mockeado (sin red real).
"""
from unittest.mock import MagicMock, patch

from app.agent.memory_agent import (
    _cosine_similarity,
    _extract_facts,
    extract_and_store_memories,
    retrieve_relevant_memories,
)


# ── _cosine_similarity ───────────────────────────────────────────────────────

def test_cosine_similarity_identical_vectors_is_one():
    assert _cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]) == 1.0


def test_cosine_similarity_orthogonal_vectors_is_zero():
    assert _cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_cosine_similarity_zero_vector_does_not_divide_by_zero():
    assert _cosine_similarity([0.0, 0.0], [1.0, 2.0]) == 0.0


# ── _extract_facts: tolerancia a JSON parcialmente inválido ─────────────────

def _mock_completion_response(content: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=content))]
    return response


@patch("app.agent.memory_agent.litellm.completion")
@patch("app.agent.memory_agent._is_claude", return_value=True)
@patch("app.agent.memory_agent._build_model", return_value="anthropic/claude-haiku-4-5")
def test_extract_facts_valid_json_returns_strings(mock_build_model, mock_is_claude, mock_completion):
    mock_completion.return_value = _mock_completion_response(
        '{"facts": ["Prefiere ahorrar antes que invertir", "Tiene aversión al riesgo"]}'
    )
    assert _extract_facts("user: prefiero ahorrar") == [
        "Prefiere ahorrar antes que invertir",
        "Tiene aversión al riesgo",
    ]


@patch("app.agent.memory_agent.litellm.completion")
@patch("app.agent.memory_agent._is_claude", return_value=True)
@patch("app.agent.memory_agent._build_model", return_value="anthropic/claude-haiku-4-5")
def test_extract_facts_malformed_json_returns_empty(mock_build_model, mock_is_claude, mock_completion):
    mock_completion.return_value = _mock_completion_response("esto no es json")
    assert _extract_facts("user: hola") == []


@patch("app.agent.memory_agent.litellm.completion")
@patch("app.agent.memory_agent._is_claude", return_value=True)
@patch("app.agent.memory_agent._build_model", return_value="anthropic/claude-haiku-4-5")
def test_extract_facts_filters_non_string_entries(mock_build_model, mock_is_claude, mock_completion):
    mock_completion.return_value = _mock_completion_response(
        '{"facts": ["Hecho válido", 123, null, "  "]}'
    )
    assert _extract_facts("user: hola") == ["Hecho válido"]


# ── retrieve_relevant_memories ───────────────────────────────────────────────

def _memory_row(chunk_text: str, embedding: list[float]):
    row = MagicMock()
    row.chunk_text = chunk_text
    row.embedding = '[' + ','.join(str(x) for x in embedding) + ']'
    return row


@patch("app.agent.memory_agent.SessionLocal")
@patch("app.agent.memory_agent._embed")
def test_retrieve_relevant_memories_orders_by_similarity(mock_embed, mock_session_local):
    mock_embed.return_value = [1.0, 0.0]
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.all.return_value = [
        _memory_row("poco relacionado", [0.0, 1.0]),
        _memory_row("muy relacionado", [1.0, 0.0]),
        _memory_row("algo relacionado", [0.7, 0.7]),
    ]
    mock_session_local.return_value = mock_db

    result = retrieve_relevant_memories(user_id=1, query="algo", top_k=2)

    assert result == ["muy relacionado", "algo relacionado"]


@patch("app.agent.memory_agent._embed", side_effect=RuntimeError("red caída"))
def test_retrieve_relevant_memories_returns_empty_on_embed_failure(mock_embed):
    assert retrieve_relevant_memories(user_id=1, query="algo") == []


# ── extract_and_store_memories ───────────────────────────────────────────────

def _conversation_row(role: str, content: str):
    row = MagicMock()
    row.role = role
    row.content = content
    return row


@patch("app.agent.memory_agent._embed", return_value=[0.1, 0.2])
@patch("app.agent.memory_agent._extract_facts", return_value=["Prefiere ahorrar antes que invertir"])
@patch("app.agent.memory_agent.SessionLocal")
def test_extract_and_store_memories_adds_one_row_per_fact(mock_session_local, mock_extract, mock_embed):
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = [
        _conversation_row("user", "prefiero ahorrar antes que invertir"),
    ]
    mock_session_local.return_value = mock_db

    facts = extract_and_store_memories(user_id=1)

    assert facts == ["Prefiere ahorrar antes que invertir"]
    assert mock_db.add.call_count == 1
    mock_db.commit.assert_called_once()


@patch("app.agent.memory_agent._extract_facts")
@patch("app.agent.memory_agent.SessionLocal")
def test_extract_and_store_memories_skips_llm_when_no_conversations(mock_session_local, mock_extract):
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    mock_session_local.return_value = mock_db

    facts = extract_and_store_memories(user_id=1)

    assert facts == []
    mock_extract.assert_not_called()
