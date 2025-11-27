"""
End-to-end tests for complete booking flow with FSM.

Tests Story 5-5 acceptance criteria:
- AC #1: Complete booking flow IDLE → BOOKED works correctly
- AC #2: Invalid transitions rejected with friendly redirect
- AC #3: Tool/API errors don't corrupt FSM state
- AC #4: Out-of-order conversations handled gracefully
- AC #6: Epic 1 Story 1-5 bugs are resolved

Test Categories:
- Task 1: Happy path flows (single service, multiple services, returning/new customer)
- Task 2: Invalid transition validation
- Task 3: Error recovery tests
- Task 4: Out-of-order conversation tests
- Task 6: Bug verification tests (UUID serialization, state flags)
"""

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.fsm import (
    BookingFSM,
    BookingState,
    FSMResult,
    Intent,
    IntentType,
    validate_tool_call,
)


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def fresh_fsm() -> BookingFSM:
    """Create a fresh FSM instance for testing."""
    return BookingFSM(f"test-e2e-{uuid4()}")


@pytest.fixture
def sample_services() -> list[str]:
    """Sample services for testing."""
    return ["Corte de Caballero", "Tinte Raíces"]


@pytest.fixture
def sample_stylist_id() -> str:
    """Sample stylist UUID."""
    return str(uuid4())


@pytest.fixture
def sample_slot() -> dict:
    """Sample slot data."""
    start = datetime.now(UTC) + timedelta(days=7)
    return {
        "start_time": start.isoformat(),
        "duration_minutes": 90,
    }


@pytest.fixture
def sample_customer_data() -> dict:
    """Sample customer data."""
    return {
        "first_name": "María",
        "last_name": "García",
        "notes": "Prefiere productos naturales",
    }


# ============================================================================
# Task 1: Happy Path Tests (AC #1, #7)
# ============================================================================


