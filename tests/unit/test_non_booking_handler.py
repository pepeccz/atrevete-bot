"""
Tests for NonBookingHandler conversational flow.

This module tests the NonBookingHandler that processes non-booking intents
(GREETING, FAQ, ESCALATE, UNKNOWN) using LLM with safe tools only.

Coverage:
- _build_messages method (FSM context inclusion)
- _execute_tool method (safe tool execution)
- Safe tool binding (3 tools only)
- No booking tools available
- LLM conversational handling
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.fsm.models import BookingState, Intent, IntentType
from agent.routing.non_booking_handler import NonBookingHandler


class TestNonBookingHandlerSafeTools:
    """Test safe tool binding and execution."""

    @pytest.mark.asyncio
    async def test_only_safe_tools_bound(self, non_booking_handler):
        """Verify only 3 safe tools are bound to LLM."""
        # Mock LLM with tool binding
        mock_llm_with_tools = MagicMock()
        non_booking_handler.llm.bind_tools = MagicMock(return_value=mock_llm_with_tools)

        # Mock LLM response (no tool calls)
        mock_response = MagicMock()
        mock_response.content = "Response"
        mock_response.tool_calls = []
        mock_llm_with_tools.ainvoke = AsyncMock(return_value=mock_response)

        intent = Intent(type=IntentType.GREETING, raw_message="Hola")
        await non_booking_handler.handle(intent)

        # Verify bind_tools was called with exactly 3 safe tools
        bind_tools_call = non_booking_handler.llm.bind_tools.call_args
        tools_bound = bind_tools_call[0][0]  # First positional argument
        assert len(tools_bound) == 3, f"Expected 3 safe tools, got {len(tools_bound)}"

        # Verify tool names are safe (no booking tools)
        tool_names = [tool.name for tool in tools_bound]
        expected_safe_tools = {"query_info", "search_services", "escalate_to_human"}
        actual_tool_names = set(tool_names)
        assert actual_tool_names == expected_safe_tools, (
            f"Expected safe tools {expected_safe_tools}, got {actual_tool_names}"
        )

    @pytest.mark.asyncio
    async def test_no_booking_tools_available(self, non_booking_handler):
        """Verify booking tools (book, check_availability) are NOT available."""
        mock_llm_with_tools = MagicMock()
        non_booking_handler.llm.bind_tools = MagicMock(return_value=mock_llm_with_tools)

        mock_response = MagicMock()
        mock_response.content = "Response"
        mock_response.tool_calls = []
        mock_llm_with_tools.ainvoke = AsyncMock(return_value=mock_response)

        intent = Intent(type=IntentType.FAQ, raw_message="Quiero info")
        await non_booking_handler.handle(intent)

        # Get bound tools
        bind_tools_call = non_booking_handler.llm.bind_tools.call_args
        tools_bound = bind_tools_call[0][0]
        tool_names = [tool.name for tool in tools_bound]

        # Verify no booking tools
        forbidden_tools = {"book", "check_availability", "find_next_available"}
        assert not forbidden_tools.intersection(set(tool_names)), (
            f"Booking tools {forbidden_tools.intersection(set(tool_names))} should not be available"
        )

    @pytest.mark.asyncio
    async def test_execute_safe_tool_query_info(self, non_booking_handler):
        """Verify safe tool execution for query_info."""
        tool_call = {
            "name": "query_info",
            "args": {"info_type": "services", "filters": {}},
            "id": "call_123"
        }

        with patch("agent.routing.non_booking_handler.query_info") as mock_tool:
            mock_tool.ainvoke = AsyncMock(return_value={"results": ["Service 1", "Service 2"]})

            result = await non_booking_handler._execute_tool(tool_call)

            # Verify tool was called
            mock_tool.ainvoke.assert_called_once_with(
                {"info_type": "services", "filters": {}}
            )

            # Verify result is JSON string
            result_dict = json.loads(result)
            assert result_dict["results"] == ["Service 1", "Service 2"]

    @pytest.mark.asyncio
    async def test_execute_safe_tool_escalate_to_human(self, non_booking_handler):
        """Verify safe tool execution for escalate_to_human."""
        tool_call = {
            "name": "escalate_to_human",
            "args": {"reason": "Customer needs complex help"},
            "id": "call_456"
        }

        with patch("agent.routing.non_booking_handler.escalate_to_human") as mock_tool:
            mock_tool.ainvoke = AsyncMock(return_value={"escalated": True})

            result = await non_booking_handler._execute_tool(tool_call)

            mock_tool.ainvoke.assert_called_once_with(
                {"reason": "Customer needs complex help"}
            )

            result_dict = json.loads(result)
            assert result_dict["escalated"] is True

    @pytest.mark.asyncio
    async def test_execute_tool_not_found(self, non_booking_handler):
        """Verify unknown tool returns error."""
        tool_call = {
            "name": "unknown_tool",
            "args": {},
            "id": "call_789"
        }

        result = await non_booking_handler._execute_tool(tool_call)

        result_dict = json.loads(result)
        assert "error" in result_dict
        assert "Tool not found" in result_dict["error"]

    @pytest.mark.asyncio
    async def test_execute_tool_handles_exception(self, non_booking_handler):
        """Verify tool execution exception is handled gracefully."""
        tool_call = {
            "name": "query_info",
            "args": {"info_type": "invalid"},
            "id": "call_999"
        }

        with patch("agent.routing.non_booking_handler.query_info") as mock_tool:
            mock_tool.ainvoke = AsyncMock(side_effect=Exception("Database error"))

            result = await non_booking_handler._execute_tool(tool_call)

            result_dict = json.loads(result)
            assert "error" in result_dict
            assert "Database error" in result_dict["error"]


class TestNonBookingHandlerMessageBuilding:
    """Test _build_messages method."""

    def test_build_messages_includes_system_prompt(self, non_booking_handler):
        """Verify system prompt is included in messages."""
        intent = Intent(type=IntentType.GREETING, raw_message="Hola")

        messages = non_booking_handler._build_messages(intent)

        # First message should be SystemMessage
        assert len(messages) > 0
        assert messages[0].type == "system"
        assert "Maite" in messages[0].content
        assert "asistente virtual" in messages[0].content.lower()

    def test_build_messages_includes_fsm_context_when_booking_active(
        self, non_booking_handler_with_active_booking
    ):
        """Verify FSM context is included when booking is active."""
        handler, fsm = non_booking_handler_with_active_booking

        intent = Intent(type=IntentType.FAQ, raw_message="¿Cuál es el horario?")
        messages = handler._build_messages(intent)

        # System message should contain FSM context
        system_message = messages[0].content
        assert "CONTEXTO DE RESERVA ACTUAL" in system_message
        assert "service_selection" in system_message.lower()

    def test_build_messages_excludes_fsm_context_when_idle(self, non_booking_handler):
        """Verify FSM context is excluded when FSM is IDLE."""
        intent = Intent(type=IntentType.GREETING, raw_message="Hola")
        messages = non_booking_handler._build_messages(intent)

        system_message = messages[0].content
        assert "CONTEXTO DE RESERVA ACTUAL" not in system_message

    def test_build_messages_includes_conversation_history(
        self, non_booking_handler_with_history
    ):
        """Verify recent conversation history is included."""
        handler, _ = non_booking_handler_with_history

        intent = Intent(type=IntentType.FAQ, raw_message="¿Cuánto cuesta?")
        messages = handler._build_messages(intent)

        # Should have system message + history + current message
        assert len(messages) >= 3

        # Check history messages are included
        human_messages = [m for m in messages if m.type == "human"]
        assert len(human_messages) >= 2  # History + current

    def test_build_messages_limits_conversation_history(
        self, non_booking_handler_with_long_history
    ):
        """Verify only last 5 messages are included from history."""
        handler, state = non_booking_handler_with_long_history

        intent = Intent(type=IntentType.FAQ, raw_message="Current message")
        messages = handler._build_messages(intent)

        # Count non-system messages (should be max 5 history + 1 current = 6)
        non_system_messages = [m for m in messages if m.type != "system"]
        assert len(non_system_messages) <= 6, (
            f"Expected max 6 non-system messages, got {len(non_system_messages)}"
        )

    def test_build_messages_adds_current_user_message(self, non_booking_handler):
        """Verify current user message is added at the end."""
        intent = Intent(
            type=IntentType.FAQ,
            raw_message="¿Dónde están ubicados?"
        )

        messages = non_booking_handler._build_messages(intent)

        # Last message should be HumanMessage with current intent
        last_message = messages[-1]
        assert last_message.type == "human"
        assert last_message.content == "¿Dónde están ubicados?"


class TestNonBookingHandlerHandleMethod:
    """Test handle method integration."""

    @pytest.mark.asyncio
    async def test_handle_greeting_without_tool_calls(self, non_booking_handler):
        """Verify greeting handled without tool calls."""
        mock_llm_with_tools = MagicMock()
        non_booking_handler.llm.bind_tools = MagicMock(return_value=mock_llm_with_tools)

        mock_response = MagicMock()
        mock_response.content = "¡Hola! Soy Maite, ¿en qué puedo ayudarte?"
        mock_response.tool_calls = []  # No tool calls needed
        mock_llm_with_tools.ainvoke = AsyncMock(return_value=mock_response)

        intent = Intent(type=IntentType.GREETING, raw_message="Hola")
        response = await non_booking_handler.handle(intent)

        assert response == "¡Hola! Soy Maite, ¿en qué puedo ayudarte?"

    @pytest.mark.asyncio
    async def test_handle_faq_with_tool_call(self, non_booking_handler):
        """Verify FAQ handled with query_info tool call."""
        mock_llm_with_tools = MagicMock()
        non_booking_handler.llm.bind_tools = MagicMock(return_value=mock_llm_with_tools)

        # First LLM call: decides to call query_info
        mock_first_response = MagicMock()
        mock_first_response.tool_calls = [
            {"name": "query_info", "args": {"info_type": "hours"}, "id": "call_1"}
        ]

        # Second LLM call: formats final response with tool results
        mock_second_response = MagicMock()
        mock_second_response.content = "Nuestro horario es de lunes a sábado de 9:00 a 20:00"

        # Setup mock to return different responses on consecutive calls
        mock_llm_with_tools.ainvoke = AsyncMock(
            side_effect=[mock_first_response, mock_second_response]
        )

        with patch("agent.routing.non_booking_handler.query_info") as mock_tool:
            mock_tool.ainvoke = AsyncMock(
                return_value={"hours": "Lunes a Sábado: 9:00 - 20:00"}
            )

            intent = Intent(type=IntentType.FAQ, raw_message="¿Cuál es el horario?")
            response = await non_booking_handler.handle(intent)

            assert "9:00" in response
            assert "20:00" in response


# ==============================================================================
# FIXTURES
# ==============================================================================


@pytest.fixture
def mock_fsm_idle():
    """Mock FSM in IDLE state."""
    fsm = MagicMock()
    fsm.state = BookingState.IDLE
    fsm.collected_data = {}
    return fsm


@pytest.fixture
def mock_fsm_active_booking():
    """Mock FSM in SERVICE_SELECTION state (active booking)."""
    fsm = MagicMock()
    fsm.state = BookingState.SERVICE_SELECTION
    fsm.collected_data = {"customer_id": "123"}
    return fsm


@pytest.fixture
def mock_llm():
    """Mock ChatOpenAI instance."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock()
    llm.bind_tools = MagicMock()
    return llm


