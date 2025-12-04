"""
Edge Case Tests: Duration Enrichment and Placeholder Handling.

Tests the transition from duration:0 placeholder to real duration values.
This validates the fix for the temporal coupling bug where FSM would accept
slots with duration:0 and later calculate the real duration.

Test Scenarios:
1. Single service: duration:0 → duration:60 (calculated from DB)
2. Multiple services: duration:0 → duration:150 (sum of all services)
3. Service not found: duration:0 → duration:60 (default fallback)
4. Duration calculation timing: when is it triggered?

This suite ensures Phase 3 (Temporal Coupling Elimination) won't break existing behavior.
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from agent.fsm import BookingFSM, BookingState, Intent, IntentType

MADRID_TZ = ZoneInfo("Europe/Madrid")


@pytest.fixture
def conversation_id() -> str:
    """Generate unique conversation ID."""
    return f"test-duration-{uuid4()}"


@pytest.fixture
def fsm(conversation_id: str) -> BookingFSM:
    """Create FSM instance."""
    return BookingFSM(conversation_id)


@pytest.fixture
def valid_slot_zero_duration() -> dict:
    """Slot with duration:0 placeholder."""
    future = datetime.now(MADRID_TZ) + timedelta(days=5)
    # Skip weekends
    while future.weekday() in [5, 6]:
        future += timedelta(days=1)

    return {
        "start_time": future.replace(hour=14, minute=0).isoformat(),
        "duration_minutes": 0,  # Placeholder
    }


class TestDurationPlaceholderAcceptance:
    """Test that FSM currently accepts duration:0 as placeholder."""

    @pytest.mark.asyncio
    async def test_fsm_accepts_duration_zero_placeholder(
        self,
        fsm: BookingFSM,
        valid_slot_zero_duration: dict,
    ):
        """
        Test that FSM accepts slots with duration:0.

        This is the CURRENT behavior (Phase 1 fix).
        Phase 3 will eliminate this by calculating duration BEFORE transition.

        Validates:
        - FSM structural validation allows duration:0
        - FSM does NOT reject the slot for missing duration
        """
        # Navigate to SLOT_SELECTION
        await fsm.transition(Intent(type=IntentType.START_BOOKING, entities={}))
        await fsm.transition(Intent(type=IntentType.SELECT_SERVICE, entities={"services": ["Corte"]}))
        await fsm.transition(Intent(type=IntentType.CONFIRM_SERVICES, entities={}))
        await fsm.transition(Intent(type=IntentType.SELECT_STYLIST, entities={"stylist_id": str(uuid4())}))

        assert fsm.state == BookingState.SLOT_SELECTION

        # Mock SlotValidator to pass (structural validation allows duration:0)
        with patch("agent.fsm.booking_fsm.SlotValidator") as mock_validator:
            mock_validation = MagicMock()
            mock_validation.valid = True
            mock_validator.validate_complete = AsyncMock(return_value=mock_validation)

            # Attempt to select slot with duration:0
            result = await fsm.transition(
                Intent(
                    type=IntentType.SELECT_SLOT,
                    entities={"slot": valid_slot_zero_duration}
                )
            )

        # Verify acceptance (current behavior)
        assert result.success is True
        assert fsm.state == BookingState.CUSTOMER_DATA
        assert fsm.collected_data["slot"]["duration_minutes"] == 0


class TestDurationCalculationTiming:
    """Test when duration is calculated from database."""

    @pytest.mark.asyncio
    async def test_duration_calculated_on_slot_selection(
        self,
        fsm: BookingFSM,
        valid_slot_zero_duration: dict,
    ):
        """
        Test that duration is calculated after SELECT_SLOT transition.

        Current behavior:
        - SELECT_SLOT accepts duration:0
        - conversational_agent calls calculate_service_durations()
        - slot.duration_minutes is updated with real value

        This test documents the CURRENT timing for Phase 3 comparison.
        """
        # Navigate to SLOT_SELECTION with services
        await fsm.transition(Intent(type=IntentType.START_BOOKING, entities={}))
        await fsm.transition(Intent(type=IntentType.SELECT_SERVICE, entities={"services": ["Corte de Caballero"]}))
        await fsm.transition(Intent(type=IntentType.CONFIRM_SERVICES, entities={}))
        await fsm.transition(Intent(type=IntentType.SELECT_STYLIST, entities={"stylist_id": str(uuid4())}))

        # Mock SlotValidator
        with patch("agent.fsm.booking_fsm.SlotValidator") as mock_validator:
            mock_validation = MagicMock()
            mock_validation.valid = True
            mock_validator.validate_complete = AsyncMock(return_value=mock_validation)

            # Select slot with duration:0
            await fsm.transition(
                Intent(
                    type=IntentType.SELECT_SLOT,
                    entities={"slot": valid_slot_zero_duration}
                )
            )

        # At this point, slot.duration_minutes is still 0
        assert fsm.collected_data["slot"]["duration_minutes"] == 0

        # Mock database service lookup
        with patch("agent.fsm.booking_fsm.get_async_session") as mock_session_ctx:
            mock_session = MagicMock()
            mock_service = MagicMock()
            mock_service.name = "Corte de Caballero"
            mock_service.duration_minutes = 60

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = mock_service
            mock_session.execute = AsyncMock(return_value=mock_result)

            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            # Mock service resolver to return valid UUID
            with patch("agent.fsm.booking_fsm.resolve_single_service") as mock_resolver:
                mock_resolver.return_value = uuid4()

                # Call calculate_service_durations (normally called by conversational_agent)
                await fsm.calculate_service_durations()

        # After calculation, duration should be updated
        assert "total_duration_minutes" in fsm.collected_data
        assert fsm.collected_data["total_duration_minutes"] == 60
        assert fsm.collected_data["slot"]["duration_minutes"] == 60


class TestMultipleServicesDurationSum:
    """Test that multiple services sum durations correctly."""

    @pytest.mark.asyncio
    async def test_multiple_services_duration_summed(
        self,
        fsm: BookingFSM,
        valid_slot_zero_duration: dict,
    ):
        """
        Test that selecting multiple services sums their durations.

        Services:
        - Corte de Caballero: 60 min
        - Barba: 30 min
        Total: 90 min

        Validates:
        - calculate_service_durations() sums all services
        - slot.duration_minutes is synchronized to total
        """
        # Navigate to SLOT_SELECTION with multiple services
        await fsm.transition(Intent(type=IntentType.START_BOOKING, entities={}))
        await fsm.transition(Intent(type=IntentType.SELECT_SERVICE, entities={"services": ["Corte de Caballero"]}))
        await fsm.transition(Intent(type=IntentType.SELECT_SERVICE, entities={"services": ["Barba"]}))
        await fsm.transition(Intent(type=IntentType.CONFIRM_SERVICES, entities={}))
        await fsm.transition(Intent(type=IntentType.SELECT_STYLIST, entities={"stylist_id": str(uuid4())}))

        # Mock SlotValidator
        with patch("agent.fsm.booking_fsm.SlotValidator") as mock_validator:
            mock_validation = MagicMock()
            mock_validation.valid = True
            mock_validator.validate_complete = AsyncMock(return_value=mock_validation)

            await fsm.transition(
                Intent(
                    type=IntentType.SELECT_SLOT,
                    entities={"slot": valid_slot_zero_duration}
                )
            )

        # Mock database service lookups
        with patch("agent.fsm.booking_fsm.get_async_session") as mock_session_ctx:
            mock_session = MagicMock()

            # Mock service 1: Corte de Caballero (60 min)
            mock_service1 = MagicMock()
            mock_service1.name = "Corte de Caballero"
            mock_service1.duration_minutes = 60

            # Mock service 2: Barba (30 min)
            mock_service2 = MagicMock()
            mock_service2.name = "Barba"
            mock_service2.duration_minutes = 30

            # Configure mock to return different services for each query
            call_count = [0]

            async def mock_execute(*args, **kwargs):
                result = MagicMock()
                if call_count[0] == 0:
                    result.scalar_one_or_none.return_value = mock_service1
                else:
                    result.scalar_one_or_none.return_value = mock_service2
                call_count[0] += 1
                return result

            mock_session.execute = mock_execute
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            # Mock service resolver
            with patch("agent.fsm.booking_fsm.resolve_single_service") as mock_resolver:
                mock_resolver.side_effect = [uuid4(), uuid4()]

                # Calculate durations
                await fsm.calculate_service_durations()

        # Verify total duration
        assert "total_duration_minutes" in fsm.collected_data
        assert fsm.collected_data["total_duration_minutes"] == 90  # 60 + 30
        assert fsm.collected_data["slot"]["duration_minutes"] == 90


class TestServiceNotFoundFallback:
    """Test fallback behavior when service is not found in database."""

    @pytest.mark.asyncio
    async def test_service_not_found_uses_default_duration(
        self,
        fsm: BookingFSM,
        valid_slot_zero_duration: dict,
    ):
        """
        Test that unknown services default to 60 min.

        This ensures graceful degradation if service name doesn't match DB.

        Validates:
        - calculate_service_durations() handles missing services
        - Default duration of 60 min is used
        - System doesn't crash on unknown service
        """
        # Navigate to SLOT_SELECTION
        await fsm.transition(Intent(type=IntentType.START_BOOKING, entities={}))
        await fsm.transition(Intent(type=IntentType.SELECT_SERVICE, entities={"services": ["Unknown Service"]}))
        await fsm.transition(Intent(type=IntentType.CONFIRM_SERVICES, entities={}))
        await fsm.transition(Intent(type=IntentType.SELECT_STYLIST, entities={"stylist_id": str(uuid4())}))

        # Mock SlotValidator
        with patch("agent.fsm.booking_fsm.SlotValidator") as mock_validator:
            mock_validation = MagicMock()
            mock_validation.valid = True
            mock_validator.validate_complete = AsyncMock(return_value=mock_validation)

            await fsm.transition(
                Intent(
                    type=IntentType.SELECT_SLOT,
                    entities={"slot": valid_slot_zero_duration}
                )
            )

        # Mock service resolver to raise ValueError (not found)
        with patch("agent.fsm.booking_fsm.resolve_single_service") as mock_resolver:
            mock_resolver.side_effect = ValueError("Service not found")

            # Calculate durations (should not crash)
            await fsm.calculate_service_durations()

        # Verify fallback duration
        assert "total_duration_minutes" in fsm.collected_data
        assert fsm.collected_data["total_duration_minutes"] == 60  # Default
        assert fsm.collected_data["slot"]["duration_minutes"] == 60