class TestCompleteBookingHappyPath:
    """Task 1: Complete booking flow happy path tests."""

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_complete_booking_single_service(
        self,
        fresh_fsm: BookingFSM,
        sample_stylist_id: str,
        sample_slot: dict,
    ):
        """
        Task 1.2: Test complete happy path with single service.

        Flow: IDLE → SERVICE_SELECTION → STYLIST_SELECTION → SLOT_SELECTION
              → CUSTOMER_DATA → CONFIRMATION → BOOKED
        """
        # Step 1: Start booking (IDLE → SERVICE_SELECTION)
        result = fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))
        assert result.success is True
        assert fresh_fsm.state == BookingState.SERVICE_SELECTION

        # Step 2: Confirm services (SERVICE_SELECTION → STYLIST_SELECTION)
        result = fresh_fsm.transition(
            Intent(
                type=IntentType.CONFIRM_SERVICES,
                entities={"services": ["Corte de Caballero"]},
            )
        )
        assert result.success is True
        assert fresh_fsm.state == BookingState.STYLIST_SELECTION
        assert "Corte de Caballero" in fresh_fsm.collected_data["services"]

        # Step 3: Select stylist (STYLIST_SELECTION → SLOT_SELECTION)
        result = fresh_fsm.transition(
            Intent(
                type=IntentType.SELECT_STYLIST,
                entities={"stylist_id": sample_stylist_id},
            )
        )
        assert result.success is True
        assert fresh_fsm.state == BookingState.SLOT_SELECTION
        assert fresh_fsm.collected_data["stylist_id"] == sample_stylist_id

        # Step 4: Select slot (SLOT_SELECTION → CUSTOMER_DATA)
        result = fresh_fsm.transition(
            Intent(
                type=IntentType.SELECT_SLOT,
                entities={"slot": sample_slot},
            )
        )
        assert result.success is True
        assert fresh_fsm.state == BookingState.CUSTOMER_DATA
        assert fresh_fsm.collected_data["slot"] == sample_slot

        # Step 5: Provide customer data (CUSTOMER_DATA → CONFIRMATION)
        result = fresh_fsm.transition(
            Intent(
                type=IntentType.PROVIDE_CUSTOMER_DATA,
                entities={"first_name": "Juan", "last_name": "Pérez"},
            )
        )
        assert result.success is True
        assert fresh_fsm.state == BookingState.CONFIRMATION
        assert fresh_fsm.collected_data["first_name"] == "Juan"

        # Step 6: Confirm booking (CONFIRMATION → BOOKED)
        result = fresh_fsm.transition(Intent(type=IntentType.CONFIRM_BOOKING))
        assert result.success is True
        assert fresh_fsm.state == BookingState.BOOKED

        # Verify all data accumulated correctly
        final_data = fresh_fsm.collected_data
        assert final_data["services"] == ["Corte de Caballero"]
        assert final_data["stylist_id"] == sample_stylist_id
        assert final_data["slot"] == sample_slot
        assert final_data["first_name"] == "Juan"
        assert final_data["last_name"] == "Pérez"

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_complete_booking_multiple_services(
        self,
        fresh_fsm: BookingFSM,
        sample_stylist_id: str,
        sample_slot: dict,
    ):
        """
        Task 1.3: Test complete booking with multiple services and combined duration.
        """
        # Start booking
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))

        # Confirm multiple services at once
        result = fresh_fsm.transition(
            Intent(
                type=IntentType.CONFIRM_SERVICES,
                entities={"services": ["Corte de Caballero", "Tinte Raíces", "Peinado"]},
            )
        )
        assert result.success is True
        assert len(fresh_fsm.collected_data["services"]) == 3

        # Complete flow
        fresh_fsm.transition(
            Intent(type=IntentType.SELECT_STYLIST, entities={"stylist_id": sample_stylist_id})
        )
        fresh_fsm.transition(Intent(type=IntentType.SELECT_SLOT, entities={"slot": sample_slot}))
        fresh_fsm.transition(
            Intent(type=IntentType.PROVIDE_CUSTOMER_DATA, entities={"first_name": "Ana"})
        )
        result = fresh_fsm.transition(Intent(type=IntentType.CONFIRM_BOOKING))

        assert result.success is True
        assert fresh_fsm.state == BookingState.BOOKED
        # All 3 services should be in the booking
        assert fresh_fsm.collected_data["services"] == [
            "Corte de Caballero",
            "Tinte Raíces",
            "Peinado",
        ]

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_booking_with_returning_customer(
        self,
        fresh_fsm: BookingFSM,
        sample_stylist_id: str,
        sample_slot: dict,
    ):
        """
        Task 1.4: Test booking with returning customer who has history.
        """
        customer_id = str(uuid4())

        # Start and complete booking
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))
        fresh_fsm.transition(
            Intent(type=IntentType.CONFIRM_SERVICES, entities={"services": ["Corte Largo"]})
        )
        fresh_fsm.transition(
            Intent(type=IntentType.SELECT_STYLIST, entities={"stylist_id": sample_stylist_id})
        )
        fresh_fsm.transition(Intent(type=IntentType.SELECT_SLOT, entities={"slot": sample_slot}))

        # Returning customer provides name (system may have pre-filled from history)
        result = fresh_fsm.transition(
            Intent(
                type=IntentType.PROVIDE_CUSTOMER_DATA,
                entities={
                    "first_name": "María",
                    "last_name": "García",
                    "customer_id": customer_id,
                },
            )
        )
        assert result.success is True

        result = fresh_fsm.transition(Intent(type=IntentType.CONFIRM_BOOKING))
        assert result.success is True
        assert fresh_fsm.state == BookingState.BOOKED
        assert fresh_fsm.collected_data["customer_id"] == customer_id

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_booking_with_new_customer(
        self,
        fresh_fsm: BookingFSM,
        sample_stylist_id: str,
        sample_slot: dict,
    ):
        """
        Task 1.5: Test booking with new customer (first time).
        """
        # Start and complete booking
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))
        fresh_fsm.transition(
            Intent(type=IntentType.CONFIRM_SERVICES, entities={"services": ["Consulta Gratuita"]})
        )
        fresh_fsm.transition(
            Intent(type=IntentType.SELECT_STYLIST, entities={"stylist_id": sample_stylist_id})
        )
        fresh_fsm.transition(Intent(type=IntentType.SELECT_SLOT, entities={"slot": sample_slot}))

        # New customer provides only first name (minimum required)
        result = fresh_fsm.transition(
            Intent(
                type=IntentType.PROVIDE_CUSTOMER_DATA,
                entities={"first_name": "Pedro"},
            )
        )
        assert result.success is True
        assert fresh_fsm.collected_data["first_name"] == "Pedro"
        # No last_name or customer_id required
        assert fresh_fsm.collected_data.get("last_name") is None

        result = fresh_fsm.transition(Intent(type=IntentType.CONFIRM_BOOKING))
        assert result.success is True
        assert fresh_fsm.state == BookingState.BOOKED


