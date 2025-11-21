"""
Integration tests for FSM + Tools validation.

Tests Story 5-4 acceptance criteria:
- AC #1: Tools only execute if FSM state permits
- AC #2: FSM rejects book() in wrong states with redirect
- AC #3: Tools return FSM-compatible structured data
- AC #5: Errors don't corrupt FSM state
- AC #6: Logging shows FSM context
- AC #7: Availability tools only in specific states
- AC #8: Integration tests with coverage >85%
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.fsm import BookingFSM, BookingState
from agent.fsm.tool_validation import (
    ToolValidationResult,
    log_tool_execution,
    validate_tool_call,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def mock_state() -> dict:
    """Create a mock conversation state."""
    return {
        "conversation_id": "test-conv-123",
        "customer_id": "550e8400-e29b-41d4-a716-446655440000",
        "customer_phone": "+34666123456",
        "messages": [
            {"role": "user", "content": "Quiero reservar un corte", "timestamp": "2025-11-21T10:00:00+01:00"},
        ],
    }


@pytest.fixture
def fsm_idle() -> BookingFSM:
    """FSM in IDLE state."""
    fsm = BookingFSM("test-conv-123")
    return fsm


@pytest.fixture
def fsm_confirmation_complete() -> BookingFSM:
    """FSM in CONFIRMATION with complete data."""
    fsm = BookingFSM("test-conv-123")
    fsm._state = BookingState.CONFIRMATION
    fsm._collected_data = {
        "services": ["Corte de Caballero"],
        "stylist_id": "550e8400-e29b-41d4-a716-446655440001",
        "slot": {"start_time": "2025-11-28T10:00:00+01:00", "duration_minutes": 30},
        "first_name": "Juan",
    }
    return fsm


# ============================================================================
# Test AC #1: Tools only execute if FSM state permits
# ============================================================================


class TestToolStatePermissionIntegration:
    """Integration tests for tool state permissions."""

    def test_search_services_allowed_in_idle_via_validation(self, fsm_idle: BookingFSM):
        """search_services should pass validation in IDLE state."""
        result = validate_tool_call("search_services", fsm_idle)
        assert result.allowed is True

    def test_book_blocked_in_idle_via_validation(self, fsm_idle: BookingFSM):
        """book() should fail validation in IDLE state."""
        result = validate_tool_call("book", fsm_idle)
        assert result.allowed is False
        assert result.error_code == "TOOL_STATE_NOT_ALLOWED"

    @pytest.mark.asyncio
    async def test_execute_tool_call_with_fsm_validation_blocked(
        self, mock_state: dict, fsm_idle: BookingFSM
    ):
        """execute_tool_call should return error when FSM blocks tool."""
        from agent.nodes.conversational_agent import execute_tool_call

        tool_call = {
            "name": "book",
            "args": {
                "customer_id": "550e8400-e29b-41d4-a716-446655440000",
                "first_name": "Juan",
                "services": ["Corte de Caballero"],
                "stylist_id": "550e8400-e29b-41d4-a716-446655440001",
                "start_time": "2025-11-28T10:00:00+01:00",
            },
            "id": "call_123",
        }

        result_str, state_updates = await execute_tool_call(tool_call, mock_state, fsm_idle)

        result = json.loads(result_str)
        assert result["error"] == "TOOL_STATE_NOT_ALLOWED"
        assert "book" in result["message"]
        assert result["fsm_state"] == "idle"
        assert result["redirect"] is not None


# ============================================================================
# Test AC #2: FSM rejects book() in wrong states with redirect
# ============================================================================


class TestBookToolRejection:
    """Test book() rejection in wrong states."""

    def test_book_rejected_with_redirect_in_service_selection(self):
        """book() should be rejected with helpful redirect in SERVICE_SELECTION."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SERVICE_SELECTION

        result = validate_tool_call("book", fsm)

        assert result.allowed is False
        assert result.redirect_message is not None
        # Should guide user to select services first
        assert "servicio" in result.redirect_message.lower() or "seleccionar" in result.redirect_message.lower()

    def test_book_rejected_with_redirect_in_slot_selection(self):
        """book() should be rejected with helpful redirect in SLOT_SELECTION."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SLOT_SELECTION
        fsm._collected_data = {"services": ["Corte"], "stylist_id": "uuid"}

        result = validate_tool_call("book", fsm)

        assert result.allowed is False
        assert result.redirect_message is not None
        # Should guide user to select time slot
        assert "horario" in result.redirect_message.lower()

    def test_book_rejected_with_redirect_in_customer_data(self):
        """book() should be rejected with helpful redirect in CUSTOMER_DATA."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.CUSTOMER_DATA
        fsm._collected_data = {
            "services": ["Corte"],
            "stylist_id": "uuid",
            "slot": {"start_time": "2025-11-28T10:00:00+01:00"},
        }

        result = validate_tool_call("book", fsm)

        assert result.allowed is False
        assert result.redirect_message is not None
        # Should guide user to provide name
        assert "nombre" in result.redirect_message.lower()


