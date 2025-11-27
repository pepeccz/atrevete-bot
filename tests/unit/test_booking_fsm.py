"""
Unit tests for BookingFSM - FSM controller for booking flow.

Tests cover:
- State enum verification (7 states)
- State transitions (valid and invalid)
- Cancel booking from all states
- Data accumulation in collected_data
- Redis persistence (persist/load)
- Logging behavior
"""

import json
import logging
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.fsm import (
    BookingFSM,
    BookingState,
    FSMResult,
    Intent,
    IntentType,
)


class TestBookingStateEnum:
    """Tests for BookingState enum (AC #1)."""

    def test_booking_state_has_7_values(self):
        """BookingState enum has exactly 7 states."""
        assert len(BookingState) == 7

    def test_booking_state_values(self):
        """BookingState enum has correct state values."""
        expected_states = [
            "idle",
            "service_selection",
            "stylist_selection",
            "slot_selection",
            "customer_data",
            "confirmation",
            "booked",
        ]
        actual_states = [s.value for s in BookingState]
        assert sorted(actual_states) == sorted(expected_states)

    def test_booking_state_is_str_enum(self):
        """BookingState enum values are strings."""
        for state in BookingState:
            assert isinstance(state.value, str)


class TestIntentTypeEnum:
    """Tests for IntentType enum."""

    def test_intent_type_has_13_values(self):
        """IntentType enum has 13 types as documented."""
        assert len(IntentType) == 13

    def test_booking_flow_intents(self):
        """Booking flow intents are present."""
        booking_intents = [
            IntentType.START_BOOKING,
            IntentType.SELECT_SERVICE,
            IntentType.CONFIRM_SERVICES,
            IntentType.SELECT_STYLIST,
            IntentType.SELECT_SLOT,
            IntentType.PROVIDE_CUSTOMER_DATA,
            IntentType.CONFIRM_BOOKING,
            IntentType.CANCEL_BOOKING,
        ]
        assert all(intent in IntentType for intent in booking_intents)

    def test_general_intents(self):
        """General intents are present."""
        general_intents = [
            IntentType.GREETING,
            IntentType.FAQ,
            IntentType.CHECK_AVAILABILITY,
            IntentType.ESCALATE,
            IntentType.UNKNOWN,
        ]
        assert all(intent in IntentType for intent in general_intents)


class TestBookingFSMInitialization:
    """Tests for BookingFSM initialization (AC #1)."""

    def test_fsm_initializes_in_idle_state(self):
        """New FSM starts in IDLE state."""
        fsm = BookingFSM("test-conv-123")
        assert fsm.state == BookingState.IDLE

    def test_fsm_initializes_with_empty_collected_data(self):
        """New FSM starts with empty collected_data."""
        fsm = BookingFSM("test-conv-123")
        assert fsm.collected_data == {}

    def test_fsm_stores_conversation_id(self):
        """FSM stores the conversation_id."""
        fsm = BookingFSM("test-conv-123")
        assert fsm.conversation_id == "test-conv-123"


class TestCanTransition:
    """Tests for can_transition method (AC #2)."""

    def test_can_transition_valid_start_booking(self):
        """can_transition returns True for valid start_booking from IDLE."""
        fsm = BookingFSM("test-conv")
        intent = Intent(type=IntentType.START_BOOKING)
        assert fsm.can_transition(intent) is True

    def test_can_transition_invalid_from_idle(self):
        """can_transition returns False for invalid intent from IDLE."""
        fsm = BookingFSM("test-conv")
        intent = Intent(type=IntentType.CONFIRM_BOOKING)
        assert fsm.can_transition(intent) is False

    def test_can_transition_confirm_services_requires_data(self):
        """can_transition returns False when required data is missing."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SERVICE_SELECTION
        # No services in collected_data or entities
        intent = Intent(type=IntentType.CONFIRM_SERVICES)
        assert fsm.can_transition(intent) is False

    def test_can_transition_confirm_services_with_data(self):
        """can_transition returns True when required data is present."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SERVICE_SELECTION
        fsm._collected_data = {"services": ["Corte largo"]}
        intent = Intent(type=IntentType.CONFIRM_SERVICES)
        assert fsm.can_transition(intent) is True

    def test_can_transition_cancel_always_allowed(self):
        """can_transition returns True for cancel from any state."""
        for state in BookingState:
            if state == BookingState.BOOKED:
                continue  # BOOKED auto-resets
            fsm = BookingFSM("test-conv")
            fsm._state = state
            intent = Intent(type=IntentType.CANCEL_BOOKING)
            assert fsm.can_transition(intent) is True, f"Cancel should be allowed from {state}"

    def test_can_transition_select_stylist_requires_stylist_id(self):
        """can_transition returns False when stylist_id is missing."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.STYLIST_SELECTION
        fsm._collected_data = {"services": ["Corte largo"]}
        intent = Intent(type=IntentType.SELECT_STYLIST)  # No stylist_id in entities
        assert fsm.can_transition(intent) is False

    def test_can_transition_with_entities_in_intent(self):
        """can_transition checks entities from intent, not just collected_data."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.STYLIST_SELECTION
        fsm._collected_data = {"services": ["Corte largo"]}
        intent = Intent(
            type=IntentType.SELECT_STYLIST,
            entities={"stylist_id": "stylist-uuid-123"},
        )
        assert fsm.can_transition(intent) is True