@pytest.fixture
def mock_state():
    """Mock ConversationState."""
    return {
        "conversation_id": "test-123",
        "messages": [],
    }


@pytest.fixture
def mock_state_with_history():
    """Mock ConversationState with message history."""
    return {
        "conversation_id": "test-456",
        "messages": [
            {"role": "user", "content": "Hola"},
            {"role": "assistant", "content": "¡Hola! ¿En qué puedo ayudarte?"},
            {"role": "user", "content": "¿Qué servicios ofrecen?"},
            {"role": "assistant", "content": "Ofrecemos cortes, tintes, etc."},
        ],
    }


@pytest.fixture
def mock_state_with_long_history():
    """Mock ConversationState with more than 5 messages."""
    messages = []
    for i in range(10):
        messages.append({"role": "user", "content": f"User message {i}"})
        messages.append({"role": "assistant", "content": f"Assistant response {i}"})

    return {
        "conversation_id": "test-789",
        "messages": messages,
    }


@pytest.fixture
def non_booking_handler(mock_state, mock_llm, mock_fsm_idle):
    """Create NonBookingHandler instance."""
    return NonBookingHandler(mock_state, mock_llm, mock_fsm_idle)


@pytest.fixture
def non_booking_handler_with_active_booking(
    mock_state, mock_llm, mock_fsm_active_booking
):
    """Create NonBookingHandler with active booking FSM."""
    handler = NonBookingHandler(mock_state, mock_llm, mock_fsm_active_booking)
    return handler, mock_fsm_active_booking


@pytest.fixture
def non_booking_handler_with_history(
    mock_state_with_history, mock_llm, mock_fsm_idle
):
    """Create NonBookingHandler with conversation history."""
    handler = NonBookingHandler(mock_state_with_history, mock_llm, mock_fsm_idle)
    return handler, mock_state_with_history


@pytest.fixture
def non_booking_handler_with_long_history(
    mock_state_with_long_history, mock_llm, mock_fsm_idle
):
    """Create NonBookingHandler with long conversation history."""
    handler = NonBookingHandler(mock_state_with_long_history, mock_llm, mock_fsm_idle)
    return handler, mock_state_with_long_history
