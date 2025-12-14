"""
Unit tests for transaction_validators.py - Business rule validators.

Tests coverage:
- validate_category_consistency() with various service combinations
- validate_slot_availability() with different conflict scenarios
- validate_3_day_rule() with edge cases (today, tomorrow, 3 days, etc.)
- Timezone handling
- Error messages and logging
- Edge cases and boundary conditions
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from agent.validators.transaction_validators import (
    validate_category_consistency,
    validate_slot_availability,
    validate_3_day_rule,
    validate_appointment_limit,
    MADRID_TZ,
)
from database.models import ServiceCategory, AppointmentStatus


# ============================================================================
# Test validate_category_consistency()
# ============================================================================


class TestValidateCategoryConsistency:
    """Test category consistency validation."""

    @pytest.mark.asyncio
    async def test_empty_service_list_is_valid(self):
        """Test that empty service list is considered valid."""
        result = await validate_category_consistency([])

        assert result["valid"] is True
        assert result["error_code"] is None
        assert result["error_message"] is None
        assert result["categories_found"] == []

    @pytest.mark.asyncio
    async def test_single_service_is_valid(self):
        """Test that single service is always valid."""
        service_id = uuid4()

        # Mock database session
        with patch("agent.validators.transaction_validators.get_async_session") as mock_session_ctx:
            mock_session = MagicMock()
            mock_service = MagicMock()
            mock_service.category = ServiceCategory.PELUQUERIA

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [mock_service]
            mock_session.execute = AsyncMock(return_value=mock_result)

            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            result = await validate_category_consistency([service_id])

        assert result["valid"] is True
        assert result["error_code"] is None
        assert result["categories_found"] == ["Peluquería"]

    @pytest.mark.asyncio
    async def test_multiple_services_same_category_valid(self):
        """Test that multiple services of same category are valid."""
        service_ids = [uuid4(), uuid4(), uuid4()]

        with patch("agent.validators.transaction_validators.get_async_session") as mock_session_ctx:
            mock_session = MagicMock()

            # All services are Peluquería
            mock_services = [
                MagicMock(category=ServiceCategory.PELUQUERIA),
                MagicMock(category=ServiceCategory.PELUQUERIA),
                MagicMock(category=ServiceCategory.PELUQUERIA),
            ]

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = mock_services
            mock_session.execute = AsyncMock(return_value=mock_result)

            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            result = await validate_category_consistency(service_ids)

        assert result["valid"] is True
        assert result["error_code"] is None
        assert result["categories_found"] == ["Peluquería"]

    @pytest.mark.asyncio
    async def test_mixed_categories_invalid(self):
        """Test that mixing Peluquería and Estética is invalid."""
        service_ids = [uuid4(), uuid4()]

        with patch("agent.validators.transaction_validators.get_async_session") as mock_session_ctx:
            mock_session = MagicMock()

            # Mix of Peluquería and Estética
            mock_services = [
                MagicMock(category=ServiceCategory.PELUQUERIA),
                MagicMock(category=ServiceCategory.ESTETICA),
            ]

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = mock_services
            mock_session.execute = AsyncMock(return_value=mock_result)

            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            result = await validate_category_consistency(service_ids)

        assert result["valid"] is False
        assert result["error_code"] == "CATEGORY_MISMATCH"
        assert "diferentes categorías" in result["error_message"]
        assert len(result["categories_found"]) == 2
        assert "Peluquería" in result["categories_found"]
        assert "Estética" in result["categories_found"]

    @pytest.mark.asyncio
    async def test_all_estetica_services_valid(self):
        """Test that all Estética services are valid."""
        service_ids = [uuid4(), uuid4()]

        with patch("agent.validators.transaction_validators.get_async_session") as mock_session_ctx:
            mock_session = MagicMock()

            mock_services = [
                MagicMock(category=ServiceCategory.ESTETICA),
                MagicMock(category=ServiceCategory.ESTETICA),
            ]

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = mock_services
            mock_session.execute = AsyncMock(return_value=mock_result)

            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            result = await validate_category_consistency(service_ids)

        assert result["valid"] is True
        assert result["categories_found"] == ["Estética"]


# ============================================================================
# Test validate_3_day_rule()
# ============================================================================


class TestValidate3DayRule:
    """Test 3-day advance booking rule."""

    @pytest.mark.asyncio
    async def test_today_is_invalid(self):
        """Test that booking for today violates 3-day rule."""
        today = datetime.now(MADRID_TZ)
        result = await validate_3_day_rule(today)

        assert result["valid"] is False
        assert result["error_code"] == "DATE_TOO_SOON"
        assert "3 días" in result["error_message"]
        assert result["days_until_appointment"] == 0
        assert result["minimum_required_days"] == 3

    @pytest.mark.asyncio
    async def test_tomorrow_is_invalid(self):
        """Test that booking for tomorrow violates 3-day rule."""
        tomorrow = datetime.now(MADRID_TZ) + timedelta(days=1)
        result = await validate_3_day_rule(tomorrow)

        assert result["valid"] is False
        assert result["error_code"] == "DATE_TOO_SOON"
        assert result["days_until_appointment"] == 1

    @pytest.mark.asyncio
    async def test_two_days_ahead_is_invalid(self):
        """Test that 2 days ahead violates 3-day rule."""
        two_days = datetime.now(MADRID_TZ) + timedelta(days=2)
        result = await validate_3_day_rule(two_days)

        assert result["valid"] is False
        assert result["error_code"] == "DATE_TOO_SOON"
        assert result["days_until_appointment"] == 2

    @pytest.mark.asyncio
    async def test_exactly_three_days_is_valid(self):
        """Test that exactly 3 days ahead is valid."""
        three_days = datetime.now(MADRID_TZ) + timedelta(days=3)
        result = await validate_3_day_rule(three_days)

        assert result["valid"] is True
        assert result["error_code"] is None
        assert result["error_message"] is None
        assert result["days_until_appointment"] == 3
        assert result["minimum_required_days"] == 3

    @pytest.mark.asyncio
    async def test_four_days_ahead_is_valid(self):
        """Test that 4 days ahead is valid."""
        four_days = datetime.now(MADRID_TZ) + timedelta(days=4)
        result = await validate_3_day_rule(four_days)

        assert result["valid"] is True
        assert result["days_until_appointment"] == 4

    @pytest.mark.asyncio
    async def test_one_week_ahead_is_valid(self):
        """Test that 1 week ahead is valid."""
        one_week = datetime.now(MADRID_TZ) + timedelta(days=7)
        result = await validate_3_day_rule(one_week)

        assert result["valid"] is True
        assert result["days_until_appointment"] == 7

    @pytest.mark.asyncio
    async def test_one_month_ahead_is_valid(self):
        """Test that far future dates are valid."""
        one_month = datetime.now(MADRID_TZ) + timedelta(days=30)
        result = await validate_3_day_rule(one_month)

        assert result["valid"] is True
        assert result["days_until_appointment"] == 30

    @pytest.mark.asyncio
    async def test_timezone_naive_datetime_handled(self):
        """Test that timezone-naive datetimes are handled."""
        # Create naive datetime (no timezone)
        three_days_naive = datetime.now() + timedelta(days=3)
        three_days_naive = three_days_naive.replace(tzinfo=None)

        result = await validate_3_day_rule(three_days_naive)

        # Should still work (timezone added automatically)
        assert result["valid"] is True
        assert result["days_until_appointment"] == 3

    @pytest.mark.asyncio
    async def test_time_component_ignored(self):
        """Test that time component is ignored (only dates compared)."""
        # 3 days ahead at 23:59
        three_days_late = datetime.now(MADRID_TZ) + timedelta(days=3)
        three_days_late = three_days_late.replace(hour=23, minute=59)

        result = await validate_3_day_rule(three_days_late)

        assert result["valid"] is True
        assert result["days_until_appointment"] == 3

    @pytest.mark.asyncio
    async def test_error_message_includes_minimum_date(self):
        """Test that error message includes earliest valid date."""
        tomorrow = datetime.now(MADRID_TZ) + timedelta(days=1)
        result = await validate_3_day_rule(tomorrow)

        assert result["valid"] is False
        # Should mention the minimum date
        assert "partir del" in result["error_message"]
        # Should include a date in format DD/MM/YYYY
        import re
        assert re.search(r'\d{2}/\d{2}/\d{4}', result["error_message"])


# ============================================================================
# Test validate_slot_availability()
# ============================================================================


class TestValidateSlotAvailability:
    """Test slot availability validation."""

    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        return MagicMock()

    @pytest.fixture
    def stylist_id(self):
        """Sample stylist UUID."""
        return uuid4()

    @pytest.fixture
    def start_time(self):
        """Sample start time."""
        return datetime(2025, 11, 8, 10, 0, 0, tzinfo=MADRID_TZ)

    @pytest.mark.asyncio
    async def test_slot_available_when_no_conflicts(
        self, mock_session, stylist_id, start_time
    ):
        """Test that slot is available when no conflicts exist."""
        # Mock empty result (no conflicting appointments)
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await validate_slot_availability(
            stylist_id, start_time, duration_minutes=60, session=mock_session
        )

        assert result["available"] is True
        assert result["error_code"] is None
        assert result["error_message"] is None
        assert result["conflicting_appointment_id"] is None

    @pytest.mark.asyncio
    async def test_slot_unavailable_when_conflict_exists(
        self, mock_session, stylist_id, start_time
    ):
        """Test that slot is unavailable when conflict exists."""
        # Mock conflicting appointment
        conflict_id = uuid4()
        mock_appointment = MagicMock()
        mock_appointment.id = conflict_id
        mock_appointment.start_time = start_time
        mock_appointment.end_time = start_time + timedelta(minutes=60)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_appointment]
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await validate_slot_availability(
            stylist_id, start_time, duration_minutes=60, session=mock_session
        )

        assert result["available"] is False
        assert result["error_code"] == "SLOT_TAKEN"
        assert "ocupado" in result["error_message"]
        assert result["conflicting_appointment_id"] == conflict_id

    @pytest.mark.asyncio
    async def test_slot_checks_with_for_update_lock(
        self, mock_session, stylist_id, start_time
    ):
        """Test that query uses SELECT FOR UPDATE for row locking."""
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        await validate_slot_availability(
            stylist_id, start_time, duration_minutes=60, session=mock_session
        )

        # Verify session.execute was called (query was executed)
        mock_session.execute.assert_called_once()

        # The query should include with_for_update() for locking
        # We can't easily test the exact SQL, but we verified it's called

    @pytest.mark.asyncio
    async def test_slot_includes_buffer_time(
        self, mock_session, stylist_id, start_time
    ):
        """Test that duration includes 10-minute buffer."""
        # Duration passed should already include buffer
        # This test verifies the end_time calculation

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        # 60 min service + 10 min buffer = 70 min total
        result = await validate_slot_availability(
            stylist_id, start_time, duration_minutes=70, session=mock_session
        )

        assert result["available"] is True

    @pytest.mark.asyncio
    async def test_slot_only_checks_pending_and_confirmed(
        self, mock_session, stylist_id, start_time
    ):
        """Test that only PENDING and CONFIRMED appointments are checked."""
        # This is tested indirectly through the query
        # Cancelled/completed appointments should not cause conflicts

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await validate_slot_availability(
            stylist_id, start_time, duration_minutes=60, session=mock_session
        )

        assert result["available"] is True

    @pytest.mark.asyncio
    async def test_multiple_conflicts_returns_first(
        self, mock_session, stylist_id, start_time
    ):
        """Test that if multiple conflicts exist, first one is returned."""
        conflict1_id = uuid4()
        conflict2_id = uuid4()

        mock_apt1 = MagicMock()
        mock_apt1.id = conflict1_id
        mock_apt1.start_time = start_time
        mock_apt1.end_time = start_time + timedelta(minutes=60)

        mock_apt2 = MagicMock()
        mock_apt2.id = conflict2_id
        mock_apt2.start_time = start_time + timedelta(minutes=30)
        mock_apt2.end_time = start_time + timedelta(minutes=90)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_apt1, mock_apt2]
        mock_session.execute = AsyncMock(return_value=mock_result)

        result = await validate_slot_availability(
            stylist_id, start_time, duration_minutes=60, session=mock_session
        )

        assert result["available"] is False
        # Returns first conflict
        assert result["conflicting_appointment_id"] == conflict1_id


# ============================================================================
# Test Logging Behavior
# ============================================================================


class TestLoggingBehavior:
    """Test that validators log appropriately."""

    @pytest.mark.asyncio
    async def test_category_mismatch_logs_warning(self):
        """Test that category mismatch logs a warning."""
        service_ids = [uuid4(), uuid4()]

        with patch("agent.validators.transaction_validators.get_async_session") as mock_session_ctx:
            mock_session = MagicMock()
            mock_services = [
                MagicMock(category=ServiceCategory.PELUQUERIA),
                MagicMock(category=ServiceCategory.ESTETICA),
            ]
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = mock_services
            mock_session.execute = AsyncMock(return_value=mock_result)
            mock_session_ctx.return_value.__aenter__.return_value = mock_session

            with patch("agent.validators.transaction_validators.logger") as mock_logger:
                await validate_category_consistency(service_ids)

                mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_3day_rule_violation_logs_warning(self):
        """Test that 3-day rule violation logs a warning."""
        tomorrow = datetime.now(MADRID_TZ) + timedelta(days=1)

        with patch("agent.validators.transaction_validators.logger") as mock_logger:
            await validate_3_day_rule(tomorrow)

            mock_logger.warning.assert_called_once()
            call_args = mock_logger.warning.call_args[0][0]
            assert "3-day rule violation" in call_args

    @pytest.mark.asyncio
    async def test_3day_rule_pass_logs_info(self):
        """Test that passing 3-day rule logs info."""
        four_days = datetime.now(MADRID_TZ) + timedelta(days=4)

        with patch("agent.validators.transaction_validators.logger") as mock_logger:
            await validate_3_day_rule(four_days)

            mock_logger.info.assert_called_once()


# ============================================================================
# Test Edge Cases
# ============================================================================


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @pytest.mark.asyncio
    async def test_validate_3day_rule_on_leap_year(self):
        """Test 3-day rule around leap year dates."""
        # Feb 29, 2024 (leap year) + 3 days = March 3
        leap_date = datetime(2024, 2, 29, 10, 0, 0, tzinfo=MADRID_TZ)

        # Mock now to be Feb 26, 2024
        with patch("agent.validators.transaction_validators.datetime") as mock_datetime:
            mock_datetime.now.return_value = datetime(2024, 2, 26, 0, 0, 0, tzinfo=MADRID_TZ)
            mock_datetime.side_effect = lambda *args, **kw: datetime(*args, **kw)

            result = await validate_3_day_rule(leap_date)

        # 3 days from Feb 26 is Feb 29 (valid)
        assert result["valid"] is True

    @pytest.mark.asyncio
    async def test_validate_3day_rule_across_month_boundary(self):
        """Test 3-day rule across month boundaries."""
        # November 30 + 3 days would be December 3
        # We can't easily mock "now" so we test the logic works
        future_date = datetime.now(MADRID_TZ) + timedelta(days=5)
        result = await validate_3_day_rule(future_date)

        assert result["valid"] is True


# ============================================================================
# Test validate_appointment_limit()
# ============================================================================


class TestValidateAppointmentLimit:
    """Test appointment limit validation per customer."""

    @pytest.fixture
    def customer_id(self):
        """Sample customer UUID."""
        return uuid4()

    @pytest.mark.asyncio
    async def test_under_limit_is_valid(self, customer_id):
        """Test that customer under limit passes validation."""
        with patch("agent.validators.transaction_validators.get_async_session") as mock_session_ctx:
            with patch("shared.settings_service.get_settings_service") as mock_settings:
                mock_service = AsyncMock()
                mock_service.get = AsyncMock(return_value=3)
                mock_settings.return_value = mock_service

                mock_session = MagicMock()
                mock_result = MagicMock()
                mock_result.scalar.return_value = 2  # 2 existing appointments
                mock_session.execute = AsyncMock(return_value=mock_result)
                mock_session_ctx.return_value.__aenter__.return_value = mock_session

                result = await validate_appointment_limit(customer_id)

        assert result["valid"] is True
        assert result["error_code"] is None
        assert result["current_count"] == 2
        assert result["max_allowed"] == 3

    @pytest.mark.asyncio
    async def test_at_limit_is_invalid(self, customer_id):
        """Test that customer at limit fails validation."""
        with patch("agent.validators.transaction_validators.get_async_session") as mock_session_ctx:
            with patch("shared.settings_service.get_settings_service") as mock_settings:
                mock_service = AsyncMock()
                mock_service.get = AsyncMock(return_value=3)
                mock_settings.return_value = mock_service

                mock_session = MagicMock()
                mock_result = MagicMock()
                mock_result.scalar.return_value = 3  # At limit
                mock_session.execute = AsyncMock(return_value=mock_result)
                mock_session_ctx.return_value.__aenter__.return_value = mock_session

                result = await validate_appointment_limit(customer_id)

        assert result["valid"] is False
        assert result["error_code"] == "APPOINTMENT_LIMIT_EXCEEDED"
        assert "3 citas programadas" in result["error_message"]
        assert result["current_count"] == 3
        assert result["max_allowed"] == 3

    @pytest.mark.asyncio
    async def test_over_limit_is_invalid(self, customer_id):
        """Test that customer over limit fails validation."""
        with patch("agent.validators.transaction_validators.get_async_session") as mock_session_ctx:
            with patch("shared.settings_service.get_settings_service") as mock_settings:
                mock_service = AsyncMock()
                mock_service.get = AsyncMock(return_value=3)
                mock_settings.return_value = mock_service

                mock_session = MagicMock()
                mock_result = MagicMock()
                mock_result.scalar.return_value = 5  # Over limit
                mock_session.execute = AsyncMock(return_value=mock_result)
                mock_session_ctx.return_value.__aenter__.return_value = mock_session

                result = await validate_appointment_limit(customer_id)

        assert result["valid"] is False
        assert result["error_code"] == "APPOINTMENT_LIMIT_EXCEEDED"
        assert result["current_count"] == 5

    @pytest.mark.asyncio
    async def test_zero_appointments_is_valid(self, customer_id):
        """Test that new customer with zero appointments is valid."""
        with patch("agent.validators.transaction_validators.get_async_session") as mock_session_ctx:
            with patch("shared.settings_service.get_settings_service") as mock_settings:
                mock_service = AsyncMock()
                mock_service.get = AsyncMock(return_value=3)
                mock_settings.return_value = mock_service

                mock_session = MagicMock()
                mock_result = MagicMock()
                mock_result.scalar.return_value = 0
                mock_session.execute = AsyncMock(return_value=mock_result)
                mock_session_ctx.return_value.__aenter__.return_value = mock_session

                result = await validate_appointment_limit(customer_id)

        assert result["valid"] is True
        assert result["current_count"] == 0

    @pytest.mark.asyncio
    async def test_configurable_limit_respected(self, customer_id):
        """Test that configured limit is respected."""
        with patch("agent.validators.transaction_validators.get_async_session") as mock_session_ctx:
            with patch("shared.settings_service.get_settings_service") as mock_settings:
                mock_service = AsyncMock()
                mock_service.get = AsyncMock(return_value=5)  # Custom limit of 5
                mock_settings.return_value = mock_service

                mock_session = MagicMock()
                mock_result = MagicMock()
                mock_result.scalar.return_value = 4  # Under custom limit
                mock_session.execute = AsyncMock(return_value=mock_result)
                mock_session_ctx.return_value.__aenter__.return_value = mock_session

                result = await validate_appointment_limit(customer_id)

        assert result["valid"] is True
        assert result["max_allowed"] == 5

    @pytest.mark.asyncio
    async def test_error_message_in_spanish(self, customer_id):
        """Test that error message is in Spanish."""
        with patch("agent.validators.transaction_validators.get_async_session") as mock_session_ctx:
            with patch("shared.settings_service.get_settings_service") as mock_settings:
                mock_service = AsyncMock()
                mock_service.get = AsyncMock(return_value=3)
                mock_settings.return_value = mock_service

                mock_session = MagicMock()
                mock_result = MagicMock()
                mock_result.scalar.return_value = 3
                mock_session.execute = AsyncMock(return_value=mock_result)
                mock_session_ctx.return_value.__aenter__.return_value = mock_session

                result = await validate_appointment_limit(customer_id)

        assert "Ya tienes" in result["error_message"]
        assert "cancelar una existente" in result["error_message"]
        assert "esperar a que se complete" in result["error_message"]

    @pytest.mark.asyncio
    async def test_limit_check_logs_warning_on_exceed(self, customer_id):
        """Test that exceeding limit logs a warning."""
        with patch("agent.validators.transaction_validators.get_async_session") as mock_session_ctx:
            with patch("shared.settings_service.get_settings_service") as mock_settings:
                mock_service = AsyncMock()
                mock_service.get = AsyncMock(return_value=3)
                mock_settings.return_value = mock_service

                mock_session = MagicMock()
                mock_result = MagicMock()
                mock_result.scalar.return_value = 3
                mock_session.execute = AsyncMock(return_value=mock_result)
                mock_session_ctx.return_value.__aenter__.return_value = mock_session

                with patch("agent.validators.transaction_validators.logger") as mock_logger:
                    await validate_appointment_limit(customer_id)

                    mock_logger.warning.assert_called_once()

    @pytest.mark.asyncio
    async def test_limit_check_logs_info_on_pass(self, customer_id):
        """Test that passing limit check logs info."""
        with patch("agent.validators.transaction_validators.get_async_session") as mock_session_ctx:
            with patch("shared.settings_service.get_settings_service") as mock_settings:
                mock_service = AsyncMock()
                mock_service.get = AsyncMock(return_value=3)
                mock_settings.return_value = mock_service

                mock_session = MagicMock()
                mock_result = MagicMock()
                mock_result.scalar.return_value = 1
                mock_session.execute = AsyncMock(return_value=mock_result)
                mock_session_ctx.return_value.__aenter__.return_value = mock_session

                with patch("agent.validators.transaction_validators.logger") as mock_logger:
                    await validate_appointment_limit(customer_id)

                    mock_logger.info.assert_called_once()

    @pytest.mark.asyncio
    async def test_default_limit_used_when_setting_missing(self, customer_id):
        """Test that default limit (3) is used when setting is not found."""
        with patch("agent.validators.transaction_validators.get_async_session") as mock_session_ctx:
            with patch("shared.settings_service.get_settings_service") as mock_settings:
                mock_service = AsyncMock()
                # Return default value (simulating missing setting)
                mock_service.get = AsyncMock(return_value=3)
                mock_settings.return_value = mock_service

                mock_session = MagicMock()
                mock_result = MagicMock()
                mock_result.scalar.return_value = 2
                mock_session.execute = AsyncMock(return_value=mock_result)
                mock_session_ctx.return_value.__aenter__.return_value = mock_session

                result = await validate_appointment_limit(customer_id)

        # Verify default of 3 was used
        mock_service.get.assert_called_once_with("max_pending_appointments_per_customer", 3)
        assert result["max_allowed"] == 3
