"""
Test de _build_system_prompt (graph.py): antepone el bloque de memoria recuperada
al SYSTEM_PROMPT, o lo deja igual si no hay memorias o falla la recuperación.
"""
from unittest.mock import patch

from app.agent.chat_agent import SYSTEM_PROMPT
from app.agent.graph import _build_system_prompt


@patch("app.agent.graph.retrieve_relevant_memories", return_value=["Prefiere ahorrar antes que invertir"])
def test_build_system_prompt_prepends_memory_block(mock_retrieve):
    prompt = _build_system_prompt(user_id=1, message="¿puedo invertir?")
    assert prompt.startswith("Lo que sabes de este usuario:")
    assert "Prefiere ahorrar antes que invertir" in prompt
    assert prompt.endswith(SYSTEM_PROMPT)


@patch("app.agent.graph.retrieve_relevant_memories", return_value=[])
def test_build_system_prompt_unchanged_when_no_memories(mock_retrieve):
    assert _build_system_prompt(user_id=1, message="hola") == SYSTEM_PROMPT


@patch("app.agent.graph.retrieve_relevant_memories", side_effect=RuntimeError("fallo de red"))
def test_build_system_prompt_unchanged_when_retrieval_fails(mock_retrieve):
    assert _build_system_prompt(user_id=1, message="hola") == SYSTEM_PROMPT
