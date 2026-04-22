"""Tests for agent/nodes/preprocess.py — Task 6.2."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

GREETING_TEXT = "Hola, soy Maite, la asistente virtual de Atrévete. ¿En qué puedo ayudarte hoy?"


@pytest.fixture
def base_state():
    return {
        "conversation_id": "conv-1",
        "customer_phone": "+5491100000000",
        "user_message": "hola",
        "pending_whatsapp_name": "Juan",
        "current_mode": "GENERAL",
        "messages": [],
        "booking": None,
        "customer_id": None,
        "customer_name": None,
    }


def _import_preprocess():
    from agent.nodes.preprocess import preprocess_node

    return preprocess_node


# ---------------------------------------------------------------------------
# Empty / whitespace message → no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_message_returns_end(base_state):
    preprocess_node = _import_preprocess()
    state = {**base_state, "user_message": ""}
    result = await preprocess_node(state)
    assert isinstance(result, Command)
    from langgraph.constants import END

    assert result.goto == END


@pytest.mark.asyncio
async def test_whitespace_message_returns_end(base_state):
    preprocess_node = _import_preprocess()
    state = {**base_state, "user_message": "   \n  "}
    result = await preprocess_node(state)
    assert isinstance(result, Command)
    from langgraph.constants import END

    assert result.goto == END


# ---------------------------------------------------------------------------
# Truncation: user_message > 2000 chars → truncated
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_truncates_long_message(base_state):
    preprocess_node = _import_preprocess()
    long_msg = "a" * 3000
    state = {**base_state, "user_message": long_msg, "messages": [HumanMessage(content="prev")]}

    customer = MagicMock()
    customer.id = uuid.uuid4()
    customer.full_name = "Test User"

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = customer
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("agent.nodes.preprocess.get_async_session", return_value=mock_session):
        result = await preprocess_node(state)

    assert isinstance(result, Command)
    assert result.goto == "router"
    # find the HumanMessage added
    new_messages = result.update.get("messages", [])
    human_msgs = [m for m in new_messages if isinstance(m, HumanMessage)]
    assert len(human_msgs) == 1
    assert len(human_msgs[0].content) == 2000


# ---------------------------------------------------------------------------
# First turn: injects greeting AIMessage BEFORE user HumanMessage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_turn_injects_greeting(base_state):
    preprocess_node = _import_preprocess()
    state = {**base_state, "messages": []}  # first turn

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("agent.nodes.preprocess.get_async_session", return_value=mock_session):
        result = await preprocess_node(state)

    messages = result.update.get("messages", [])
    assert len(messages) == 2
    assert isinstance(messages[0], AIMessage)
    assert "Maite" in messages[0].content
    assert isinstance(messages[1], HumanMessage)
    assert messages[1].content == "hola"


@pytest.mark.asyncio
async def test_non_first_turn_no_greeting(base_state):
    preprocess_node = _import_preprocess()
    state = {
        **base_state,
        "messages": [HumanMessage(content="prev"), AIMessage(content="resp")],
    }

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    with patch("agent.nodes.preprocess.get_async_session", return_value=mock_session):
        result = await preprocess_node(state)

    messages = result.update.get("messages", [])
    # only 1 new message: the HumanMessage
    assert len(messages) == 1
    assert isinstance(messages[0], HumanMessage)


# ---------------------------------------------------------------------------
# Customer lookup: found → populate customer_id + customer_name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_customer_found_populates_fields(base_state):
    preprocess_node = _import_preprocess()
    customer_id = uuid.uuid4()
    customer = MagicMock()
    customer.id = customer_id
    customer.full_name = "María García"

    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = customer
    mock_session.execute = AsyncMock(return_value=mock_result)

    state = {**base_state, "messages": [HumanMessage(content="prev")]}
    with patch("agent.nodes.preprocess.get_async_session", return_value=mock_session):
        result = await preprocess_node(state)

    assert result.update.get("customer_id") == customer_id
    assert result.update.get("customer_name") == "María García"


@pytest.mark.asyncio
async def test_customer_not_found_leaves_none(base_state):
    preprocess_node = _import_preprocess()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    state = {**base_state, "messages": [HumanMessage(content="prev")]}
    with patch("agent.nodes.preprocess.get_async_session", return_value=mock_session):
        result = await preprocess_node(state)

    assert result.update.get("customer_id") is None
    assert result.update.get("customer_name") is None


# ---------------------------------------------------------------------------
# user_message cleared in update
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_user_message_cleared_in_update(base_state):
    preprocess_node = _import_preprocess()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    state = {**base_state, "messages": [HumanMessage(content="prev")]}
    with patch("agent.nodes.preprocess.get_async_session", return_value=mock_session):
        result = await preprocess_node(state)

    assert result.update.get("user_message") is None


# ---------------------------------------------------------------------------
# Routes to "router"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_routes_to_router_on_valid_message(base_state):
    preprocess_node = _import_preprocess()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    state = {**base_state, "messages": [HumanMessage(content="prev")]}
    with patch("agent.nodes.preprocess.get_async_session", return_value=mock_session):
        result = await preprocess_node(state)

    assert result.goto == "router"


# ---------------------------------------------------------------------------
# pending_whatsapp_name preserved
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_whatsapp_name_preserved(base_state):
    preprocess_node = _import_preprocess()
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_session.execute = AsyncMock(return_value=mock_result)

    state = {
        **base_state,
        "messages": [HumanMessage(content="prev")],
        "pending_whatsapp_name": "Luisa",
    }
    with patch("agent.nodes.preprocess.get_async_session", return_value=mock_session):
        result = await preprocess_node(state)

    # pending_whatsapp_name should NOT be touched (not in update or present as-is)
    assert (
        "pending_whatsapp_name" not in result.update
        or result.update["pending_whatsapp_name"] == "Luisa"
    )