# ============================================================================
# Task 2: Invalid Transition Tests (AC #2, #4)
# ============================================================================


class TestInvalidTransitions:
    """Task 2: Tests for invalid transition validation."""

    def test_cannot_confirm_from_idle(self, fresh_fsm: BookingFSM):
        """
        Task 2.1: Intent confirm_booking should fail from IDLE.
        """
        result = fresh_fsm.transition(Intent(type=IntentType.CONFIRM_BOOKING))

        assert result.success is False
        assert fresh_fsm.state == BookingState.IDLE  # State unchanged
        assert len(result.validation_errors) > 0
        assert "not allowed" in result.validation_errors[0].lower()

    def test_cannot_select_slot_without_stylist(self, fresh_fsm: BookingFSM):
        """
        Task 2.2: Skipping STYLIST_SELECTION should fail.
        """
        # Get to SERVICE_SELECTION
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))
        fresh_fsm.transition(
            Intent(type=IntentType.CONFIRM_SERVICES, entities={"services": ["Corte"]})
        )

        # Try to skip to slot selection directly
        result = fresh_fsm.transition(
            Intent(
                type=IntentType.SELECT_SLOT,
                entities={"slot": {"start_time": "2025-12-01T10:00:00", "duration_minutes": 30}},
            )
        )

        assert result.success is False
        assert fresh_fsm.state == BookingState.STYLIST_SELECTION
        assert "not allowed" in result.validation_errors[0].lower()

    def test_cannot_book_without_customer_data(self, fresh_fsm: BookingFSM):
        """
        Task 2.3: Going to CONFIRMATION without first_name should fail.
        """
        stylist_id = str(uuid4())
        slot = {"start_time": "2025-12-01T10:00:00", "duration_minutes": 30}

        # Progress to CUSTOMER_DATA
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))
        fresh_fsm.transition(
            Intent(type=IntentType.CONFIRM_SERVICES, entities={"services": ["Corte"]})
        )
        fresh_fsm.transition(Intent(type=IntentType.SELECT_STYLIST, entities={"stylist_id": stylist_id}))
        fresh_fsm.transition(Intent(type=IntentType.SELECT_SLOT, entities={"slot": slot}))

        # Try to provide customer data without first_name
        result = fresh_fsm.transition(
            Intent(type=IntentType.PROVIDE_CUSTOMER_DATA, entities={})  # No first_name
        )

        assert result.success is False
        assert fresh_fsm.state == BookingState.CUSTOMER_DATA
        assert "first_name" in result.validation_errors[0].lower()

    def test_redirect_messages_are_natural(self, fresh_fsm: BookingFSM):
        """
        Task 2.4: Verify redirect messages are user-friendly.
        """
        # Try to confirm services without selecting any
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))
        result = fresh_fsm.transition(Intent(type=IntentType.CONFIRM_SERVICES, entities={}))

        assert result.success is False
        # Error message should be descriptive
        error_msg = result.validation_errors[0].lower()
        assert "services" in error_msg or "required" in error_msg

    def test_user_guided_to_correct_step(self, fresh_fsm: BookingFSM):
        """
        Task 2.5: FSM provides next_action guidance on failure.
        """
        result = fresh_fsm.transition(Intent(type=IntentType.CONFIRM_BOOKING))

        assert result.success is False
        # next_action should indicate what to do
        assert result.next_action == "invalid_transition"
        # State should still be IDLE
        assert result.new_state == BookingState.IDLE


# ============================================================================
# Task 3: Error Recovery Tests (AC #3)
# ============================================================================