class TestTransition:
    """Tests for transition method (AC #3)."""

    def test_transition_success_updates_state(self):
        """Successful transition updates the state."""
        fsm = BookingFSM("test-conv")
        intent = Intent(type=IntentType.START_BOOKING)
        result = fsm.transition(intent)

        assert result.success is True
        assert result.new_state == BookingState.SERVICE_SELECTION
        assert fsm.state == BookingState.SERVICE_SELECTION

    def test_transition_returns_fsm_result(self):
        """transition returns FSMResult dataclass."""
        fsm = BookingFSM("test-conv")
        intent = Intent(type=IntentType.START_BOOKING)
        result = fsm.transition(intent)

        assert isinstance(result, FSMResult)
        assert result.success is True
        assert result.new_state == BookingState.SERVICE_SELECTION
        assert result.validation_errors == []

    def test_transition_accumulates_data(self):
        """transition accumulates entities into collected_data."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SERVICE_SELECTION
        intent = Intent(
            type=IntentType.CONFIRM_SERVICES,
            entities={"services": ["Corte largo", "Tinte"]},
        )
        result = fsm.transition(intent)

        assert result.success is True
        assert "services" in result.collected_data
        assert "Corte largo" in result.collected_data["services"]
        assert "Tinte" in result.collected_data["services"]

    def test_transition_happy_path_complete(self):
        """Complete happy path from IDLE to BOOKED with auto-reset (Bug #2 fix)."""
        fsm = BookingFSM("test-conv")

        # Step 1: IDLE -> SERVICE_SELECTION
        result = fsm.transition(Intent(type=IntentType.START_BOOKING))
        assert result.success is True
        assert fsm.state == BookingState.SERVICE_SELECTION

        # Step 2: SERVICE_SELECTION -> STYLIST_SELECTION
        result = fsm.transition(
            Intent(
                type=IntentType.CONFIRM_SERVICES,
                entities={"services": ["Corte largo"]},
            )
        )
        assert result.success is True
        assert fsm.state == BookingState.STYLIST_SELECTION

        # Step 3: STYLIST_SELECTION -> SLOT_SELECTION
        result = fsm.transition(
            Intent(
                type=IntentType.SELECT_STYLIST,
                entities={"stylist_id": "stylist-uuid"},
            )
        )
        assert result.success is True
        assert fsm.state == BookingState.SLOT_SELECTION

        # Step 4: SLOT_SELECTION -> CUSTOMER_DATA
        result = fsm.transition(
            Intent(
                type=IntentType.SELECT_SLOT,
                entities={"slot": {"start_time": "2024-12-01T10:00:00", "duration_minutes": 45}},
            )
        )
        assert result.success is True
        assert fsm.state == BookingState.CUSTOMER_DATA

        # Step 5a: CUSTOMER_DATA Phase 1 - provide name (stays in CUSTOMER_DATA)
        result = fsm.transition(
            Intent(
                type=IntentType.PROVIDE_CUSTOMER_DATA,
                entities={"first_name": "María", "last_name": "García"},
            )
        )
        assert result.success is True
        assert fsm.state == BookingState.CUSTOMER_DATA  # Still in CUSTOMER_DATA waiting for notes
        assert fsm.collected_data.get("first_name") == "María"

        # Step 5b: CUSTOMER_DATA Phase 2 - respond to notes question -> CONFIRMATION
        result = fsm.transition(
            Intent(
                type=IntentType.PROVIDE_CUSTOMER_DATA,
                entities={},  # No notes needed, just responding to question
            )
        )
        assert result.success is True
        assert fsm.state == BookingState.CONFIRMATION

        # Step 6: CONFIRMATION -> BOOKED
        # Note: FSM stays in BOOKED state - reset is handled by conversational_agent.py
        # after book() tool executes successfully
        result = fsm.transition(Intent(type=IntentType.CONFIRM_BOOKING))
        assert result.success is True
        assert fsm.state == BookingState.BOOKED
        # collected_data is preserved for book() tool to use
        assert "first_name" in fsm.collected_data

    def test_transition_invalid_returns_failure(self):
        """Invalid transition returns FSMResult with success=False."""
        fsm = BookingFSM("test-conv")
        intent = Intent(type=IntentType.CONFIRM_BOOKING)  # Invalid from IDLE
        result = fsm.transition(intent)

        assert result.success is False
        assert result.new_state == BookingState.IDLE
        assert len(result.validation_errors) > 0
        assert "not allowed" in result.validation_errors[0].lower()

    def test_transition_invalid_missing_data(self):
        """Transition fails with validation errors when data is missing."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SERVICE_SELECTION
        intent = Intent(type=IntentType.CONFIRM_SERVICES)  # No services
        result = fsm.transition(intent)

        assert result.success is False
        assert "services" in result.validation_errors[0].lower()


class TestCancelBooking:
    """Tests for cancel_booking transition (AC #3)."""

    def test_cancel_from_service_selection(self):
        """Cancel from SERVICE_SELECTION resets to IDLE."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SERVICE_SELECTION
        fsm._collected_data = {"services": ["Corte largo"]}

        result = fsm.transition(Intent(type=IntentType.CANCEL_BOOKING))

        assert result.success is True
        assert fsm.state == BookingState.IDLE
        assert fsm.collected_data == {}

    def test_cancel_from_stylist_selection(self):
        """Cancel from STYLIST_SELECTION resets to IDLE."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.STYLIST_SELECTION
        fsm._collected_data = {"services": ["Corte largo"]}

        result = fsm.transition(Intent(type=IntentType.CANCEL_BOOKING))

        assert result.success is True
        assert fsm.state == BookingState.IDLE
        assert fsm.collected_data == {}

    def test_cancel_from_slot_selection(self):
        """Cancel from SLOT_SELECTION resets to IDLE."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SLOT_SELECTION
        fsm._collected_data = {"services": ["Corte"], "stylist_id": "uuid"}

        result = fsm.transition(Intent(type=IntentType.CANCEL_BOOKING))

        assert result.success is True
        assert fsm.state == BookingState.IDLE

    def test_cancel_from_customer_data(self):
        """Cancel from CUSTOMER_DATA resets to IDLE."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.CUSTOMER_DATA
        fsm._collected_data = {"services": ["Corte"], "stylist_id": "uuid", "slot": {}}

        result = fsm.transition(Intent(type=IntentType.CANCEL_BOOKING))

        assert result.success is True
        assert fsm.state == BookingState.IDLE

    def test_cancel_from_confirmation(self):
        """Cancel from CONFIRMATION resets to IDLE."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.CONFIRMATION
        fsm._collected_data = {
            "services": ["Corte"],
            "stylist_id": "uuid",
            "slot": {},
            "first_name": "María",
        }

        result = fsm.transition(Intent(type=IntentType.CANCEL_BOOKING))

        assert result.success is True
        assert fsm.state == BookingState.IDLE

    def test_cancel_from_idle_stays_idle(self):
        """Cancel from IDLE stays in IDLE."""
        fsm = BookingFSM("test-conv")

        result = fsm.transition(Intent(type=IntentType.CANCEL_BOOKING))

        assert result.success is True
        assert fsm.state == BookingState.IDLE


class TestReset:
    """Tests for reset method."""

    def test_reset_clears_state_and_data(self):
        """reset() returns FSM to IDLE with empty data."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.CONFIRMATION
        fsm._collected_data = {"services": ["Corte"], "first_name": "María"}

        fsm.reset()

        assert fsm.state == BookingState.IDLE
        assert fsm.collected_data == {}


class TestLogging:
    """Tests for logging behavior (AC #7)."""

    def test_transition_logs_info_on_success(self, caplog):
        """Successful transition logs INFO."""
        with caplog.at_level(logging.INFO, logger="agent.fsm.booking_fsm"):
            fsm = BookingFSM("test-conv-123")
            fsm.transition(Intent(type=IntentType.START_BOOKING))

        assert len(caplog.records) >= 1
        log_message = caplog.records[-1].message
        assert "test-conv-123" in log_message
        assert "idle" in log_message.lower()
        assert "service_selection" in log_message.lower()
        assert "start_booking" in log_message.lower()

    def test_transition_logs_warning_on_failure(self, caplog):
        """Failed transition logs WARNING."""
        with caplog.at_level(logging.WARNING, logger="agent.fsm.booking_fsm"):
            fsm = BookingFSM("test-conv-123")
            fsm.transition(Intent(type=IntentType.CONFIRM_BOOKING))  # Invalid

        assert len(caplog.records) >= 1
        log_record = caplog.records[-1]
        assert log_record.levelno == logging.WARNING
        assert "test-conv-123" in log_record.message
        assert "rejected" in log_record.message.lower()

    def test_reset_logs_info(self, caplog):
        """reset() logs INFO."""
        with caplog.at_level(logging.INFO, logger="agent.fsm.booking_fsm"):
            fsm = BookingFSM("test-conv-123")
            fsm._state = BookingState.SERVICE_SELECTION
            fsm.reset()

        assert any("reset" in r.message.lower() for r in caplog.records)


class TestServiceAccumulation:
    """Tests for service list accumulation."""

    def test_services_accumulate_not_replace(self):
        """Services accumulate when added incrementally."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SERVICE_SELECTION

        # Add first service
        fsm._merge_entities({"services": ["Corte largo"]})
        assert fsm.collected_data["services"] == ["Corte largo"]

        # Add second service
        fsm._merge_entities({"services": ["Tinte"]})
        assert fsm.collected_data["services"] == ["Corte largo", "Tinte"]

    def test_services_no_duplicates(self):
        """Duplicate services are not added."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SERVICE_SELECTION

        fsm._merge_entities({"services": ["Corte largo"]})
        fsm._merge_entities({"services": ["Corte largo"]})  # Duplicate

        assert fsm.collected_data["services"] == ["Corte largo"]
        assert len(fsm.collected_data["services"]) == 1

    def test_services_filter_empty_strings(self):
        """Empty strings are filtered from services list."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SERVICE_SELECTION

        # Add services including empty strings
        fsm._merge_entities({"services": ["", "Corte Caballero", "", "  "]})

        # Only non-empty services should be added
        assert fsm.collected_data["services"] == ["Corte Caballero"]
        assert len(fsm.collected_data["services"]) == 1

    def test_services_strip_whitespace(self):
        """Service names are trimmed of whitespace."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SERVICE_SELECTION

        fsm._merge_entities({"services": ["  Corte Caballero  ", "\nTinte\t"]})

        assert fsm.collected_data["services"] == ["Corte Caballero", "Tinte"]

    def test_services_filter_mixed_valid_invalid(self):
        """Mixed valid and invalid services are handled correctly."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SERVICE_SELECTION

        # First batch with empty
        fsm._merge_entities({"services": ["", "Corte Caballero"]})
        assert fsm.collected_data["services"] == ["Corte Caballero"]

        # Second batch with whitespace-only
        fsm._merge_entities({"services": ["   ", "Tinte"]})
        assert fsm.collected_data["services"] == ["Corte Caballero", "Tinte"]


class TestServiceDurationCalculation:
    """Tests for service duration calculation from database."""

    @pytest.mark.asyncio
    async def test_calculate_service_durations_empty_services(self):
        """calculate_service_durations handles empty services list."""
        fsm = BookingFSM("test-conv")
        fsm._collected_data = {}

        # Should not raise, just return early
        await fsm.calculate_service_durations()

        # No duration fields should be added
        assert "service_details" not in fsm.collected_data
        assert "total_duration_minutes" not in fsm.collected_data

    @pytest.mark.asyncio
    async def test_calculate_service_durations_with_services(self):
        """calculate_service_durations looks up durations from database."""
        from contextlib import asynccontextmanager

        fsm = BookingFSM("test-conv")
        fsm._collected_data = {"services": ["Corte de Caballero"]}

        # Mock the database session and query
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = ("Corte de Caballero", 40)
        mock_session.execute.return_value = mock_result

        @asynccontextmanager
        async def mock_context_manager():
            yield mock_session

        with patch("database.connection.get_async_session", mock_context_manager):
            await fsm.calculate_service_durations()

        # Should have enriched data
        assert fsm.collected_data.get("total_duration_minutes") == 40
        assert len(fsm.collected_data.get("service_details", [])) == 1
        assert fsm.collected_data["service_details"][0]["name"] == "Corte de Caballero"
        assert fsm.collected_data["service_details"][0]["duration_minutes"] == 40

    @pytest.mark.asyncio
    async def test_calculate_service_durations_multiple_services(self):
        """calculate_service_durations sums durations for multiple services."""
        from contextlib import asynccontextmanager

        fsm = BookingFSM("test-conv")
        fsm._collected_data = {"services": ["Corte de Caballero", "Barba"]}

        # Mock database to return different durations
        call_count = [0]

        async def mock_execute(query):
            mock_result = MagicMock()
            if call_count[0] == 0:
                mock_result.first.return_value = ("Corte de Caballero", 40)
            else:
                mock_result.first.return_value = ("Barba", 20)
            call_count[0] += 1
            return mock_result

        mock_session = AsyncMock()
        mock_session.execute = mock_execute

        @asynccontextmanager
        async def mock_context_manager():
            yield mock_session

        with patch("database.connection.get_async_session", mock_context_manager):
            await fsm.calculate_service_durations()

        # Total should be sum of durations
        assert fsm.collected_data.get("total_duration_minutes") == 60  # 40 + 20

    @pytest.mark.asyncio
    async def test_calculate_service_durations_syncs_slot(self):
        """calculate_service_durations updates slot.duration_minutes."""
        from contextlib import asynccontextmanager

        fsm = BookingFSM("test-conv")
        fsm._collected_data = {
            "services": ["Corte de Caballero"],
            "slot": {"start_time": "2025-11-25T10:00:00", "duration_minutes": 0},
        }

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.first.return_value = ("Corte de Caballero", 40)
        mock_session.execute.return_value = mock_result

        @asynccontextmanager
        async def mock_context_manager():
            yield mock_session

        with patch("database.connection.get_async_session", mock_context_manager):
            await fsm.calculate_service_durations()

        # Slot duration should be synchronized
        assert fsm.collected_data["slot"]["duration_minutes"] == 40
        assert fsm.collected_data.get("total_duration_minutes") == 40


class TestNextAction:
    """Tests for next_action in FSMResult."""

    def test_next_action_after_start_booking(self):
        """next_action is show_services after start_booking."""
        fsm = BookingFSM("test-conv")
        result = fsm.transition(Intent(type=IntentType.START_BOOKING))

        assert result.next_action == "show_services"

    def test_next_action_after_confirm_services(self):
        """next_action is show_stylists after confirm_services."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SERVICE_SELECTION
        result = fsm.transition(
            Intent(
                type=IntentType.CONFIRM_SERVICES,
                entities={"services": ["Corte"]},
            )
        )

        assert result.next_action == "show_stylists"

    def test_next_action_after_cancel(self):
        """next_action is booking_cancelled after cancel."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SERVICE_SELECTION
        result = fsm.transition(Intent(type=IntentType.CANCEL_BOOKING))

        assert result.next_action == "booking_cancelled"


class TestBookedStateAndReset:
    """Tests for BOOKED state behavior and manual reset.

    Note: FSM no longer auto-resets to IDLE after BOOKED transition.
    Reset is now handled by conversational_agent.py after book() succeeds.
    This ensures collected_data is available for the booking tool.
    """

    def test_booked_preserves_state(self):
        """Transition to BOOKED keeps FSM in BOOKED state (data preserved for book())."""
        fsm = BookingFSM("test-conv")
        # Setup: get to CONFIRMATION state with all required data
        fsm._state = BookingState.CONFIRMATION
        fsm._collected_data = {
            "services": ["Corte largo"],
            "stylist_id": "stylist-uuid",
            "slot": {"start_time": "2024-12-01T10:00:00"},
            "first_name": "María",
        }

        # Transition to BOOKED
        result = fsm.transition(Intent(type=IntentType.CONFIRM_BOOKING))

        assert result.success is True
        # FSM should stay in BOOKED (not auto-reset)
        assert fsm.state == BookingState.BOOKED
        # collected_data should be preserved for book() tool
        assert fsm.collected_data["first_name"] == "María"
        assert fsm.collected_data["services"] == ["Corte largo"]

    def test_booked_preserves_collected_data_for_booking_tool(self):
        """BOOKED state preserves all accumulated data for book() tool."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.CONFIRMATION
        fsm._collected_data = {
            "services": ["Corte largo", "Tinte"],
            "stylist_id": "stylist-uuid",
            "slot": {"start_time": "2024-12-01T10:00:00", "duration_minutes": 60},
            "first_name": "María",
            "last_name": "García",
            "notes": "Primera visita",
        }

        fsm.transition(Intent(type=IntentType.CONFIRM_BOOKING))

        # All data preserved for book() tool
        assert fsm.collected_data["services"] == ["Corte largo", "Tinte"]
        assert fsm.collected_data["stylist_id"] == "stylist-uuid"
        assert fsm.collected_data["first_name"] == "María"
        assert fsm.collected_data["notes"] == "Primera visita"

    def test_manual_reset_allows_new_booking(self):
        """After manual reset() from BOOKED, new booking can start immediately."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.CONFIRMATION
        fsm._collected_data = {
            "services": ["Corte"],
            "stylist_id": "uuid",
            "slot": {},
            "first_name": "María",
        }

        # Complete booking (stays in BOOKED)
        fsm.transition(Intent(type=IntentType.CONFIRM_BOOKING))
        assert fsm.state == BookingState.BOOKED

        # Manual reset (called by conversational_agent after successful book())
        fsm.reset()
        assert fsm.state == BookingState.IDLE
        assert fsm.collected_data == {}

        # Start new booking immediately
        result = fsm.transition(Intent(type=IntentType.START_BOOKING))
        assert result.success is True
        assert fsm.state == BookingState.SERVICE_SELECTION

    def test_manual_reset_logs_correctly(self, caplog):
        """Manual reset() logs INFO message."""
        with caplog.at_level(logging.INFO, logger="agent.fsm.booking_fsm"):
            fsm = BookingFSM("test-conv-manual-reset")
            fsm._state = BookingState.BOOKED
            fsm._collected_data = {
                "services": ["Corte"],
                "stylist_id": "uuid",
                "slot": {},
                "first_name": "María",
            }

            fsm.reset()

        # Should log the reset
        log_messages = [r.message for r in caplog.records]
        assert any("reset" in msg.lower() for msg in log_messages)
        assert any("booked" in msg.lower() and "idle" in msg.lower() for msg in log_messages)


class TestValidationErrors:
    """Tests for validation_errors in FSMResult."""

    def test_validation_errors_empty_on_success(self):
        """validation_errors is empty list on successful transition."""
        fsm = BookingFSM("test-conv")
        result = fsm.transition(Intent(type=IntentType.START_BOOKING))

        assert result.validation_errors == []

    def test_validation_errors_contains_missing_field(self):
        """validation_errors mentions missing required field."""
        # Test with SLOT_SELECTION which requires 'slot' field
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SLOT_SELECTION
        result = fsm.transition(Intent(type=IntentType.SELECT_SLOT))

        assert len(result.validation_errors) > 0
        assert "slot" in result.validation_errors[0].lower()

    def test_validation_errors_contains_invalid_transition(self):
        """validation_errors mentions invalid transition."""
        fsm = BookingFSM("test-conv")
        result = fsm.transition(Intent(type=IntentType.CONFIRM_BOOKING))

        assert len(result.validation_errors) > 0
        assert "not allowed" in result.validation_errors[0].lower()


class TestResponseGuidanceRequiredTool:
    """Tests for ResponseGuidance.required_tool_call field."""

    def test_response_guidance_has_required_tool_call_field(self):
        """ResponseGuidance dataclass has required_tool_call field."""
        from agent.fsm.models import ResponseGuidance

        guidance = ResponseGuidance(
            must_show=["lista de servicios"],
            must_ask="¿Qué servicio?",
            forbidden=["estilistas"],
            context_hint="Seleccionando servicios",
            required_tool_call="search_services",
        )

        assert guidance.required_tool_call == "search_services"

    def test_response_guidance_required_tool_call_default_none(self):
        """ResponseGuidance.required_tool_call defaults to None."""
        from agent.fsm.models import ResponseGuidance

        guidance = ResponseGuidance()

        assert guidance.required_tool_call is None

    def test_service_selection_guidance_requires_search_services(self):
        """SERVICE_SELECTION state guidance requires search_services tool."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SERVICE_SELECTION
        # No services collected yet

        guidance = fsm.get_response_guidance()

        assert guidance.required_tool_call == "search_services"

    def test_service_selection_with_services_still_requires_search_services(self):
        """SERVICE_SELECTION with services still requires search_services for adding more."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SERVICE_SELECTION
        fsm._collected_data = {"services": ["Corte de Caballero"]}

        guidance = fsm.get_response_guidance()

        assert guidance.required_tool_call == "search_services"

    def test_service_selection_forbids_premature_confirmation(self):
        """SERVICE_SELECTION without services forbids 'has seleccionado' pattern."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SERVICE_SELECTION
        # No services collected

        guidance = fsm.get_response_guidance()

        assert "has seleccionado" in guidance.forbidden
        assert "servicio seleccionado" in guidance.forbidden

    def test_other_states_no_required_tool(self):
        """Non-SERVICE_SELECTION states don't require specific tools."""
        for state in [
            BookingState.IDLE,
            BookingState.STYLIST_SELECTION,
            BookingState.SLOT_SELECTION,
            BookingState.CUSTOMER_DATA,
            BookingState.CONFIRMATION,
        ]:
            fsm = BookingFSM("test-conv")
            fsm._state = state
            fsm._collected_data = {
                "services": ["Corte"],
                "stylist_id": "uuid",
                "slot": {},
                "first_name": "Test",
            }

            guidance = fsm.get_response_guidance()

            assert guidance.required_tool_call is None, f"State {state} should not require tool"


class TestPrematureServiceConfirmationDetection:
    """Tests for premature service confirmation detection in conversational_agent."""

    def test_detect_premature_confirmation_no_services(self):
        """Detects premature confirmation when no services collected."""
        from agent.nodes.conversational_agent import detect_premature_service_confirmation

        result = detect_premature_service_confirmation(
            response_content="Perfecto, has seleccionado corte de pelo.",
            fsm_state=BookingState.SERVICE_SELECTION,
            collected_services=[],
            search_services_called=False,
        )

        assert result is True

    def test_detect_premature_confirmation_with_search_called(self):
        """Does not detect premature confirmation when search_services was called."""
        from agent.nodes.conversational_agent import detect_premature_service_confirmation

        result = detect_premature_service_confirmation(
            response_content="Has seleccionado Corte de Caballero.",
            fsm_state=BookingState.SERVICE_SELECTION,
            collected_services=[],
            search_services_called=True,  # search_services was called
        )

        assert result is False

    def test_detect_premature_confirmation_with_collected_services(self):
        """Does not detect premature confirmation when services already collected."""
        from agent.nodes.conversational_agent import detect_premature_service_confirmation

        result = detect_premature_service_confirmation(
            response_content="Has seleccionado otro servicio.",
            fsm_state=BookingState.SERVICE_SELECTION,
            collected_services=["Corte de Caballero"],  # Already has services
            search_services_called=False,
        )

        assert result is False

    def test_detect_premature_confirmation_wrong_state(self):
        """Does not detect premature confirmation in other states."""
        from agent.nodes.conversational_agent import detect_premature_service_confirmation

        result = detect_premature_service_confirmation(
            response_content="Has seleccionado el estilista.",
            fsm_state=BookingState.STYLIST_SELECTION,  # Different state
            collected_services=[],
            search_services_called=False,
        )

        assert result is False

    def test_detect_premature_confirmation_various_patterns(self):
        """Detects various premature confirmation patterns."""
        from agent.nodes.conversational_agent import detect_premature_service_confirmation

        patterns = [
            "Has seleccionado corte",
            "Servicio seleccionado: corte",
            "Perfecto, has elegido el corte",
            "Excelente elección, el corte",
            "Seleccionaste corte de pelo",
            "Elegiste el corte",
        ]

        for pattern in patterns:
            result = detect_premature_service_confirmation(
                response_content=pattern,
                fsm_state=BookingState.SERVICE_SELECTION,
                collected_services=[],
                search_services_called=False,
            )
            assert result is True, f"Should detect pattern: {pattern}"

    def test_no_premature_confirmation_for_questions(self):
        """Does not detect premature confirmation for questions."""
        from agent.nodes.conversational_agent import detect_premature_service_confirmation

        result = detect_premature_service_confirmation(
            response_content="¿Qué servicio te gustaría? Tenemos cortes, tintes y más.",
            fsm_state=BookingState.SERVICE_SELECTION,
            collected_services=[],
            search_services_called=False,
        )

        assert result is False


class TestExtractServiceQuery:
    """Tests for _extract_service_query function."""

    def test_extract_service_query_with_keywords(self):
        """Extracts known service keywords from message."""
        from agent.nodes.conversational_agent import _extract_service_query

        query = _extract_service_query("Quiero cortarme el pelo")

        assert "corte" in query.lower() or "cortar" in query.lower() or "pelo" in query.lower()

    def test_extract_service_query_multiple_keywords(self):
        """Extracts multiple keywords and limits to 3."""
        from agent.nodes.conversational_agent import _extract_service_query

        query = _extract_service_query("Quiero corte, tinte y mechas")

        # Should have at most 3 keywords
        words = query.split()
        assert len(words) <= 3

    def test_extract_service_query_no_keywords(self):
        """Falls back to cleaned message when no keywords found."""
        from agent.nodes.conversational_agent import _extract_service_query

        query = _extract_service_query("Quiero algo especial")

        # Should return cleaned text or fallback
        assert len(query) > 0
        assert query != ""

    def test_extract_service_query_empty_message(self):
        """Returns fallback for empty message."""
        from agent.nodes.conversational_agent import _extract_service_query

        query = _extract_service_query("")

        assert query == "servicios"

    def test_extract_service_query_removes_booking_phrases(self):
        """Removes common booking phrases from query."""
        from agent.nodes.conversational_agent import _extract_service_query

        query = _extract_service_query("Quisiera reservar una cita para algo")

        # Should not contain booking phrases
        assert "quisiera" not in query.lower()
        assert "reservar" not in query.lower()
        assert "una cita" not in query.lower()


class TestSlotFreshnessValidation:
    """Tests for slot freshness validation (ADR-008: Obsolete slot cleanup)."""

    @pytest.mark.asyncio
    async def test_load_cleans_slot_with_past_date(self):
        """Load() removes slots with dates in the past."""
        from agent.fsm.booking_fsm import BookingFSM
        from datetime import datetime, timedelta, UTC
        from unittest.mock import AsyncMock, patch

        # Create FSM state with a slot from 1 year ago
        past_date = (datetime.now(UTC) - timedelta(days=365)).isoformat()
        state_data = {
            "state": "slot_selection",
            "collected_data": {
                "services": ["Corte"],
                "stylist_id": "stylist-123",
                "slot": {
                    "start_time": past_date,
                    "duration_minutes": 40,
                },
                "first_name": "Juan",
            },
            "last_updated": datetime.now(UTC).isoformat(),
        }

        # Mock Redis
        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps(state_data)

        with patch("agent.fsm.booking_fsm.get_redis_client", return_value=mock_redis):
            # Load the FSM
            fsm = await BookingFSM.load("conv-obsolete-slot")

            # Slot should be removed (cleaned)
            assert "slot" not in fsm.collected_data
            # State should reset to SLOT_SELECTION (per validation logic)
            assert fsm.state == BookingState.SLOT_SELECTION

    @pytest.mark.asyncio
    async def test_load_cleans_slot_violating_3day_rule(self):
        """Load() removes slots that violate the 3-day minimum rule."""
        from agent.fsm.booking_fsm import BookingFSM
        from datetime import datetime, timedelta, UTC
        from unittest.mock import AsyncMock, patch

        # Create FSM state with a slot only 1 day in the future (violates 3-day rule)
        future_date = (datetime.now(UTC) + timedelta(days=1)).isoformat()
        state_data = {
            "state": "confirmation",
            "collected_data": {
                "services": ["Corte"],
                "stylist_id": "stylist-123",
                "slot": {
                    "start_time": future_date,
                    "duration_minutes": 40,
                },
                "first_name": "Juan",
            },
            "last_updated": datetime.now(UTC).isoformat(),
        }

        # Mock Redis
        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps(state_data)

        with patch("agent.fsm.booking_fsm.get_redis_client", return_value=mock_redis):
            # Load the FSM
            fsm = await BookingFSM.load("conv-3day-violation")

            # Slot should be removed (cleaned)
            assert "slot" not in fsm.collected_data
            # State should reset to SLOT_SELECTION
            assert fsm.state == BookingState.SLOT_SELECTION

    @pytest.mark.asyncio
    async def test_load_preserves_valid_slot(self):
        """Load() preserves slots with valid future dates (>= 3 days)."""
        from agent.fsm.booking_fsm import BookingFSM
        from datetime import datetime, timedelta, UTC
        from unittest.mock import AsyncMock, patch

        # Create FSM state with a slot 5 days in the future (valid)
        future_date = (datetime.now(UTC) + timedelta(days=5)).isoformat()
        state_data = {
            "state": "confirmation",
            "collected_data": {
                "services": ["Corte"],
                "stylist_id": "stylist-123",
                "slot": {
                    "start_time": future_date,
                    "duration_minutes": 40,
                },
                "first_name": "Juan",
            },
            "last_updated": datetime.now(UTC).isoformat(),
        }

        # Mock Redis
        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps(state_data)

        with patch("agent.fsm.booking_fsm.get_redis_client", return_value=mock_redis):
            # Load the FSM
            fsm = await BookingFSM.load("conv-valid-slot")

            # Slot should be preserved (NOT cleaned)
            assert "slot" in fsm.collected_data
            assert fsm.collected_data["slot"]["start_time"] == future_date
            # State should remain as confirmation (not reset)
            assert fsm.state == BookingState.CONFIRMATION

    @pytest.mark.asyncio
    async def test_load_preserves_state_if_no_slot(self):
        """Load() preserves FSM state when there's no slot to validate."""
        from agent.fsm.booking_fsm import BookingFSM
        from datetime import datetime, UTC
        from unittest.mock import AsyncMock, patch

        # Create FSM state without a slot (normal case)
        state_data = {
            "state": "customer_data",
            "collected_data": {
                "services": ["Corte"],
                "stylist_id": "stylist-123",
                "first_name": "Juan",
            },
            "last_updated": datetime.now(UTC).isoformat(),
        }

        # Mock Redis
        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps(state_data)

        with patch("agent.fsm.booking_fsm.get_redis_client", return_value=mock_redis):
            # Load the FSM
            fsm = await BookingFSM.load("conv-no-slot")

            # State should be preserved
            assert fsm.state == BookingState.CUSTOMER_DATA
            # Collected data unchanged
            assert fsm.collected_data["services"] == ["Corte"]

    @pytest.mark.asyncio
    async def test_load_handles_malformed_slot(self):
        """Load() cleans up malformed slots (missing start_time)."""
        from agent.fsm.booking_fsm import BookingFSM
        from datetime import datetime, UTC
        from unittest.mock import AsyncMock, patch

        # Create FSM state with a malformed slot
        state_data = {
            "state": "confirmation",
            "collected_data": {
                "services": ["Corte"],
                "stylist_id": "stylist-123",
                "slot": {
                    # Missing start_time!
                    "duration_minutes": 40,
                },
                "first_name": "Juan",
            },
            "last_updated": datetime.now(UTC).isoformat(),
        }

        # Mock Redis
        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps(state_data)

        with patch("agent.fsm.booking_fsm.get_redis_client", return_value=mock_redis):
            # Load the FSM
            fsm = await BookingFSM.load("conv-malformed-slot")

            # Slot should be removed (malformed)
            assert "slot" not in fsm.collected_data


class TestFSMSerialization:
    """Tests for FSM serialization (ADR-011: to_dict/from_dict for checkpoint storage)."""

    def test_to_dict_empty_fsm(self):
        """to_dict() serializes empty IDLE FSM correctly."""
        fsm = BookingFSM("conv-123")
        result = fsm.to_dict()

        assert result["state"] == "idle"
        assert result["collected_data"] == {}
        assert isinstance(result["last_updated"], str)
        # Verify ISO format datetime
        datetime.fromisoformat(result["last_updated"])

    def test_to_dict_with_collected_data(self):
        """to_dict() serializes FSM with collected data."""
        fsm = BookingFSM("conv-123")
        fsm._state = BookingState.CUSTOMER_DATA
        fsm._collected_data = {
            "services": ["Corte Largo", "Tinte"],
            "stylist_id": "stylist-001",
            "first_name": "Juan",
            "notes": "Alergia a tintes",
        }

        result = fsm.to_dict()

        assert result["state"] == "customer_data"
        assert result["collected_data"]["services"] == ["Corte Largo", "Tinte"]
        assert result["collected_data"]["stylist_id"] == "stylist-001"
        assert result["collected_data"]["first_name"] == "Juan"
        assert result["collected_data"]["notes"] == "Alergia a tintes"

    def test_to_dict_with_slot_data(self):
        """to_dict() serializes slot with datetime correctly."""
        from datetime import UTC

        fsm = BookingFSM("conv-123")
        fsm._state = BookingState.CONFIRMATION
        now = datetime.now(UTC)
        fsm._collected_data = {
            "services": ["Corte"],
            "stylist_id": "stylist-001",
            "slot": {
                "start_time": now.isoformat(),
                "duration_minutes": 40,
            },
            "first_name": "Juan",
        }

        result = fsm.to_dict()

        assert result["state"] == "confirmation"
        assert result["collected_data"]["slot"]["start_time"] == now.isoformat()
        assert result["collected_data"]["slot"]["duration_minutes"] == 40

    def test_to_dict_is_json_serializable(self):
        """to_dict() output is JSON serializable."""
        fsm = BookingFSM("conv-123")
        fsm._state = BookingState.SLOT_SELECTION
        fsm._collected_data = {
            "services": ["Corte"],
            "stylist_id": "stylist-001",
        }

        result = fsm.to_dict()
        json_str = json.dumps(result)
        parsed = json.loads(json_str)

        assert parsed["state"] == "slot_selection"
        assert "services" in parsed["collected_data"]

    def test_from_dict_empty_data(self):
        """from_dict() handles empty data gracefully."""
        fsm = BookingFSM.from_dict("conv-123", {})

        assert fsm.state == BookingState.IDLE
        assert fsm.collected_data == {}
        assert fsm.conversation_id == "conv-123"

    def test_from_dict_none_data(self):
        """from_dict() handles None data gracefully."""
        fsm = BookingFSM.from_dict("conv-123", None)

        assert fsm.state == BookingState.IDLE
        assert fsm.collected_data == {}

    def test_from_dict_valid_state(self):
        """from_dict() deserializes valid state correctly."""
        data = {
            "state": "customer_data",
            "collected_data": {
                "services": ["Corte"],
                "first_name": "Juan",
            },
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        fsm = BookingFSM.from_dict("conv-123", data)

        assert fsm.state == BookingState.CUSTOMER_DATA
        assert fsm.collected_data["services"] == ["Corte"]
        assert fsm.collected_data["first_name"] == "Juan"

    def test_from_dict_invalid_state_fallback(self):
        """from_dict() falls back to IDLE on invalid state."""
        data = {
            "state": "invalid_state_name",
            "collected_data": {},
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        fsm = BookingFSM.from_dict("conv-123", data)

        assert fsm.state == BookingState.IDLE

    def test_from_dict_round_trip(self):
        """to_dict() -> from_dict() round trip preserves FSM state."""
        # Create FSM with complex data
        fsm1 = BookingFSM("conv-123")
        fsm1._state = BookingState.SLOT_SELECTION
        fsm1._collected_data = {
            "services": ["Corte Largo", "Tinte"],
            "stylist_id": "stylist-001",
            "first_name": "Juan",
            "last_name": "García",
        }

        # Serialize and deserialize
        data = fsm1.to_dict()
        fsm2 = BookingFSM.from_dict("conv-123", data)

        # Verify state preserved
        assert fsm2.state == fsm1.state
        assert fsm2.collected_data == fsm1.collected_data
        assert fsm2.conversation_id == fsm1.conversation_id

    def test_from_dict_malformed_last_updated(self):
        """from_dict() handles malformed last_updated gracefully."""
        data = {
            "state": "service_selection",
            "collected_data": {"services": ["Corte"]},
            "last_updated": "not-a-valid-datetime",
        }

        fsm = BookingFSM.from_dict("conv-123", data)

        # Should still load the data
        assert fsm.state == BookingState.SERVICE_SELECTION
        assert fsm.collected_data["services"] == ["Corte"]
        # last_updated should be updated to current time
        assert fsm._last_updated is not None

    def test_from_dict_validates_slot_freshness(self):
        """from_dict() validates slot freshness (ADR-008)."""
        from datetime import UTC, timedelta

        # Create slot with past date
        past_date = datetime.now(UTC) - timedelta(days=5)
        data = {
            "state": "confirmation",
            "collected_data": {
                "services": ["Corte"],
                "stylist_id": "stylist-001",
                "slot": {
                    "start_time": past_date.isoformat(),
                    "duration_minutes": 40,
                },
                "first_name": "Juan",
            },
            "last_updated": datetime.now(UTC).isoformat(),
        }

        fsm = BookingFSM.from_dict("conv-123", data)

        # Slot should be removed as it's in the past
        assert "slot" not in fsm.collected_data
        # State should be reset to SLOT_SELECTION
        assert fsm.state == BookingState.SLOT_SELECTION

    def test_from_dict_missing_collected_data(self):
        """from_dict() handles missing collected_data field."""
        data = {
            "state": "service_selection",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            # missing collected_data
        }

        fsm = BookingFSM.from_dict("conv-123", data)

        assert fsm.state == BookingState.SERVICE_SELECTION
        assert fsm.collected_data == {}

    def test_from_dict_invalid_collected_data_type(self):
        """from_dict() handles non-dict collected_data."""
        data = {
            "state": "service_selection",
            "collected_data": "not-a-dict",  # Invalid!
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        fsm = BookingFSM.from_dict("conv-123", data)

        assert fsm.state == BookingState.SERVICE_SELECTION
        assert fsm.collected_data == {}  # Should fallback to empty dict


class TestSlotStructuralValidation:
    """
    Tests for slot structural validation in FSM.

    These tests verify that _validate_slot_structure() correctly validates
    slot format before allowing FSM to advance to CUSTOMER_DATA state.
    """

    def test_valid_slot_structure(self):
        """Valid slot with start_time and duration passes validation."""
        fsm = BookingFSM("test-conv")
        slot = {
            "start_time": "2025-12-09T10:00:00+01:00",
            "duration_minutes": 60
        }

        is_valid, errors = fsm._validate_slot_structure(slot)

        assert is_valid is True
        assert errors == []

    def test_slot_missing_start_time(self):
        """Slot without start_time fails validation."""
        fsm = BookingFSM("test-conv")
        slot = {"duration_minutes": 60}

        is_valid, errors = fsm._validate_slot_structure(slot)

        assert is_valid is False
        assert len(errors) == 1
        assert "missing start_time" in errors[0]

    def test_slot_invalid_iso_format(self):
        """Slot with invalid ISO 8601 format fails validation."""
        fsm = BookingFSM("test-conv")
        slot = {
            "start_time": "not-a-valid-datetime",
            "duration_minutes": 60
        }

        is_valid, errors = fsm._validate_slot_structure(slot)

        assert is_valid is False
        assert len(errors) == 1
        assert "Invalid ISO 8601" in errors[0]

    def test_slot_date_only_no_time(self):
        """Slot with date but no specific time (00:00:00) fails validation."""
        fsm = BookingFSM("test-conv")
        slot = {
            "start_time": "2025-12-09T00:00:00+01:00",  # Midnight = no time specified
            "duration_minutes": 60
        }

        is_valid, errors = fsm._validate_slot_structure(slot)

        assert is_valid is False
        assert "no specific time" in errors[0]

    def test_slot_zero_duration_allowed_as_placeholder(self):
        """Slot with zero duration is allowed as placeholder (FSM will sync duration later)."""
        fsm = BookingFSM("test-conv")
        slot = {
            "start_time": "2025-12-09T10:00:00+01:00",
            "duration_minutes": 0  # Placeholder - FSM syncs via calculate_service_durations()
        }

        is_valid, errors = fsm._validate_slot_structure(slot)

        assert is_valid is True
        assert errors == []

    def test_slot_negative_duration(self):
        """Slot with negative duration fails validation."""
        fsm = BookingFSM("test-conv")
        slot = {
            "start_time": "2025-12-09T10:00:00+01:00",
            "duration_minutes": -30
        }

        is_valid, errors = fsm._validate_slot_structure(slot)

        assert is_valid is False
        assert "Invalid duration_minutes" in errors[0]

    def test_slot_non_integer_duration(self):
        """Slot with non-integer duration fails validation."""
        fsm = BookingFSM("test-conv")
        slot = {
            "start_time": "2025-12-09T10:00:00+01:00",
            "duration_minutes": "60"  # String instead of int
        }

        is_valid, errors = fsm._validate_slot_structure(slot)

        assert is_valid is False
        assert "Invalid duration_minutes" in errors[0]


class TestSlotValidationInTransition:
    """
    Tests for slot validation integrated into FSM transition() method.

    These tests verify that FSM rejects SELECT_SLOT transitions with invalid slots,
    preventing bad data from advancing to CUSTOMER_DATA state.
    """

    def test_valid_slot_allows_transition(self):
        """FSM accepts SELECT_SLOT with valid slot structure."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SLOT_SELECTION
        fsm._collected_data = {
            "services": ["Corte"],
            "stylist_id": "stylist-uuid"
        }

        intent = Intent(
            type=IntentType.SELECT_SLOT,
            entities={
                "slot": {
                    "start_time": "2025-12-09T10:00:00+01:00",
                    "duration_minutes": 60
                }
            }
        )

        result = fsm.transition(intent)

        assert result.success is True
        assert result.new_state == BookingState.CUSTOMER_DATA
        assert result.validation_errors == []

    def test_malformed_slot_rejects_transition(self):
        """FSM rejects SELECT_SLOT with malformed slot (missing start_time)."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SLOT_SELECTION
        fsm._collected_data = {
            "services": ["Corte"],
            "stylist_id": "stylist-uuid"
        }

        intent = Intent(
            type=IntentType.SELECT_SLOT,
            entities={
                "slot": {
                    "duration_minutes": 60
                    # Missing start_time!
                }
            }
        )

        result = fsm.transition(intent)

        assert result.success is False
        assert result.new_state == BookingState.SLOT_SELECTION  # Stays in same state
        assert len(result.validation_errors) > 0
        assert "missing start_time" in result.validation_errors[0]

    def test_date_only_slot_rejects_transition(self):
        """FSM rejects SELECT_SLOT with date-only timestamp (00:00:00)."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SLOT_SELECTION
        fsm._collected_data = {
            "services": ["Corte"],
            "stylist_id": "stylist-uuid"
        }

        intent = Intent(
            type=IntentType.SELECT_SLOT,
            entities={
                "slot": {
                    "start_time": "2025-12-07T00:00:00+01:00",  # Date only, no time
                    "duration_minutes": 60
                }
            }
        )

        result = fsm.transition(intent)

        assert result.success is False
        assert result.new_state == BookingState.SLOT_SELECTION
        assert "no specific time" in result.validation_errors[0]

    def test_zero_duration_placeholder_accepts_transition(self):
        """FSM accepts SELECT_SLOT with duration:0 (placeholder for later sync)."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.SLOT_SELECTION
        fsm._collected_data = {
            "services": ["Corte"],
            "stylist_id": "stylist-uuid"
        }

        intent = Intent(
            type=IntentType.SELECT_SLOT,
            entities={
                "slot": {
                    "start_time": "2025-12-09T10:00:00+01:00",
                    "duration_minutes": 0  # Placeholder - FSM syncs via calculate_service_durations()
                }
            }
        )

        result = fsm.transition(intent)

        assert result.success is True
        assert result.new_state == BookingState.CUSTOMER_DATA
        assert result.validation_errors == []


class TestSlotSelectionSubPhases:
    """
    Tests for SLOT_SELECTION sub-phases with date_preference_requested flag.

    Validates that SLOT_SELECTION has two sub-phases:
    1. Ask for date preference (date_preference_requested=False)
    2. Show available slots (date_preference_requested=True)
    """

    def test_slot_selection_sub_phase_1_asks_for_date(self):
        """
        Test sub-phase 1: When entering SLOT_SELECTION without date preference,
        guidance should ask for date without showing slots.
        """
        fsm = BookingFSM(conversation_id="test-conv")

        # Transition to SLOT_SELECTION from STYLIST_SELECTION
        fsm._state = BookingState.STYLIST_SELECTION
        fsm._collected_data["services"] = ["Corte + Peinado (Corto-Medio)"]
        fsm._collected_data["stylist_id"] = "stylist-123"

        intent = Intent(
            type=IntentType.SELECT_STYLIST,
            entities={"stylist_id": "stylist-123"}
        )

        result = fsm.transition(intent)

        # Verify transition succeeded
        assert result.success is True
        assert result.new_state == BookingState.SLOT_SELECTION

        # Verify flag was reset
        assert fsm.collected_data.get("date_preference_requested") is False

        # Verify guidance for sub-phase 1
        guidance = fsm.get_response_guidance()
        assert guidance.must_show == []
        assert "día" in guidance.must_ask.lower()
        assert "horarios" in guidance.forbidden

    def test_slot_selection_sub_phase_2_shows_slots(self):
        """
        Test sub-phase 2: After date preference is given (flag=True),
        guidance should show available slots.
        """
        fsm = BookingFSM(conversation_id="test-conv")

        # Setup SLOT_SELECTION state with date preference requested
        fsm._state = BookingState.SLOT_SELECTION
        fsm._collected_data["services"] = ["Corte + Peinado (Corto-Medio)"]
        fsm._collected_data["stylist_id"] = "stylist-123"
        fsm._collected_data["date_preference_requested"] = True

        # Verify guidance for sub-phase 2
        guidance = fsm.get_response_guidance()
        assert "horarios disponibles" in guidance.must_show
        assert "horario" in guidance.must_ask.lower()
        assert "confirmación de cita" in guidance.forbidden

    def test_flag_resets_on_entry_from_stylist_selection(self):
        """
        Test that date_preference_requested flag resets when entering
        SLOT_SELECTION from STYLIST_SELECTION.
        """
        fsm = BookingFSM(conversation_id="test-conv")

        # Start in STYLIST_SELECTION
        fsm._state = BookingState.STYLIST_SELECTION
        fsm._collected_data["services"] = ["Corte de Caballero"]

        # Manually set flag to True (simulating previous booking attempt)
        fsm._collected_data["date_preference_requested"] = True

        # Transition to SLOT_SELECTION
        intent = Intent(
            type=IntentType.SELECT_STYLIST,
            entities={"stylist_id": "stylist-456"}
        )

        result = fsm.transition(intent)

        # Verify flag was reset
        assert result.success is True
        assert fsm.collected_data.get("date_preference_requested") is False

    def test_flag_set_on_check_availability_self_loop(self):
        """
        Test that date_preference_requested flag is set to True when
        CHECK_AVAILABILITY intent occurs in SLOT_SELECTION (self-loop).
        """
        fsm = BookingFSM(conversation_id="test-conv")

        # Setup SLOT_SELECTION state
        fsm._state = BookingState.SLOT_SELECTION
        fsm._collected_data["services"] = ["Corte de Caballero"]
        fsm._collected_data["stylist_id"] = "stylist-789"
        fsm._collected_data["date_preference_requested"] = False

        # Transition with CHECK_AVAILABILITY (self-loop)
        intent = Intent(
            type=IntentType.CHECK_AVAILABILITY,
            entities={"date": "2025-12-01"}
        )

        result = fsm.transition(intent)

        # Verify self-loop occurred
        assert result.success is True
        assert result.new_state == BookingState.SLOT_SELECTION

        # Verify flag was set
        assert fsm.collected_data.get("date_preference_requested") is True
