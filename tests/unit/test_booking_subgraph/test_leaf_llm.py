"""
Phase 5 — LLM Leaf Nodes: RED tests.

For each of the 9 LLM leaf nodes (ask_service, ask_audience, ask_stylist, ask_slot,
ask_name, ask_notes, show_confirmation, booking_complete, error_recovery):
  - mock llm.ainvoke
  - assert called exactly once
  - assert correct prompt shape (SystemMessage + last messages)
  - assert returns AIMessage appended to messages
  - assert no tool binding (llm used with bind_tools never called)
  - assert booking_context is NOT mutated

await_confirmation: silent no-op — resolved as decision: no LLM call, returns {}.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(bc: dict | None = None, messages: list | None = None) -> dict:
    """Minimal ConversationState-like dict for LLM leaf node tests."""
    return {
        "booking_context": bc or {},
        "messages": messages or [],
        "user_message": "hola",
    }


def _make_llm_mock(response_text: str = "respuesta del bot") -> AsyncMock:
    """Return a mock LLM whose ainvoke returns an AIMessage."""
    mock = AsyncMock()
    mock.ainvoke.return_value = AIMessage(content=response_text)
    return mock


# ---------------------------------------------------------------------------
# ask_service
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_service_calls_llm_once():
    """ask_service must call llm.ainvoke exactly once."""
    from agent.booking.nodes.leaf_llm import ask_service

    mock_llm = _make_llm_mock()
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await ask_service(_state())

    mock_llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_ask_service_returns_ai_message():
    """ask_service must append an AIMessage to messages."""
    from agent.booking.nodes.leaf_llm import ask_service

    mock_llm = _make_llm_mock("¿Qué servicio querés?")
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await ask_service(_state())

    assert "messages" in result
    msgs = result["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], dict) and msgs[0]["role"] == "assistant"
    assert msgs[0]["content"] == "¿Qué servicio querés?"


@pytest.mark.asyncio
async def test_ask_service_prompt_contains_system_message():
    """ask_service must pass a SystemMessage as first element."""
    from agent.booking.nodes.leaf_llm import ask_service

    mock_llm = _make_llm_mock()
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        await ask_service(_state())

    call_args = mock_llm.ainvoke.call_args[0][0]
    assert isinstance(call_args[0], SystemMessage)


@pytest.mark.asyncio
async def test_ask_service_does_not_mutate_booking_context():
    """ask_service must not modify booking_context."""
    from agent.booking.nodes.leaf_llm import ask_service

    bc = {"service": None}
    state = _state(bc=dict(bc))
    mock_llm = _make_llm_mock()
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await ask_service(state)

    assert "booking_context" not in result


# ---------------------------------------------------------------------------
# ask_audience
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_audience_calls_llm_once():
    from agent.booking.nodes.leaf_llm import ask_audience

    mock_llm = _make_llm_mock()
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await ask_audience(_state(bc={"service": "Cortar"}))

    mock_llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_ask_audience_returns_ai_message():
    from agent.booking.nodes.leaf_llm import ask_audience

    mock_llm = _make_llm_mock("¿Para quién es el turno?")
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await ask_audience(_state(bc={"service": "Cortar"}))

    msgs = result["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], dict) and msgs[0]["role"] == "assistant"


@pytest.mark.asyncio
async def test_ask_audience_does_not_mutate_booking_context():
    from agent.booking.nodes.leaf_llm import ask_audience

    mock_llm = _make_llm_mock()
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await ask_audience(_state())

    assert "booking_context" not in result


# ---------------------------------------------------------------------------
# ask_stylist
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_stylist_calls_llm_once():
    from agent.booking.nodes.leaf_llm import ask_stylist

    mock_llm = _make_llm_mock()
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await ask_stylist(_state())

    mock_llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_ask_stylist_returns_ai_message():
    from agent.booking.nodes.leaf_llm import ask_stylist

    mock_llm = _make_llm_mock("¿Con qué estilista querés?")
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await ask_stylist(_state())

    msgs = result["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], dict) and msgs[0]["role"] == "assistant"


# ---------------------------------------------------------------------------
# ask_slot
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_slot_calls_llm_once():
    from agent.booking.nodes.leaf_llm import ask_slot

    mock_llm = _make_llm_mock()
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await ask_slot(_state())

    mock_llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_ask_slot_returns_ai_message():
    from agent.booking.nodes.leaf_llm import ask_slot

    mock_llm = _make_llm_mock("Estos son los horarios disponibles:")
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await ask_slot(_state())

    msgs = result["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], dict) and msgs[0]["role"] == "assistant"


# ---------------------------------------------------------------------------
# ask_name
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_name_calls_llm_once():
    from agent.booking.nodes.leaf_llm import ask_name

    mock_llm = _make_llm_mock()
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await ask_name(_state())

    mock_llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_ask_name_returns_ai_message():
    from agent.booking.nodes.leaf_llm import ask_name

    mock_llm = _make_llm_mock("¿A nombre de quién hago la reserva?")
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await ask_name(_state())

    msgs = result["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], dict) and msgs[0]["role"] == "assistant"


# ---------------------------------------------------------------------------
# ask_notes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ask_notes_calls_llm_once():
    from agent.booking.nodes.leaf_llm import ask_notes

    mock_llm = _make_llm_mock()
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await ask_notes(_state())

    mock_llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_ask_notes_returns_ai_message():
    from agent.booking.nodes.leaf_llm import ask_notes

    mock_llm = _make_llm_mock("¿Alguna indicación especial?")
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await ask_notes(_state())

    msgs = result["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], dict) and msgs[0]["role"] == "assistant"


# ---------------------------------------------------------------------------
# show_confirmation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_show_confirmation_calls_llm_once():
    from agent.booking.nodes.leaf_llm import show_confirmation

    bc = {
        "last_services": ["Cortar Señora"],
        "stylist_name": "Gabi",
        "selected_slot": {"datetime_display": "miércoles 29 a las 10:00"},
        "customer_name": "María",
    }
    mock_llm = _make_llm_mock()
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await show_confirmation(_state(bc=bc))

    mock_llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_show_confirmation_returns_ai_message():
    from agent.booking.nodes.leaf_llm import show_confirmation

    bc = {
        "last_services": ["Cortar Señora"],
        "stylist_name": "Gabi",
        "selected_slot": {"datetime_display": "miércoles 29 a las 10:00"},
        "customer_name": "María",
    }
    mock_llm = _make_llm_mock("Confirmación: Cortar Señora con Gabi...")
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await show_confirmation(_state(bc=bc))

    msgs = result["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], dict) and msgs[0]["role"] == "assistant"


@pytest.mark.asyncio
async def test_show_confirmation_does_not_mutate_booking_context():
    """show_confirmation must never modify booking_context (spec invariant #2)."""
    from agent.booking.nodes.leaf_llm import show_confirmation

    bc = {"last_services": ["Cortar Señora"], "customer_name": "María"}
    mock_llm = _make_llm_mock()
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await show_confirmation(_state(bc=dict(bc)))

    assert "booking_context" not in result


# ---------------------------------------------------------------------------
# booking_complete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_booking_complete_calls_llm_once():
    from agent.booking.nodes.leaf_llm import booking_complete

    bc = {
        "appointment_id": "abc-123",
        "last_services": ["Cortar Señora"],
        "stylist_name": "Gabi",
        "selected_slot": {"datetime_display": "miércoles 29 a las 10:00"},
        "customer_name": "María",
    }
    mock_llm = _make_llm_mock()
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await booking_complete(_state(bc=bc))

    mock_llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_booking_complete_returns_ai_message():
    from agent.booking.nodes.leaf_llm import booking_complete

    bc = {"appointment_id": "abc-123", "last_services": ["Cortar Señora"]}
    mock_llm = _make_llm_mock("¡Tu turno está confirmado!")
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await booking_complete(_state(bc=bc))

    msgs = result["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], dict) and msgs[0]["role"] == "assistant"
    assert msgs[0]["content"] == "¡Tu turno está confirmado!"


@pytest.mark.asyncio
async def test_booking_complete_does_not_make_tool_calls():
    """booking_complete must return AIMessage with no tool_calls."""
    from agent.booking.nodes.leaf_llm import booking_complete

    bc = {"appointment_id": "abc-123"}
    ai_msg = AIMessage(content="confirmado", tool_calls=[])
    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = ai_msg
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await booking_complete(_state(bc=bc))

    msgs = result["messages"]
    assert "tool_calls" not in msgs[0]


# ---------------------------------------------------------------------------
# error_recovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_error_recovery_calls_llm_once():
    from agent.booking.nodes.leaf_llm import error_recovery

    mock_llm = _make_llm_mock()
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await error_recovery(_state())

    mock_llm.ainvoke.assert_called_once()


@pytest.mark.asyncio
async def test_error_recovery_returns_ai_message():
    from agent.booking.nodes.leaf_llm import error_recovery

    mock_llm = _make_llm_mock("Hubo un problema, empecemos de nuevo.")
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await error_recovery(_state())

    msgs = result["messages"]
    assert len(msgs) == 1
    assert isinstance(msgs[0], dict) and msgs[0]["role"] == "assistant"


@pytest.mark.asyncio
async def test_error_recovery_resets_booking_context():
    """error_recovery must clear stale booking_context fields (spec: state fence)."""
    from agent.booking.nodes.leaf_llm import error_recovery

    bc = {"service": "algo", "audience": "señora", "_booking_completed": False}
    mock_llm = _make_llm_mock()
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await error_recovery(_state(bc=dict(bc)))

    # Must return a reset booking_context (empty or minimal clean state)
    assert "booking_context" in result
    assert result["booking_context"] == {}


# ---------------------------------------------------------------------------
# await_confirmation — silent no-op (design decision: wait for next user input)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_await_confirmation_is_silent_no_op():
    """
    await_confirmation is a silent no-op — no LLM call.
    User already saw show_confirmation. This node just waits for next input.
    Decision: resolved as silent no-op (orchestrator instruction).
    """
    from agent.booking.nodes.leaf_llm import await_confirmation

    mock_llm = _make_llm_mock()
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await await_confirmation(_state())

    # No LLM call
    mock_llm.ainvoke.assert_not_called()
    # Returns empty dict (no state changes)
    assert result == {}


# ---------------------------------------------------------------------------
# No tools bound — shared invariant
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# TRIANGULATE — cross-cutting edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_messages_history_passed_to_llm():
    """_last_turns must include prior conversation history in the LLM call."""
    from agent.booking.nodes.leaf_llm import ask_service

    history = [
        HumanMessage(content="quiero reservar"),
        AIMessage(content="¿qué servicio?"),
    ]
    state = _state(messages=history)
    mock_llm = _make_llm_mock()
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        await ask_service(state)

    call_args = mock_llm.ainvoke.call_args[0][0]
    # First is SystemMessage, rest includes history
    assert isinstance(call_args[0], SystemMessage)
    assert len(call_args) == 3  # SystemMessage + 2 history messages


@pytest.mark.asyncio
async def test_error_recovery_with_partial_booking_context():
    """error_recovery with a partially-filled context still resets to {}."""
    from agent.booking.nodes.leaf_llm import error_recovery

    bc = {"service": "Cortar Señora", "stylist_id": "abc", "_booking_completed": False}
    mock_llm = _make_llm_mock("Lo siento, empecemos de nuevo.")
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await error_recovery(_state(bc=dict(bc)))

    # booking_context reset
    assert result["booking_context"] == {}
    # LLM still called once
    mock_llm.ainvoke.assert_called_once()
    # Message still returned
    assert len(result["messages"]) == 1
    assert isinstance(result["messages"][0], dict) and result["messages"][0]["role"] == "assistant"


@pytest.mark.asyncio
async def test_booking_complete_message_content_returned():
    """booking_complete returns the exact LLM response text."""
    from agent.booking.nodes.leaf_llm import booking_complete

    bc = {"appointment_id": "xyz-789"}
    expected_text = "¡Listo! Tu turno #xyz-789 está confirmado."
    mock_llm = _make_llm_mock(expected_text)
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        result = await booking_complete(_state(bc=bc))

    assert result["messages"][0]["content"] == expected_text


@pytest.mark.asyncio
async def test_ask_service_no_bind_tools():
    """
    LLM leaf nodes must NOT use bind_tools. They call llm.ainvoke directly.
    Verify by asserting bind_tools is never called on the module-level llm.
    """
    from agent.booking.nodes.leaf_llm import ask_service

    mock_llm = _make_llm_mock()
    mock_llm.bind_tools = MagicMock(side_effect=AssertionError("bind_tools must not be called"))
    with patch("agent.booking.nodes.leaf_llm.llm", mock_llm):
        # Should not raise AssertionError
        await ask_service(_state())

    mock_llm.bind_tools.assert_not_called()