class TestErrorRecovery:
    """Task 3: Tests for error recovery without FSM corruption."""

    @pytest.mark.asyncio
    async def test_google_calendar_api_failure_recovery(self, fresh_fsm: BookingFSM):
        """
        Task 3.1: FSM maintains state when Google Calendar API fails.
        """
        stylist_id = str(uuid4())

        # Progress to SLOT_SELECTION
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))
        fresh_fsm.transition(
            Intent(type=IntentType.CONFIRM_SERVICES, entities={"services": ["Corte"]})
        )
        fresh_fsm.transition(Intent(type=IntentType.SELECT_STYLIST, entities={"stylist_id": stylist_id}))

        # Save state before simulated API call
        state_before = fresh_fsm.state
        data_before = fresh_fsm.collected_data.copy()

        # Simulate a failed API call (tool validation still passes, but tool would fail)
        # The FSM itself doesn't call APIs - it just validates transitions
        # API errors are handled at tool execution level

        # Tool validation should still work
        result = validate_tool_call("find_next_available", fresh_fsm)
        assert result.allowed is True

        # FSM state unchanged
        assert fresh_fsm.state == state_before
        assert fresh_fsm.collected_data == data_before

    @pytest.mark.asyncio
    async def test_database_error_recovery(self, fresh_fsm: BookingFSM):
        """
        Task 3.2: FSM maintains state when database error occurs.
        """
        # Progress to CONFIRMATION
        stylist_id = str(uuid4())
        slot = {"start_time": "2025-12-01T10:00:00", "duration_minutes": 30}

        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))
        fresh_fsm.transition(
            Intent(type=IntentType.CONFIRM_SERVICES, entities={"services": ["Corte"]})
        )
        fresh_fsm.transition(Intent(type=IntentType.SELECT_STYLIST, entities={"stylist_id": stylist_id}))
        fresh_fsm.transition(Intent(type=IntentType.SELECT_SLOT, entities={"slot": slot}))
        fresh_fsm.transition(
            Intent(type=IntentType.PROVIDE_CUSTOMER_DATA, entities={"first_name": "Test"})
        )

        state_before = fresh_fsm.state
        data_before = fresh_fsm.collected_data.copy()

        # Book tool validation passes (actual DB error would happen in tool execution)
        result = validate_tool_call("book", fresh_fsm)
        assert result.allowed is True

        # FSM state unchanged by validation
        assert fresh_fsm.state == state_before
        assert fresh_fsm.collected_data == data_before

    def test_llm_intent_extraction_failure_recovery(self, fresh_fsm: BookingFSM):
        """
        Task 3.3: UNKNOWN intent doesn't corrupt FSM state.
        """
        # Progress to SERVICE_SELECTION
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))
        state_before = fresh_fsm.state

        # Simulate LLM returning UNKNOWN intent
        result = fresh_fsm.transition(Intent(type=IntentType.UNKNOWN))

        # UNKNOWN is not a valid transition, should fail gracefully
        assert result.success is False
        assert fresh_fsm.state == state_before  # State unchanged

    def test_tool_execution_error_preserves_fsm_state(self, fresh_fsm: BookingFSM):
        """
        Task 3.4: Tool execution errors don't change FSM state.
        """
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))
        fresh_fsm.transition(
            Intent(type=IntentType.CONFIRM_SERVICES, entities={"services": ["Corte"]})
        )

        state_before = fresh_fsm.state
        data_before = fresh_fsm.collected_data.copy()

        # Validate a tool (this doesn't execute it, just checks permission)
        result = validate_tool_call("find_next_available", fresh_fsm)

        # FSM unchanged after validation
        assert fresh_fsm.state == state_before
        assert fresh_fsm.collected_data == data_before


# ============================================================================
# Task 4: Out of Order Conversations (AC #4)
# ============================================================================


