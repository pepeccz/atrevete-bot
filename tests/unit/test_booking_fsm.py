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
        """Complete happy path from IDLE to BOOKED."""
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

        # Step 5: CUSTOMER_DATA -> CONFIRMATION
        result = fsm.transition(
            Intent(
                type=IntentType.PROVIDE_CUSTOMER_DATA,
                entities={"first_name": "María", "last_name": "García"},
            )
        )
        assert result.success is True
        assert fsm.state == BookingState.CONFIRMATION

        # Step 6: CONFIRMATION -> BOOKED
        result = fsm.transition(Intent(type=IntentType.CONFIRM_BOOKING))
        assert result.success is True
        assert fsm.state == BookingState.BOOKED

        # Verify all data accumulated
        assert fsm.collected_data["services"] == ["Corte largo"]
        assert fsm.collected_data["stylist_id"] == "stylist-uuid"
        assert fsm.collected_data["first_name"] == "María"
        assert fsm.collected_data["last_name"] == "García"

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


class TestPersistence:
    """Tests for persist() and load() methods (AC #4, #5, #6)."""

    @pytest.mark.asyncio
    async def test_persist_saves_to_redis(self):
        """persist() saves state to Redis with correct key."""
        mock_redis = AsyncMock()
        with patch("agent.fsm.booking_fsm.get_redis_client", return_value=mock_redis):
            fsm = BookingFSM("test-conv-123")
            fsm._state = BookingState.SERVICE_SELECTION
            fsm._collected_data = {"services": ["Corte largo"]}

            await fsm.persist()

            mock_redis.set.assert_called_once()
            call_args = mock_redis.set.call_args
            key = call_args[0][0]
            data = json.loads(call_args[0][1])
            ttl = call_args[1]["ex"]

            assert key == "fsm:test-conv-123"
            assert data["state"] == "service_selection"
            assert data["collected_data"] == {"services": ["Corte largo"]}
            assert ttl == 900  # 15 minutes

    @pytest.mark.asyncio
    async def test_persist_uses_900_second_ttl(self):
        """persist() sets TTL to 900 seconds (AC #4)."""
        mock_redis = AsyncMock()
        with patch("agent.fsm.booking_fsm.get_redis_client", return_value=mock_redis):
            fsm = BookingFSM("test-conv")
            await fsm.persist()

            call_args = mock_redis.set.call_args
            assert call_args[1]["ex"] == 900

    @pytest.mark.asyncio
    async def test_load_restores_state(self):
        """load() restores state from Redis (AC #5)."""
        stored_data = {
            "state": "stylist_selection",
            "collected_data": {"services": ["Corte largo", "Tinte"]},
            "last_updated": datetime.now(timezone.utc).isoformat(),
        }

        mock_redis = AsyncMock()
        mock_redis.get.return_value = json.dumps(stored_data)

        with patch("agent.fsm.booking_fsm.get_redis_client", return_value=mock_redis):
            fsm = await BookingFSM.load("test-conv-123")

            assert fsm.state == BookingState.STYLIST_SELECTION
            assert fsm.collected_data == {"services": ["Corte largo", "Tinte"]}
            assert fsm.conversation_id == "test-conv-123"

    @pytest.mark.asyncio
    async def test_load_creates_new_if_not_found(self):
        """load() creates new FSM in IDLE if key doesn't exist (AC #6)."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = None

        with patch("agent.fsm.booking_fsm.get_redis_client", return_value=mock_redis):
            fsm = await BookingFSM.load("new-conv-123")

            assert fsm.state == BookingState.IDLE
            assert fsm.collected_data == {}
            assert fsm.conversation_id == "new-conv-123"

    @pytest.mark.asyncio
    async def test_load_handles_corrupted_data(self):
        """load() creates new FSM if stored data is corrupted."""
        mock_redis = AsyncMock()
        mock_redis.get.return_value = "invalid json {"

        with patch("agent.fsm.booking_fsm.get_redis_client", return_value=mock_redis):
            fsm = await BookingFSM.load("test-conv")

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


class TestValidationErrors:
    """Tests for validation_errors in FSMResult."""

    def test_validation_errors_empty_on_success(self):
        """validation_errors is empty list on successful transition."""
        fsm = BookingFSM("test-conv")
        result = fsm.transition(Intent(type=IntentType.START_BOOKING))

        assert result.validation_errors == []

    def test_validation_errors_contains_missing_field(self):
        """validation_errors mentions missing required field."""
        fsm = BookingFSM("test-conv")
        fsm._state = BookingState.CUSTOMER_DATA
        result = fsm.transition(Intent(type=IntentType.PROVIDE_CUSTOMER_DATA))

        assert len(result.validation_errors) > 0
        assert "first_name" in result.validation_errors[0].lower()

    def test_validation_errors_contains_invalid_transition(self):
        """validation_errors mentions invalid transition."""
        fsm = BookingFSM("test-conv")
        result = fsm.transition(Intent(type=IntentType.CONFIRM_BOOKING))

        assert len(result.validation_errors) > 0
        assert "not allowed" in result.validation_errors[0].lower()
