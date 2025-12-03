"""
Tests for BookingHandler prescriptive flow.

This module tests the BookingHandler that executes FSM-prescribed actions
for booking intents. The handler executes tools specified by the FSM and
formats responses using Jinja2 templates with optional LLM enhancement.

Coverage:
- Tool execution (_execute_tools method)
- Required vs optional tool handling
- Template rendering with Jinja2
- LLM creative enhancement
- Fallback response generation
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from agent.fsm.models import ActionType, BookingState, FSMAction, Intent, IntentType, ToolCall
from agent.routing.booking_handler import BookingHandler, ResponseFormatter


class TestBookingHandlerToolExecution:
    """Test _execute_tools method."""

    @pytest.mark.asyncio
    async def test_executes_single_tool(self, booking_handler):
        """Verify single tool execution."""
        tool_calls = [
            ToolCall(name="search_services", args={"query": "corte"}, required=True)
        ]

        with patch("agent.routing.booking_handler.search_services") as mock_tool:
            mock_tool.ainvoke = AsyncMock(
                return_value={"services": [{"name": "Corte", "duration_minutes": 30}]}
            )

            results = await booking_handler._execute_tools(tool_calls)

            assert "search_services" in results
            assert results["search_services"]["services"][0]["name"] == "Corte"
            mock_tool.ainvoke.assert_called_once_with({"query": "corte"})

    @pytest.mark.asyncio
    async def test_executes_multiple_tools_in_sequence(self, booking_handler):
        """Verify multiple tools execute in sequence."""
        tool_calls = [
            ToolCall(name="search_services", args={"query": "corte"}, required=True),
            ToolCall(
                name="find_next_available",
                args={"service_names": ["Corte"], "days_ahead": 7},
                required=True
            )
        ]

        with patch("agent.routing.booking_handler.search_services") as mock_search, \
             patch("agent.routing.booking_handler.find_next_available") as mock_find:

            mock_search.ainvoke = AsyncMock(return_value={"services": [{"name": "Corte"}]})
            mock_find.ainvoke = AsyncMock(return_value={"slots": []})

            results = await booking_handler._execute_tools(tool_calls)

            assert len(results) == 2
            assert "search_services" in results
            assert "find_next_available" in results
            mock_search.ainvoke.assert_called_once()
            mock_find.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_handles_optional_tool_failure(self, booking_handler):
        """Verify optional tool failure doesn't stop execution."""
        tool_calls = [
            ToolCall(name="search_services", args={}, required=False),
            ToolCall(name="check_availability", args={}, required=True)
        ]

        with patch("agent.routing.booking_handler.search_services") as mock_search, \
             patch("agent.routing.booking_handler.check_availability") as mock_check:

            # First tool fails (optional)
            mock_search.ainvoke = AsyncMock(side_effect=Exception("Search failed"))
            # Second tool succeeds (required)
            mock_check.ainvoke = AsyncMock(return_value={"available": True})

            results = await booking_handler._execute_tools(tool_calls)

            # Optional tool failure logged but execution continues
            assert "search_services" in results
            assert "error" in results["search_services"]
            assert "Search failed" in results["search_services"]["error"]

            # Required tool executed successfully
            assert "check_availability" in results
            assert results["check_availability"]["available"] is True

    @pytest.mark.asyncio
    async def test_raises_on_required_tool_failure(self, booking_handler):
        """Verify required tool failure raises exception."""
        tool_calls = [
            ToolCall(name="book", args={}, required=True)
        ]

        with patch("agent.routing.booking_handler.book") as mock_book:
            mock_book.ainvoke = AsyncMock(side_effect=Exception("Booking failed"))

            with pytest.raises(Exception, match="Booking failed"):
                await booking_handler._execute_tools(tool_calls)

    @pytest.mark.asyncio
    async def test_handles_tool_not_found_required(self, booking_handler):
        """Verify missing required tool raises error."""
        tool_calls = [
            ToolCall(name="nonexistent_tool", args={}, required=True)
        ]

        with pytest.raises(ValueError, match="Tool not found: nonexistent_tool"):
            await booking_handler._execute_tools(tool_calls)

    @pytest.mark.asyncio
    async def test_handles_tool_not_found_optional(self, booking_handler):
        """Verify missing optional tool logs error but continues."""
        tool_calls = [
            ToolCall(name="nonexistent_tool", args={}, required=False)
        ]

        results = await booking_handler._execute_tools(tool_calls)

        assert "nonexistent_tool" in results
        assert "error" in results["nonexistent_tool"]