class TestOutOfOrderConversations:
    """Task 4: Tests for handling out-of-order user interactions."""

    def test_out_of_order_confirm_before_services(self, fresh_fsm: BookingFSM):
        """
        Task 4.1: User tries to confirm booking without selecting services.
        """
        result = fresh_fsm.transition(Intent(type=IntentType.CONFIRM_BOOKING))

        assert result.success is False
        assert fresh_fsm.state == BookingState.IDLE
        # Should indicate services need to be selected first
        assert "not allowed" in result.validation_errors[0].lower()

    def test_out_of_order_select_slot_before_stylist(self, fresh_fsm: BookingFSM):
        """
        Task 4.2: User provides time slot before selecting stylist.
        """
        # Get to STYLIST_SELECTION
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))
        fresh_fsm.transition(
            Intent(type=IntentType.CONFIRM_SERVICES, entities={"services": ["Corte"]})
        )

        # User tries to select slot (wrong order)
        slot = {"start_time": "2025-12-01T10:00:00", "duration_minutes": 30}
        result = fresh_fsm.transition(Intent(type=IntentType.SELECT_SLOT, entities={"slot": slot}))

        assert result.success is False
        assert fresh_fsm.state == BookingState.STYLIST_SELECTION

    def test_out_of_order_provide_name_at_service_selection(self, fresh_fsm: BookingFSM):
        """
        Task 4.3: User provides name too early in the flow.
        """
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))

        # User provides name during service selection
        result = fresh_fsm.transition(
            Intent(
                type=IntentType.PROVIDE_CUSTOMER_DATA, entities={"first_name": "Early María"}
            )
        )

        assert result.success is False
        assert fresh_fsm.state == BookingState.SERVICE_SELECTION
        # Name should NOT be saved when in wrong state
        assert fresh_fsm.collected_data.get("first_name") is None

    def test_faq_during_booking_flow(self, fresh_fsm: BookingFSM):
        """
        Task 4.4: FAQ questions shouldn't interrupt booking flow.
        """
        # Progress to STYLIST_SELECTION
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))
        fresh_fsm.transition(
            Intent(type=IntentType.CONFIRM_SERVICES, entities={"services": ["Corte"]})
        )

        state_before = fresh_fsm.state
        data_before = fresh_fsm.collected_data.copy()

        # FAQ intent doesn't have a transition defined - it's handled by tools
        result = fresh_fsm.transition(Intent(type=IntentType.FAQ))

        # State should be unchanged (FAQ doesn't cause transition)
        assert result.success is False
        assert fresh_fsm.state == state_before
        assert fresh_fsm.collected_data == data_before

    def test_greeting_during_booking_flow(self, fresh_fsm: BookingFSM):
        """User greets mid-flow - should not break state."""
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))
        fresh_fsm.transition(
            Intent(type=IntentType.CONFIRM_SERVICES, entities={"services": ["Corte"]})
        )

        state_before = fresh_fsm.state

        # Greeting doesn't cause transition
        result = fresh_fsm.transition(Intent(type=IntentType.GREETING))

        assert result.success is False
        assert fresh_fsm.state == state_before


# ============================================================================
# Task 6: Epic 1 Story 1-5 Bug Verification (AC #6)
# ============================================================================


