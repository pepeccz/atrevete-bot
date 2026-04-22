"""Tests for preprocess_node greeting removal — Task 4.1 (booking-prompts-audit-fix).

Spec:
- preprocess_node MUST NOT inject an AIMessage on any turn, including first turn.
- After preprocess, message count = count_before + 1 (only HumanMessage added).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.constants import END


@pytest.fixture
def base_state():
    return {
        "conversation_id": "conv-1",
        "customer_phone": "+5491100000000",
        "user_message": "hola",
        "pending_whatsapp_name": None,
        "current_mode": "GENERAL",
        "messages": [],
        "booking": None,
        "customer_id": None,
        "customer_name": None,
    }


def _no_customer_session():
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)
    return mock_session


@pytest.mark.asyncio
async def test_first_turn_emits_no_ai_message(base_state):
    """On first turn (empty history), preprocess MUST NOT add an AIMessage."""
    from agent.nodes.preprocess import preprocess_node

    state = {**base_state, "messages": []}  # empty history = first turn

    with patch("agent.nodes.preprocess.get_async_session", return_value=_no_customer_session()):
        result = await preprocess_node(state)

    new_messages = result.update.get("messages", [])
    ai_messages = [m for m in new_messages if isinstance(m, AIMessage)]
    assert len(ai_messages) == 0, (
        f"preprocess must not inject greeting AIMessage; got {ai_messages}"
    )


@pytest.mark.asyncio
async def test_first_turn_adds_exactly_one_human_message(base_state):
    """On first turn, preprocess adds exactly one HumanMessage (no AIMessage prepended)."""
    from agent.nodes.preprocess import preprocess_node

    state = {**base_state, "messages": []}

    with patch("agent.nodes.preprocess.get_async_session", return_value=_no_customer_session()):
        result = await preprocess_node(state)

    new_messages = result.update.get("messages", [])
    assert len(new_messages) == 1, (
        f"Expected exactly 1 new message (HumanMessage), got {len(new_messages)}: {new_messages}"
    )
    assert isinstance(new_messages[0], HumanMessage)
    assert new_messages[0].content == "hola"