# ============================================================================
# Test AC #3: Tools return FSM-compatible structured data
# ============================================================================


class TestToolReturnStructure:
    """Test that tools return FSM-compatible data structures."""

    @pytest.mark.asyncio
    async def test_search_services_returns_structured_data(self):
        """search_services should return structured data with services list."""
        # Mock the database session
        from unittest.mock import MagicMock

        mock_service = MagicMock()
        mock_service.name = "Corte de Caballero"
        mock_service.duration_minutes = 30
        mock_service.category.value = "HAIRDRESSING"
        mock_service.is_active = True

        with patch("agent.tools.search_services.get_async_session") as mock_session:
            # Setup mock
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [mock_service]

            mock_session_cm = AsyncMock()
            mock_session_cm.__aenter__ = AsyncMock(return_value=MagicMock())
            mock_session_cm.__aenter__.return_value.execute = AsyncMock(return_value=mock_result)
            mock_session.return_value = mock_session_cm

            from agent.tools.search_services import search_services

            result = await search_services.ainvoke({"query": "corte"})

            # Should have structured format
            assert "services" in result
            assert "count" in result
            assert "query" in result


# ============================================================================
# Test AC #5: Errors don't corrupt FSM state
# ============================================================================


class TestFSMErrorRecovery:
    """Test that errors don't corrupt FSM state."""

    @pytest.mark.asyncio
    async def test_tool_error_preserves_fsm_state(self, fsm_confirmation_complete: BookingFSM):
        """Tool execution error should not change FSM state."""
        original_state = fsm_confirmation_complete.state
        original_data = fsm_confirmation_complete.collected_data.copy()

        # Simulate a tool error by trying to validate an unknown tool
        result = validate_tool_call("nonexistent_tool", fsm_confirmation_complete)

        # FSM state should be unchanged
        assert fsm_confirmation_complete.state == original_state
        assert fsm_confirmation_complete.collected_data == original_data

    @pytest.mark.asyncio
    async def test_rejected_tool_preserves_fsm_state(self, fsm_idle: BookingFSM):
        """Rejected tool call should not change FSM state."""
        original_state = fsm_idle.state
        original_data = fsm_idle.collected_data.copy()

        # Try to call book() in IDLE (will be rejected)
        result = validate_tool_call("book", fsm_idle)
        assert result.allowed is False

        # FSM state should be unchanged
        assert fsm_idle.state == original_state
        assert fsm_idle.collected_data == original_data


# ============================================================================
# Test AC #6: Logging shows FSM context
# ============================================================================


class TestFSMLogging:
    """Test FSM context in logging."""

    def test_log_tool_execution_success(self, fsm_idle: BookingFSM, caplog):
        """log_tool_execution should log with FSM context on success."""
        import logging

        with caplog.at_level(logging.INFO):
            log_tool_execution(
                tool_name="search_services",
                fsm=fsm_idle,
                result={"services": [], "count": 0},
                success=True,
            )

        # Check log contains FSM info
        assert any("search_services" in record.message for record in caplog.records)
        assert any("idle" in record.message.lower() for record in caplog.records)

    def test_log_tool_execution_failure(self, fsm_idle: BookingFSM, caplog):
        """log_tool_execution should log with FSM context on failure."""
        import logging

        with caplog.at_level(logging.WARNING):
            log_tool_execution(
                tool_name="book",
                fsm=fsm_idle,
                result={},
                success=False,
                error="TOOL_STATE_NOT_ALLOWED",
            )

        # Check log contains error info
        assert any("book" in record.message for record in caplog.records)


# ============================================================================
# Test AC #7: Availability tools only in specific states
# ============================================================================