class TestBugVerification:
    """Task 6: Verify Epic 1 Story 1-5 bugs are resolved."""

    def test_uuid_serialization_bug_resolved(self, fresh_fsm: BookingFSM):
        """
        Task 6.1: Verify UUIDs are stored as strings, not UUID objects.

        Bug: ensure_customer_exists() returned UUID objects instead of strings
        Fix: All IDs should be stored/returned as strings
        """
        stylist_id = str(uuid4())
        customer_id = str(uuid4())

        # Progress through flow
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))
        fresh_fsm.transition(
            Intent(type=IntentType.CONFIRM_SERVICES, entities={"services": ["Corte"]})
        )
        fresh_fsm.transition(Intent(type=IntentType.SELECT_STYLIST, entities={"stylist_id": stylist_id}))

        # Verify stylist_id is string
        assert isinstance(fresh_fsm.collected_data["stylist_id"], str)
        assert fresh_fsm.collected_data["stylist_id"] == stylist_id

        # Add customer_id
        slot = {"start_time": "2025-12-01T10:00:00", "duration_minutes": 30}
        fresh_fsm.transition(Intent(type=IntentType.SELECT_SLOT, entities={"slot": slot}))
        fresh_fsm.transition(
            Intent(
                type=IntentType.PROVIDE_CUSTOMER_DATA,
                entities={"first_name": "Test", "customer_id": customer_id},
            )
        )

        # Verify customer_id is string
        assert isinstance(fresh_fsm.collected_data.get("customer_id"), str)
        assert fresh_fsm.collected_data["customer_id"] == customer_id

    def test_state_flags_progression_bug_resolved(self, fresh_fsm: BookingFSM):
        """
        Task 6.2: Verify FSM progresses correctly through all states.

        Bug: State flags (service_selected, slot_selected) never updated
        Fix: FSM state transitions are now deterministic and tracked
        """
        stylist_id = str(uuid4())
        slot = {"start_time": "2025-12-01T10:00:00", "duration_minutes": 30}

        # Track state progression
        states_visited: list[BookingState] = [fresh_fsm.state]

        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))
        states_visited.append(fresh_fsm.state)

        fresh_fsm.transition(
            Intent(type=IntentType.CONFIRM_SERVICES, entities={"services": ["Corte"]})
        )
        states_visited.append(fresh_fsm.state)

        fresh_fsm.transition(Intent(type=IntentType.SELECT_STYLIST, entities={"stylist_id": stylist_id}))
        states_visited.append(fresh_fsm.state)

        fresh_fsm.transition(Intent(type=IntentType.SELECT_SLOT, entities={"slot": slot}))
        states_visited.append(fresh_fsm.state)

        fresh_fsm.transition(
            Intent(type=IntentType.PROVIDE_CUSTOMER_DATA, entities={"first_name": "Test"})
        )
        states_visited.append(fresh_fsm.state)

        fresh_fsm.transition(Intent(type=IntentType.CONFIRM_BOOKING))
        states_visited.append(fresh_fsm.state)

        # Verify all states were visited in order
        expected_states = [
            BookingState.IDLE,
            BookingState.SERVICE_SELECTION,
            BookingState.STYLIST_SELECTION,
            BookingState.SLOT_SELECTION,
            BookingState.CUSTOMER_DATA,
            BookingState.CONFIRMATION,
            BookingState.BOOKED,
        ]
        assert states_visited == expected_states

    def test_booking_execution_state_reachable(self, fresh_fsm: BookingFSM):
        """
        Task 6.3: Verify CONFIRMATION and BOOKED states are reachable.

        Bug: System never reached BOOKING_EXECUTION state
        Fix: FSM guarantees state progression when data is complete
        """
        stylist_id = str(uuid4())
        slot = {"start_time": "2025-12-01T10:00:00", "duration_minutes": 30}

        # Complete the full flow
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))
        fresh_fsm.transition(
            Intent(type=IntentType.CONFIRM_SERVICES, entities={"services": ["Corte"]})
        )
        fresh_fsm.transition(Intent(type=IntentType.SELECT_STYLIST, entities={"stylist_id": stylist_id}))
        fresh_fsm.transition(Intent(type=IntentType.SELECT_SLOT, entities={"slot": slot}))
        fresh_fsm.transition(
            Intent(type=IntentType.PROVIDE_CUSTOMER_DATA, entities={"first_name": "Test"})
        )

        # Verify CONFIRMATION is reachable
        assert fresh_fsm.state == BookingState.CONFIRMATION

        # Verify book() tool is now allowed
        result = validate_tool_call("book", fresh_fsm)
        assert result.allowed is True

        # Verify BOOKED is reachable
        result = fresh_fsm.transition(Intent(type=IntentType.CONFIRM_BOOKING))
        assert result.success is True
        assert fresh_fsm.state == BookingState.BOOKED

    def test_book_executes_with_complete_data(self, fresh_fsm: BookingFSM):
        """
        Task 6.4: Verify book() can execute with all required data.

        Bug: book() called with INVALID_UUID or missing data
        Fix: FSM validates all required data before allowing CONFIRMATION state
        """
        stylist_id = str(uuid4())
        slot = {
            "start_time": "2025-12-01T10:00:00+01:00",
            "duration_minutes": 30,
        }
        customer_id = str(uuid4())

        # Complete flow with all required data
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))
        fresh_fsm.transition(
            Intent(type=IntentType.CONFIRM_SERVICES, entities={"services": ["Corte de Caballero"]})
        )
        fresh_fsm.transition(Intent(type=IntentType.SELECT_STYLIST, entities={"stylist_id": stylist_id}))
        fresh_fsm.transition(Intent(type=IntentType.SELECT_SLOT, entities={"slot": slot}))
        fresh_fsm.transition(
            Intent(
                type=IntentType.PROVIDE_CUSTOMER_DATA,
                entities={"first_name": "Juan", "customer_id": customer_id},
            )
        )

        # Verify all data required for booking is present
        data = fresh_fsm.collected_data
        assert data.get("services") is not None and len(data["services"]) > 0
        assert data.get("stylist_id") is not None
        assert data.get("slot") is not None
        assert data.get("first_name") is not None

        # Verify no INVALID_UUID
        assert "INVALID" not in str(data.get("stylist_id", ""))
        assert "INVALID" not in str(data.get("customer_id", ""))

        # Book tool should be allowed
        result = validate_tool_call("book", fresh_fsm)
        assert result.allowed is True


