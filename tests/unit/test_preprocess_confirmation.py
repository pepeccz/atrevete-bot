from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.graphs.conversation_flow import preprocess_node_v6
from agent.state.schemas import create_initial_state


def _make_state() -> dict:
    state = create_initial_state("conv-preprocess", "+34612345678", "Ana")
    state["user_message"] = "Hola"
    return state


@pytest.mark.asyncio
async def test_preprocess_sets_flag_when_pending_confirmation_exists() -> None:
    state = _make_state()
    state["customer_id"] = str(uuid4())
    state["customer_phone"] = ""
    appointment = MagicMock(id=uuid4())

    with patch(
        "agent.services.confirmation_service.get_pending_confirmations",
        new=AsyncMock(return_value=[appointment]),
    ) as mock_pending:
        result = await preprocess_node_v6(state)

    assert result["pending_confirmation_appointment_id"] == str(appointment.id)
    mock_pending.assert_awaited_once()


@pytest.mark.asyncio
async def test_preprocess_clears_flag_when_no_pending_confirmation() -> None:
    state = _make_state()
    state["customer_id"] = str(uuid4())
    state["customer_phone"] = ""

    with patch(
        "agent.services.confirmation_service.get_pending_confirmations",
        new=AsyncMock(return_value=[]),
    ):
        result = await preprocess_node_v6(state)

    assert result["pending_confirmation_appointment_id"] is None


@pytest.mark.asyncio
async def test_preprocess_skips_hook_when_no_customer_id() -> None:
    state = _make_state()
    state["customer_id"] = None
    state["customer_phone"] = ""

    with patch(
        "agent.services.confirmation_service.get_pending_confirmations",
        new=AsyncMock(),
    ) as mock_pending:
        result = await preprocess_node_v6(state)

    mock_pending.assert_not_awaited()
    assert result["pending_confirmation_appointment_id"] is None


@pytest.mark.asyncio
async def test_preprocess_handles_exception_gracefully() -> None:
    state = _make_state()
    state["customer_id"] = str(uuid4())
    state["customer_phone"] = ""

    with patch(
        "agent.services.confirmation_service.get_pending_confirmations",
        new=AsyncMock(side_effect=Exception("db error")),
    ):
        result = await preprocess_node_v6(state)

    assert result["pending_confirmation_appointment_id"] is None
    assert result["last_node"] == "preprocess"