class TestResponseFormatterTemplateRendering:
    """Test ResponseFormatter template rendering."""

    @pytest.mark.asyncio
    async def test_renders_jinja2_template_strict_mode(self, response_formatter, mock_llm):
        """Verify strict template rendering (no LLM enhancement)."""
        template = "Services: {% for s in services %}{{ s.name }}, {% endfor %}"
        vars = {"services": [{"name": "Corte"}, {"name": "Tinte"}]}

        result = await response_formatter.format_with_template(
            template_str=template,
            template_vars=vars,
            allow_creativity=False,
            llm=mock_llm,
        )

        assert result == "Services: Corte, Tinte, "
        # Verify LLM was NOT called in strict mode
        mock_llm.ainvoke.assert_not_called()

    @pytest.mark.asyncio
    async def test_enhances_with_llm_creative_mode(self, response_formatter, mock_llm):
        """Verify LLM enhancement in creative mode."""
        template = "Services: Corte, Tinte"
        vars = {}

        # Mock LLM response
        mock_response = MagicMock()
        mock_response.content = "¡Perfecto! 🌸 Estos son nuestros servicios:\n- Corte\n- Tinte"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        result = await response_formatter.format_with_template(
            template_str=template,
            template_vars=vars,
            allow_creativity=True,
            llm=mock_llm,
        )

        # Verify LLM enhanced the response
        assert "🌸" in result
        assert "Corte" in result
        mock_llm.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_template_with_complex_variables(self, response_formatter, mock_llm):
        """Verify template rendering with nested variables."""
        template = """
Servicios seleccionados:
{% for service in services %}
- {{ service.name }} ({{ service.duration_minutes }} min)
{% endfor %}
Total: {{ total_duration }} minutos
"""
        vars = {
            "services": [
                {"name": "Corte", "duration_minutes": 30},
                {"name": "Tinte", "duration_minutes": 90}
            ],
            "total_duration": 120
        }

        result = await response_formatter.format_with_template(
            template_str=template,
            template_vars=vars,
            allow_creativity=False,
            llm=mock_llm,
        )

        assert "Corte (30 min)" in result
        assert "Tinte (90 min)" in result
        assert "Total: 120 minutos" in result

    @pytest.mark.asyncio
    async def test_creative_mode_preserves_data(self, response_formatter, mock_llm):
        """Verify LLM creative mode preserves structured data."""
        template = "Slots: 10:00, 11:00, 12:00"
        vars = {}

        # Mock LLM to return a response that keeps the data
        mock_response = MagicMock()
        mock_response.content = "Tenemos disponibilidad a las 10:00, 11:00 y 12:00"
        mock_llm.ainvoke = AsyncMock(return_value=mock_response)

        result = await response_formatter.format_with_template(
            template_str=template,
            template_vars=vars,
            allow_creativity=True,
            llm=mock_llm,
        )

        # Verify all data is preserved
        assert "10:00" in result
        assert "11:00" in result
        assert "12:00" in result


class TestBookingHandlerIntegration:
    """Test BookingHandler.handle method integration."""

    @pytest.mark.asyncio
    async def test_handle_with_template_response(self, booking_handler_with_fsm):
        """Verify handle() executes tools and formats response."""
        handler, mock_fsm = booking_handler_with_fsm

        # Mock FSM to return FSMAction with tools and template
        action = FSMAction(
            action_type=ActionType.CALL_TOOLS_SEQUENCE,
            tool_calls=[
                ToolCall(name="search_services", args={"query": "corte"}, required=True)
            ],
            response_template="Found: {{ search_services.services|length }} services",
            template_vars={},
            allow_llm_creativity=False
        )
        mock_fsm.get_required_action = MagicMock(return_value=action)

        # Mock tool execution
        with patch("agent.routing.booking_handler.search_services") as mock_tool:
            mock_tool.ainvoke = AsyncMock(
                return_value={"services": [{"name": "Corte"}]}
            )

            intent = Intent(type=IntentType.SELECT_SERVICE, raw_message="Corte")
            response = await handler.handle(intent)

            assert "Found: 1 services" in response

    @pytest.mark.asyncio
    async def test_handle_with_fallback_response(self, booking_handler_with_fsm):
        """Verify handle() generates fallback when no template provided."""
        handler, mock_fsm = booking_handler_with_fsm

        # Mock FSM to return FSMAction without template
        action = FSMAction(
            action_type=ActionType.RESPOND_ONLY,
            tool_calls=[],
            response_template=None,  # No template
            template_vars={},
            allow_llm_creativity=False
        )
        mock_fsm.get_required_action = MagicMock(return_value=action)

        # Mock LLM for fallback generation
        mock_response = MagicMock()
        mock_response.content = "Fallback response"

        with patch.object(handler.llm, "ainvoke", new=AsyncMock(return_value=mock_response)):
            intent = Intent(type=IntentType.START_BOOKING, raw_message="Quiero reservar")
            response = await handler.handle(intent)

            assert response == "Fallback response"


# ==============================================================================
# FIXTURES
# ==============================================================================


@pytest.fixture
def mock_fsm():
    """Mock FSM instance."""
    fsm = MagicMock()
    fsm.state = BookingState.SERVICE_SELECTION
    fsm.collected_data = {}
    return fsm


@pytest.fixture
def mock_llm():
    """Mock ChatOpenAI instance."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock()
    return llm


@pytest.fixture
def mock_state():
    """Mock ConversationState."""
    return {
        "conversation_id": "test-123",
        "messages": [],
        "fsm_state": None,
    }


@pytest.fixture
def booking_handler(mock_fsm, mock_state, mock_llm):
    """Create BookingHandler instance."""
    return BookingHandler(mock_fsm, mock_state, mock_llm)


@pytest.fixture
def booking_handler_with_fsm(mock_fsm, mock_state, mock_llm):
    """Create BookingHandler instance with FSM, returning both."""
    handler = BookingHandler(mock_fsm, mock_state, mock_llm)
    return handler, mock_fsm


@pytest.fixture
def response_formatter():
    """Create ResponseFormatter instance."""
    return ResponseFormatter()
