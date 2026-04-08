"""
Tests for preprocess_node_v6 customer memory read path (TASK-4).

Verifies:
- Returning customer → read_customer_memories called → customer_memories set in updates
- New customer → customer_memories = None, read NOT called
- Memory read failure → customer_memories = None, no re-raise
- Store miss (read returns None) → customer_memories = None in updates
- create_graph accepts store param without TypeError
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.graphs.conversation_flow import preprocess_node_v6
from agent.state.schemas import create_initial_state


def _make_state(phone: str = "+34612345678") -> dict:
    state = create_initial_state("conv-preprocess-memory", phone, "Test")
    state["user_message"] = "Hola"
    state["customer_phone"] = phone
    return state


def _make_customer(name: str = "Ana") -> MagicMock:
    customer = MagicMock()
    customer.id = uuid4()
    customer.first_name = name
    return customer


async def test_preprocess_returning_customer_loads_memories() -> None:
    """Returning customer: read_customer_memories called → customer_memories set."""
    state = _make_state()
    customer = _make_customer("Ana")
    prefs = {"visit_count": 3, "preferred_stylist_name": "Pilar"}

    with (
        patch(
            "agent.graphs.conversation_flow.check_customer_exists",
            new=AsyncMock(return_value=(True, customer)),
        ),
        patch(
            "agent.graphs.conversation_flow.read_customer_memories",
            new=AsyncMock(return_value=prefs),
        ) as mock_read,
        patch(
            "agent.services.confirmation_service.get_pending_confirmations",
            new=AsyncMock(return_value=[]),
        ),
    ):
        result = await preprocess_node_v6(state)

    assert result["customer_memories"] == prefs
    mock_read.assert_awaited_once_with(state["customer_phone"])


async def test_preprocess_new_customer_memories_none() -> None:
    """New customer: customer_memories = None, read_customer_memories NOT called."""
    state = _make_state()

    with (
        patch(
            "agent.graphs.conversation_flow.check_customer_exists",
            new=AsyncMock(return_value=(False, None)),
        ),
        patch(
            "agent.graphs.conversation_flow.read_customer_memories",
            new=AsyncMock(return_value={"visit_count": 1}),
        ) as mock_read,
    ):
        result = await preprocess_node_v6(state)

    assert result["customer_memories"] is None
    mock_read.assert_not_awaited()


async def test_preprocess_read_failure_memories_none() -> None:
    """read_customer_memories raises → customer_memories = None, no re-raise."""
    state = _make_state()
    customer = _make_customer("Ana")

    with (
        patch(
            "agent.graphs.conversation_flow.check_customer_exists",
            new=AsyncMock(return_value=(True, customer)),
        ),
        patch(
            "agent.graphs.conversation_flow.read_customer_memories",
            new=AsyncMock(side_effect=ConnectionError("Redis down")),
        ),
        patch(
            "agent.services.confirmation_service.get_pending_confirmations",
            new=AsyncMock(return_value=[]),
        ),
    ):
        result = await preprocess_node_v6(state)

    # Node must return normally — no exception propagated
    assert result["customer_memories"] is None
    assert result["last_node"] == "preprocess"


async def test_preprocess_returning_customer_store_miss() -> None:
    """read_customer_memories returns None (Store+PG miss) → customer_memories = None."""
    state = _make_state()
    customer = _make_customer("Ana")

    with (
        patch(
            "agent.graphs.conversation_flow.check_customer_exists",
            new=AsyncMock(return_value=(True, customer)),
        ),
        patch(
            "agent.graphs.conversation_flow.read_customer_memories",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "agent.services.confirmation_service.get_pending_confirmations",
            new=AsyncMock(return_value=[]),
        ),
    ):
        result = await preprocess_node_v6(state)

    assert result["customer_memories"] is None


def test_create_graph_accepts_store_param() -> None:
    """create_graph(store=mock_store) should not raise TypeError."""
    from agent.graphs.conversation_flow import create_graph
    from unittest.mock import MagicMock

    mock_store = MagicMock()
    # compile() with a non-None store might raise if store API is wrong,
    # but the function signature must accept the param without TypeError
    try:
        graph = create_graph(store=mock_store)
    except TypeError as e:
        pytest.fail(f"create_graph raised TypeError with store param: {e}")
    except Exception:
        # Other errors (e.g. graph compilation details) are acceptable
        pass
