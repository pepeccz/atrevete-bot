"""
Unit tests for FSM tool validation module.

Tests Story 5-4 acceptance criteria:
- AC #1: Tools only execute if FSM state permits
- AC #2: FSM rejects book() in wrong states
- AC #6: Logging with FSM context
- AC #7: Availability tools only in specific states
"""

import pytest

from agent.fsm import BookingFSM, BookingState
from agent.fsm.tool_validation import (
    TOOL_DATA_REQUIREMENTS,
    TOOL_STATE_PERMISSIONS,
    ToolExecutionError,
    ToolValidationResult,
    can_execute_tool,
    get_allowed_tools,
    validate_tool_call,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def fsm_idle() -> BookingFSM:
    """FSM in IDLE state (no booking started)."""
    fsm = BookingFSM("test-conv-idle")
    return fsm


@pytest.fixture
def fsm_service_selection() -> BookingFSM:
    """FSM in SERVICE_SELECTION state."""
    fsm = BookingFSM("test-conv-service")
    fsm._state = BookingState.SERVICE_SELECTION
    return fsm


@pytest.fixture
def fsm_stylist_selection() -> BookingFSM:
    """FSM in STYLIST_SELECTION state with services selected."""
    fsm = BookingFSM("test-conv-stylist")
    fsm._state = BookingState.STYLIST_SELECTION
    fsm._collected_data = {"services": ["Corte de Caballero"]}
    return fsm


@pytest.fixture
def fsm_slot_selection() -> BookingFSM:
    """FSM in SLOT_SELECTION state with services and stylist."""
    fsm = BookingFSM("test-conv-slot")
    fsm._state = BookingState.SLOT_SELECTION
    fsm._collected_data = {
        "services": ["Corte de Caballero"],
        "stylist_id": "test-stylist-uuid",
    }
    return fsm


@pytest.fixture
def fsm_customer_data() -> BookingFSM:
    """FSM in CUSTOMER_DATA state with slot selected."""
    fsm = BookingFSM("test-conv-customer")
    fsm._state = BookingState.CUSTOMER_DATA
    fsm._collected_data = {
        "services": ["Corte de Caballero"],
        "stylist_id": "test-stylist-uuid",
        "slot": {"start_time": "2025-11-08T10:00:00+01:00", "duration_minutes": 30},
    }
    return fsm


@pytest.fixture
def fsm_confirmation() -> BookingFSM:
    """FSM in CONFIRMATION state with all data ready."""
    fsm = BookingFSM("test-conv-confirm")
    fsm._state = BookingState.CONFIRMATION
    fsm._collected_data = {
        "services": ["Corte de Caballero"],
        "stylist_id": "test-stylist-uuid",
        "slot": {"start_time": "2025-11-08T10:00:00+01:00", "duration_minutes": 30},
        "first_name": "María",
    }
    return fsm


@pytest.fixture
def fsm_confirmation_incomplete() -> BookingFSM:
    """FSM in CONFIRMATION state but missing required data."""
    fsm = BookingFSM("test-conv-confirm-incomplete")
    fsm._state = BookingState.CONFIRMATION
    fsm._collected_data = {
        "services": ["Corte de Caballero"],
        # Missing: stylist_id, slot, first_name
    }
    return fsm


# ============================================================================
# Test TOOL_STATE_PERMISSIONS (AC #1)
# ============================================================================


class TestToolStatePermissions:
    """Test the TOOL_STATE_PERMISSIONS mapping."""

    def test_permissions_matrix_has_all_tools(self):
        """All expected tools should be in permissions matrix."""
        expected_tools = [
            "query_info",
            "search_services",
            "manage_customer",
            "get_customer_history",
            "check_availability",
            "find_next_available",
            "book",
            "escalate_to_human",
        ]
        for tool in expected_tools:
            assert tool in TOOL_STATE_PERMISSIONS, f"Missing tool: {tool}"

    def test_informational_tools_allowed_in_all_states(self):
        """Informational tools (query_info, escalate_to_human) should work in any state."""
        all_states = list(BookingState)

        assert TOOL_STATE_PERMISSIONS["query_info"] == all_states
        assert TOOL_STATE_PERMISSIONS["escalate_to_human"] == all_states
        assert TOOL_STATE_PERMISSIONS["get_customer_history"] == all_states

    def test_search_services_allowed_states(self):
        """search_services should be allowed in IDLE and SERVICE_SELECTION."""
        allowed = TOOL_STATE_PERMISSIONS["search_services"]
        assert BookingState.IDLE in allowed
        assert BookingState.SERVICE_SELECTION in allowed
        assert BookingState.CONFIRMATION not in allowed

    def test_availability_tools_allowed_states(self):
        """Availability tools should only work in STYLIST_SELECTION and SLOT_SELECTION."""
        for tool in ["check_availability", "find_next_available"]:
            allowed = TOOL_STATE_PERMISSIONS[tool]
            assert BookingState.STYLIST_SELECTION in allowed
            assert BookingState.SLOT_SELECTION in allowed
            assert BookingState.IDLE not in allowed
            assert BookingState.SERVICE_SELECTION not in allowed
            assert BookingState.CONFIRMATION not in allowed

    def test_book_only_in_confirmation(self):
        """book() should only be allowed in CONFIRMATION state."""
        allowed = TOOL_STATE_PERMISSIONS["book"]
        assert allowed == [BookingState.CONFIRMATION]


# ============================================================================
# Test validate_tool_call (AC #1, #2)
# ============================================================================


class TestValidateToolCall:
    """Test validate_tool_call function."""

    def test_search_services_allowed_in_idle(self, fsm_idle: BookingFSM):
        """search_services should be allowed in IDLE state."""
        result = validate_tool_call("search_services", fsm_idle)
        assert result.allowed is True
        assert result.error_code is None

    def test_search_services_allowed_in_service_selection(
        self, fsm_service_selection: BookingFSM
    ):
        """search_services should be allowed in SERVICE_SELECTION state."""
        result = validate_tool_call("search_services", fsm_service_selection)
        assert result.allowed is True

    def test_search_services_rejected_in_confirmation(
        self, fsm_confirmation: BookingFSM
    ):
        """search_services should be rejected in CONFIRMATION state."""
        result = validate_tool_call("search_services", fsm_confirmation)
        assert result.allowed is False
        assert result.error_code == "TOOL_STATE_NOT_ALLOWED"
        assert "search_services" in result.error_message
        assert result.redirect_message is not None

    def test_book_rejected_in_service_selection(
        self, fsm_service_selection: BookingFSM
    ):
        """AC #2: book() should be rejected in SERVICE_SELECTION state."""
        result = validate_tool_call("book", fsm_service_selection)
        assert result.allowed is False
        assert result.error_code == "TOOL_STATE_NOT_ALLOWED"
        assert "confirmation" in result.error_message.lower()

    def test_book_rejected_in_slot_selection(self, fsm_slot_selection: BookingFSM):
        """book() should be rejected in SLOT_SELECTION state."""
        result = validate_tool_call("book", fsm_slot_selection)
        assert result.allowed is False
        assert result.error_code == "TOOL_STATE_NOT_ALLOWED"

    def test_book_allowed_in_confirmation_with_complete_data(
        self, fsm_confirmation: BookingFSM
    ):
        """book() should be allowed in CONFIRMATION with all required data."""
        result = validate_tool_call("book", fsm_confirmation)
        assert result.allowed is True
        assert result.error_code is None

    def test_book_rejected_in_confirmation_missing_data(
        self, fsm_confirmation_incomplete: BookingFSM
    ):
        """book() should be rejected in CONFIRMATION if data is missing."""
        result = validate_tool_call("book", fsm_confirmation_incomplete)
        assert result.allowed is False
        assert result.error_code == "MISSING_REQUIRED_DATA"
        assert "stylist_id" in result.error_message or "slot" in result.error_message

    def test_availability_tools_rejected_in_idle(self, fsm_idle: BookingFSM):
        """AC #7: Availability tools should be rejected in IDLE state."""
        for tool in ["check_availability", "find_next_available"]:
            result = validate_tool_call(tool, fsm_idle)
            assert result.allowed is False
            assert result.error_code == "TOOL_STATE_NOT_ALLOWED"

    def test_availability_tools_allowed_in_stylist_selection(
        self, fsm_stylist_selection: BookingFSM
    ):
        """AC #7: Availability tools should be allowed in STYLIST_SELECTION."""
        for tool in ["check_availability", "find_next_available"]:
            result = validate_tool_call(tool, fsm_stylist_selection)
            assert result.allowed is True

    def test_availability_tools_rejected_without_services(
        self, fsm_stylist_selection: BookingFSM
    ):
        """Availability tools should be rejected if services not selected."""
        fsm_stylist_selection._collected_data = {}  # Remove services
        for tool in ["check_availability", "find_next_available"]:
            result = validate_tool_call(tool, fsm_stylist_selection)
            assert result.allowed is False
            assert result.error_code == "MISSING_REQUIRED_DATA"
            assert "services" in result.error_message

    def test_query_info_always_allowed(
        self,
        fsm_idle: BookingFSM,
        fsm_service_selection: BookingFSM,
        fsm_confirmation: BookingFSM,
    ):
        """query_info should be allowed in any state."""
        for fsm in [fsm_idle, fsm_service_selection, fsm_confirmation]:
            result = validate_tool_call("query_info", fsm)
            assert result.allowed is True

    def test_escalate_always_allowed(
        self,
        fsm_idle: BookingFSM,
        fsm_confirmation: BookingFSM,
    ):
        """escalate_to_human should be allowed in any state."""
        for fsm in [fsm_idle, fsm_confirmation]:
            result = validate_tool_call("escalate_to_human", fsm)
            assert result.allowed is True

    def test_unknown_tool_allowed_by_default(self, fsm_idle: BookingFSM):
        """Unknown tools should be allowed by default (logged as warning)."""
        result = validate_tool_call("unknown_future_tool", fsm_idle)
        assert result.allowed is True


# ============================================================================
# Test can_execute_tool (Convenience Function)
# ============================================================================


class TestCanExecuteTool:
    """Test can_execute_tool convenience function."""

    def test_returns_true_when_allowed(self, fsm_idle: BookingFSM):
        """Should return True when tool is allowed."""
        assert can_execute_tool("search_services", fsm_idle) is True
        assert can_execute_tool("query_info", fsm_idle) is True

    def test_returns_false_when_not_allowed(self, fsm_idle: BookingFSM):
        """Should return False when tool is not allowed."""
        assert can_execute_tool("book", fsm_idle) is False
        assert can_execute_tool("check_availability", fsm_idle) is False


# ============================================================================
# Test get_allowed_tools
# ============================================================================


class TestGetAllowedTools:
    """Test get_allowed_tools function."""

    def test_idle_state_allowed_tools(self, fsm_idle: BookingFSM):
        """IDLE state should allow informational and service search tools."""
        allowed = get_allowed_tools(fsm_idle)
        assert "query_info" in allowed
        assert "search_services" in allowed
        assert "escalate_to_human" in allowed
        assert "manage_customer" in allowed
        assert "book" not in allowed
        assert "check_availability" not in allowed

    def test_stylist_selection_with_services(self, fsm_stylist_selection: BookingFSM):
        """STYLIST_SELECTION with services should allow availability tools."""
        allowed = get_allowed_tools(fsm_stylist_selection)
        assert "check_availability" in allowed
        assert "find_next_available" in allowed
        assert "query_info" in allowed
        assert "book" not in allowed

    def test_confirmation_with_complete_data(self, fsm_confirmation: BookingFSM):
        """CONFIRMATION with complete data should allow book."""
        allowed = get_allowed_tools(fsm_confirmation)
        assert "book" in allowed
        assert "query_info" in allowed
        assert "escalate_to_human" in allowed

    def test_confirmation_without_complete_data(
        self, fsm_confirmation_incomplete: BookingFSM
    ):
        """CONFIRMATION without complete data should NOT allow book."""
        allowed = get_allowed_tools(fsm_confirmation_incomplete)
        assert "book" not in allowed
        assert "query_info" in allowed  # Informational always allowed


# ============================================================================
# Test ToolExecutionError
# ============================================================================


class TestToolExecutionError:
    """Test ToolExecutionError exception class."""

    def test_error_creation(self):
        """Should create error with all fields."""
        error = ToolExecutionError(
            tool_name="book",
            fsm_state=BookingState.SERVICE_SELECTION,
            error_code="TOOL_STATE_NOT_ALLOWED",
            message="book() not allowed in SERVICE_SELECTION",
            details={"expected_state": "CONFIRMATION"},
        )
        assert error.tool_name == "book"
        assert error.fsm_state == BookingState.SERVICE_SELECTION
        assert error.error_code == "TOOL_STATE_NOT_ALLOWED"
        assert "book()" in str(error)

    def test_error_to_dict(self):
        """Should convert to dict correctly."""
        error = ToolExecutionError(
            tool_name="check_availability",
            fsm_state=BookingState.IDLE,
            error_code="TOOL_STATE_NOT_ALLOWED",
            message="Not allowed in IDLE",
        )
        error_dict = error.to_dict()
        assert error_dict["tool_name"] == "check_availability"
        assert error_dict["fsm_state"] == "idle"
        assert error_dict["error"] == "TOOL_STATE_NOT_ALLOWED"


# ============================================================================
# Test ToolValidationResult
# ============================================================================


class TestToolValidationResult:
    """Test ToolValidationResult dataclass."""

    def test_allowed_result(self):
        """Allowed result should have no error fields."""
        result = ToolValidationResult(allowed=True)
        assert result.allowed is True
        assert result.error_code is None
        assert result.error_message is None

    def test_rejected_result(self):
        """Rejected result should have error details."""
        result = ToolValidationResult(
            allowed=False,
            error_code="TOOL_STATE_NOT_ALLOWED",
            error_message="Tool not allowed",
            redirect_message="Please select services first",
        )
        assert result.allowed is False
        assert result.error_code == "TOOL_STATE_NOT_ALLOWED"
        assert result.redirect_message is not None


# ============================================================================
# Test Data Requirements
# ============================================================================


class TestToolDataRequirements:
    """Test TOOL_DATA_REQUIREMENTS mapping."""

    def test_book_requires_all_booking_data(self):
        """book should require all booking fields."""
        required = TOOL_DATA_REQUIREMENTS["book"]
        assert "services" in required
        assert "stylist_id" in required
        assert "slot" in required
        assert "first_name" in required

    def test_availability_requires_services(self):
        """Availability tools should require services."""
        for tool in ["check_availability", "find_next_available"]:
            required = TOOL_DATA_REQUIREMENTS[tool]
            assert "services" in required

    def test_informational_tools_no_requirements(self):
        """Informational tools should have no requirements."""
        for tool in ["query_info", "escalate_to_human", "search_services"]:
            required = TOOL_DATA_REQUIREMENTS[tool]
            assert len(required) == 0


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_services_list_treated_as_missing(
        self, fsm_stylist_selection: BookingFSM
    ):
        """Empty services list should be treated as missing."""
        fsm_stylist_selection._collected_data = {"services": []}
        result = validate_tool_call("check_availability", fsm_stylist_selection)
        assert result.allowed is False
        assert result.error_code == "MISSING_REQUIRED_DATA"

    def test_empty_string_treated_as_missing(self, fsm_confirmation: BookingFSM):
        """Empty string should be treated as missing."""
        fsm_confirmation._collected_data["first_name"] = ""
        result = validate_tool_call("book", fsm_confirmation)
        assert result.allowed is False
        assert result.error_code == "MISSING_REQUIRED_DATA"

    def test_none_value_treated_as_missing(self, fsm_confirmation: BookingFSM):
        """None value should be treated as missing."""
        fsm_confirmation._collected_data["first_name"] = None
        result = validate_tool_call("book", fsm_confirmation)
        assert result.allowed is False
        assert result.error_code == "MISSING_REQUIRED_DATA"