class TestAvailabilityToolsStateRestriction:
    """Test availability tools are restricted to specific states."""

    @pytest.mark.parametrize(
        "tool_name", ["check_availability", "find_next_available"]
    )
    def test_availability_tools_blocked_in_idle(self, tool_name: str, fsm_idle: BookingFSM):
        """Availability tools should be blocked in IDLE state."""
        result = validate_tool_call(tool_name, fsm_idle)
        assert result.allowed is False
        assert result.error_code == "TOOL_STATE_NOT_ALLOWED"

    @pytest.mark.parametrize(
        "tool_name", ["check_availability", "find_next_available"]
    )
    def test_availability_tools_allowed_in_stylist_selection(self, tool_name: str):
        """Availability tools should be allowed in STYLIST_SELECTION with services."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.STYLIST_SELECTION
        fsm._collected_data = {"services": ["Corte de Caballero"]}

        result = validate_tool_call(tool_name, fsm)
        assert result.allowed is True

    @pytest.mark.parametrize(
        "tool_name", ["check_availability", "find_next_available"]
    )
    def test_availability_tools_blocked_without_services(self, tool_name: str):
        """Availability tools should be blocked in STYLIST_SELECTION without services."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.STYLIST_SELECTION
        fsm._collected_data = {}  # No services

        result = validate_tool_call(tool_name, fsm)
        assert result.allowed is False
        assert result.error_code == "MISSING_REQUIRED_DATA"
        assert "services" in result.error_message


# ============================================================================
# Test Happy Path: Full Booking Flow
# ============================================================================


class TestFullBookingFlowValidation:
    """Test validation through full booking flow."""

    def test_tool_permissions_through_booking_states(self):
        """Test that correct tools are allowed at each booking state."""
        fsm = BookingFSM("test-flow")

        # IDLE: search_services allowed, book blocked
        assert validate_tool_call("search_services", fsm).allowed is True
        assert validate_tool_call("query_info", fsm).allowed is True
        assert validate_tool_call("book", fsm).allowed is False
        assert validate_tool_call("check_availability", fsm).allowed is False

        # SERVICE_SELECTION
        fsm._state = BookingState.SERVICE_SELECTION
        assert validate_tool_call("search_services", fsm).allowed is True
        assert validate_tool_call("book", fsm).allowed is False

        # STYLIST_SELECTION (with services)
        fsm._state = BookingState.STYLIST_SELECTION
        fsm._collected_data = {"services": ["Corte"]}
        assert validate_tool_call("check_availability", fsm).allowed is True
        assert validate_tool_call("find_next_available", fsm).allowed is True
        assert validate_tool_call("book", fsm).allowed is False

        # SLOT_SELECTION
        fsm._state = BookingState.SLOT_SELECTION
        fsm._collected_data["stylist_id"] = "uuid"
        assert validate_tool_call("check_availability", fsm).allowed is True
        assert validate_tool_call("book", fsm).allowed is False

        # CUSTOMER_DATA
        fsm._state = BookingState.CUSTOMER_DATA
        fsm._collected_data["slot"] = {"start_time": "2025-11-28T10:00:00+01:00"}
        assert validate_tool_call("manage_customer", fsm).allowed is True
        assert validate_tool_call("book", fsm).allowed is False

        # CONFIRMATION (with complete data)
        fsm._state = BookingState.CONFIRMATION
        fsm._collected_data["first_name"] = "Juan"
        assert validate_tool_call("book", fsm).allowed is True
        assert validate_tool_call("query_info", fsm).allowed is True

    def test_informational_tools_always_allowed(self):
        """Test that informational tools work in all states."""
        fsm = BookingFSM("test-info")

        for state in BookingState:
            fsm._state = state
            assert validate_tool_call("query_info", fsm).allowed is True
            assert validate_tool_call("escalate_to_human", fsm).allowed is True
            assert validate_tool_call("get_customer_history", fsm).allowed is True


# ============================================================================
# Test ToolValidationResult Structure
# ============================================================================


class TestToolValidationResultIntegration:
    """Test ToolValidationResult integration."""

    def test_result_has_all_fields_on_rejection(self, fsm_idle: BookingFSM):
        """Rejected validation should have all error fields populated."""
        result = validate_tool_call("book", fsm_idle)

        assert isinstance(result, ToolValidationResult)
        assert result.allowed is False
        assert result.error_code is not None
        assert result.error_message is not None
        assert result.redirect_message is not None

    def test_result_has_minimal_fields_on_success(self, fsm_idle: BookingFSM):
        """Successful validation should have minimal fields."""
        result = validate_tool_call("query_info", fsm_idle)

        assert isinstance(result, ToolValidationResult)
        assert result.allowed is True
        assert result.error_code is None
        assert result.error_message is None