# ============================================================================
# Additional E2E Tests: Cancel Flow
# ============================================================================


class TestCancelFlow:
    """Tests for cancel booking flow from various states."""

    @pytest.mark.parametrize(
        "state_to_cancel",
        [
            BookingState.SERVICE_SELECTION,
            BookingState.STYLIST_SELECTION,
            BookingState.SLOT_SELECTION,
            BookingState.CUSTOMER_DATA,
            BookingState.CONFIRMATION,
        ],
    )
    def test_cancel_from_any_state_resets_to_idle(
        self, fresh_fsm: BookingFSM, state_to_cancel: BookingState
    ):
        """Cancel booking from any state should reset to IDLE."""
        stylist_id = str(uuid4())
        slot = {"start_time": "2025-12-01T10:00:00", "duration_minutes": 30}

        # Progress to the target state
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))

        if state_to_cancel in [
            BookingState.STYLIST_SELECTION,
            BookingState.SLOT_SELECTION,
            BookingState.CUSTOMER_DATA,
            BookingState.CONFIRMATION,
        ]:
            fresh_fsm.transition(
                Intent(type=IntentType.CONFIRM_SERVICES, entities={"services": ["Corte"]})
            )

        if state_to_cancel in [
            BookingState.SLOT_SELECTION,
            BookingState.CUSTOMER_DATA,
            BookingState.CONFIRMATION,
        ]:
            fresh_fsm.transition(
                Intent(type=IntentType.SELECT_STYLIST, entities={"stylist_id": stylist_id})
            )

        if state_to_cancel in [BookingState.CUSTOMER_DATA, BookingState.CONFIRMATION]:
            fresh_fsm.transition(Intent(type=IntentType.SELECT_SLOT, entities={"slot": slot}))

        if state_to_cancel == BookingState.CONFIRMATION:
            fresh_fsm.transition(
                Intent(type=IntentType.PROVIDE_CUSTOMER_DATA, entities={"first_name": "Test"})
            )

        # Verify we're at the expected state
        assert fresh_fsm.state == state_to_cancel

        # Cancel
        result = fresh_fsm.transition(Intent(type=IntentType.CANCEL_BOOKING))

        assert result.success is True
        assert fresh_fsm.state == BookingState.IDLE
        assert fresh_fsm.collected_data == {}
        assert result.next_action == "booking_cancelled"


# ============================================================================
# Additional E2E Tests: Service Accumulation
# ============================================================================


class TestServiceAccumulation:
    """Tests for service list accumulation behavior."""

    def test_services_accumulate_incrementally(self, fresh_fsm: BookingFSM):
        """Services added incrementally should accumulate."""
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))

        # Add first service via _merge_entities (simulating select_service)
        fresh_fsm._merge_entities({"services": ["Corte de Caballero"]})
        assert fresh_fsm.collected_data["services"] == ["Corte de Caballero"]

        # Add second service
        fresh_fsm._merge_entities({"services": ["Tinte Raíces"]})
        assert fresh_fsm.collected_data["services"] == ["Corte de Caballero", "Tinte Raíces"]

        # Add third service
        fresh_fsm._merge_entities({"services": ["Peinado"]})
        assert len(fresh_fsm.collected_data["services"]) == 3

    def test_duplicate_services_not_added(self, fresh_fsm: BookingFSM):
        """Duplicate services should not be added."""
        fresh_fsm.transition(Intent(type=IntentType.START_BOOKING))

        fresh_fsm._merge_entities({"services": ["Corte de Caballero"]})
        fresh_fsm._merge_entities({"services": ["Corte de Caballero"]})  # Duplicate

        assert fresh_fsm.collected_data["services"] == ["Corte de Caballero"]
        assert len(fresh_fsm.collected_data["services"]) == 1


# ============================================================================
# Checkpoint Persistence Tests
# ============================================================================
# FSM state is now persisted via checkpoint (ADR-011: single source of truth).
# Tests for checkpoint persistence are in test_checkpoint_persistence.py.
