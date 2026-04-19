from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from agent.routing.intent_types import IntentType
from agent.modes.confirmation_reply_node import confirmation_reply_node
from agent.services.confirmation_service import ConfirmationResult
from agent.state.schemas import create_initial_state


def _make_state(intent: str = "confirm", message_text: str = "Si") -> dict:
    appointment_id = str(uuid4())
    state = create_initial_state("conv-confirmation-reply", "+34612345678", "Ana")
    state["current_mode"] = "CONFIRMATION_REPLY"
    state["pending_confirmation_appointment_id"] = appointment_id
    state["mode_context"] = {
        "last_intent": intent,
        "pending_confirmation_appointment_id": appointment_id,
    }
    state["messages"] = [
        {"role": "user", "content": message_text, "timestamp": "2026-03-18T10:00:00+01:00"}
    ]
    state["user_message"] = message_text
    return state


@pytest.mark.asyncio
async def test_confirm_intent_calls_confirm_appointment() -> None:
    state = _make_state(intent="confirm", message_text="Si")
    service_result = ConfirmationResult(success=True, response_text="Cita confirmada!")

    with patch(
        "agent.modes.confirmation_reply_node.handle_confirmation_response",
        new=AsyncMock(return_value=service_result),
    ) as mock_service:
        result = await confirmation_reply_node(state)

    assert result["messages"][0]["role"] == "assistant"
    assert result["messages"][0]["content"] == "Cita confirmada!"
    assert result["pending_confirmation_appointment_id"] is None
    assert result["user_message"] is None
    mock_service.assert_awaited_once_with(
        customer_phone="+34612345678",
        intent_type=IntentType.CONFIRM_APPOINTMENT,
        message_text="Si",
    )


@pytest.mark.asyncio
async def test_reject_intent_calls_decline_appointment() -> None:
    state = _make_state(intent="reject", message_text="No")

    with patch(
        "agent.modes.confirmation_reply_node.handle_confirmation_response",
        new=AsyncMock(return_value=ConfirmationResult(success=True, response_text="Ok")),
    ) as mock_service:
        await confirmation_reply_node(state)

    assert mock_service.await_args.kwargs["intent_type"] is IntentType.DECLINE_APPOINTMENT


@pytest.mark.asyncio
async def test_cancel_intent_calls_decline_appointment() -> None:
    state = _make_state(intent="cancel", message_text="Cancelo")

    with patch(
        "agent.modes.confirmation_reply_node.handle_confirmation_response",
        new=AsyncMock(return_value=ConfirmationResult(success=True, response_text="Ok")),
    ) as mock_service:
        await confirmation_reply_node(state)

    assert mock_service.await_args.kwargs["intent_type"] is IntentType.DECLINE_APPOINTMENT


@pytest.mark.asyncio
async def test_service_error_returns_fallback_and_clears_flag() -> None:
    state = _make_state(intent="confirm", message_text="Si")

    with patch(
        "agent.modes.confirmation_reply_node.handle_confirmation_response",
        new=AsyncMock(side_effect=Exception("boom")),
    ):
        result = await confirmation_reply_node(state)

    assert result["messages"][0]["content"] == (
        "Hubo un problema procesando tu respuesta. Por favor, intentá de nuevo o escribí 'ayuda'."
    )
    assert result["pending_confirmation_appointment_id"] is None


@pytest.mark.asyncio
async def test_state_updates_applied_when_present() -> None:
    state = _make_state(intent="confirm", message_text="Si")
    service_result = ConfirmationResult(
        success=True,
        response_text="Listo",
        state_updates={"appointment_confirmed": True},
    )

    with patch(
        "agent.modes.confirmation_reply_node.handle_confirmation_response",
        new=AsyncMock(return_value=service_result),
    ):
        result = await confirmation_reply_node(state)

    assert result["appointment_confirmed"] is True


@pytest.mark.asyncio
async def test_unknown_intent_defaults_to_decline() -> None:
    state = _make_state(intent="ambiguous", message_text="mmm")

    with patch(
        "agent.modes.confirmation_reply_node.handle_confirmation_response",
        new=AsyncMock(return_value=ConfirmationResult(success=True, response_text="Ok")),
    ) as mock_service:
        await confirmation_reply_node(state)

    assert mock_service.await_args.kwargs["intent_type"] is IntentType.DECLINE_APPOINTMENT


@pytest.mark.asyncio
async def test_messages_list_used_and_string_service_response() -> None:
    """message_text is read from messages list (canonical channel). Empty messages → empty string."""
    state = _make_state(intent="confirm", message_text="Si")
    # messages list has the user message (not cleared)
    state["customer_id"] = str(uuid4())

    with patch(
        "agent.modes.confirmation_reply_node.handle_confirmation_response",
        new=AsyncMock(return_value="Confirmada por texto plano"),
    ) as mock_service:
        result = await confirmation_reply_node(state)

    assert result["messages"][0]["content"] == "Confirmada por texto plano"
    # message_text comes from messages list, not user_message field
    assert mock_service.await_args.kwargs["message_text"] == "Si"


@pytest.mark.asyncio
async def test_dict_response_without_text_uses_decline_fallback() -> None:
    state = _make_state(intent="cancel", message_text="Cancelo")

    with patch(
        "agent.modes.confirmation_reply_node.handle_confirmation_response",
        new=AsyncMock(return_value={"state_updates": {"needs_followup": True}}),
    ):
        result = await confirmation_reply_node(state)

    assert result["messages"][0]["content"] == (
        "Entendido, hemos anotado tu respuesta. Si necesitás algo más, avisame."
    )
    assert result["needs_followup"] is True


@pytest.mark.asyncio
async def test_dataclass_without_response_text_uses_confirm_fallback() -> None:
    state = _make_state(intent="confirm", message_text="Si")

    with patch(
        "agent.modes.confirmation_reply_node.handle_confirmation_response",
        new=AsyncMock(return_value=ConfirmationResult(success=True)),
    ):
        result = await confirmation_reply_node(state)

    assert (
        result["messages"][0]["content"] == "¡Perfecto! Tu cita ha sido confirmada. ¡Te esperamos!"
    )
