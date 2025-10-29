"""
Unit tests for calendar tools with mocked Google Calendar API.

Tests cover:
- get_calendar_availability: category filtering, holiday detection, busy slots, rate limiting
- create_calendar_event: provisional/confirmed events, color codes, error handling
- delete_calendar_event: successful deletion, 404 handling, rate limiting
- Helper functions: time slot generation, availability checking
"""

import contextlib
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from googleapiclient.errors import HttpError
from zoneinfo import ZoneInfo

from agent.tools.calendar_tools import (
    check_holiday_closure,
    create_calendar_event,
    delete_calendar_event,
    generate_time_slots,
    get_calendar_availability,
    get_stylists_by_category,
    is_slot_available,
)
from database.models import ServiceCategory, Stylist

TIMEZONE = ZoneInfo("Europe/Madrid")


# ============================================================================
# Test Helpers
# ============================================================================


def create_mock_async_session(mock_session):
    """
    Create a mock async context manager for get_async_session.

    Args:
        mock_session: AsyncMock session object

    Returns:
        Function that returns an async context manager
    """
    @contextlib.asynccontextmanager
    async def mock_session_generator():
        yield mock_session

    return lambda: mock_session_generator()


# ============================================================================
# Helper Function Tests
# ============================================================================


class TestGenerateTimeSlots:
    """Test time slot generation based on business hours."""

    def test_weekday_slots(self):
        """Test Monday-Friday generates 10:00-20:00 in 30-min increments."""
        date = datetime(2025, 1, 20, tzinfo=TIMEZONE)  # Monday
        slots = generate_time_slots(date, day_of_week=0)

        assert len(slots) == 20  # 10 hours * 2 slots per hour
        assert slots[0].hour == 10
        assert slots[0].minute == 0
        assert slots[-1].hour == 19
        assert slots[-1].minute == 30

    def test_saturday_slots(self):
        """Test Saturday generates 10:00-14:00 in 30-min increments."""
        date = datetime(2025, 1, 25, tzinfo=TIMEZONE)  # Saturday
        slots = generate_time_slots(date, day_of_week=5)

        assert len(slots) == 8  # 4 hours * 2 slots per hour
        assert slots[0].hour == 10
        assert slots[0].minute == 0
        assert slots[-1].hour == 13
        assert slots[-1].minute == 30

    def test_sunday_closed(self):
        """Test Sunday returns empty list (closed)."""
        date = datetime(2025, 1, 26, tzinfo=TIMEZONE)  # Sunday
        slots = generate_time_slots(date, day_of_week=6)

        assert len(slots) == 0


class TestIsSlotAvailable:
    """Test slot availability checking against busy events."""

    def test_slot_available_no_events(self):
        """Test slot is available when no busy events."""
        slot_time = datetime(2025, 1, 20, 10, 0, tzinfo=TIMEZONE)
        busy_events = []

        assert is_slot_available(slot_time, busy_events) is True

    def test_slot_busy_overlapping_event(self):
        """Test slot is busy when overlapping with event."""
        slot_time = datetime(2025, 1, 20, 10, 0, tzinfo=TIMEZONE)

        # Event from 10:00-11:00 overlaps with 10:00-10:30 slot
        busy_events = [
            {
                "start": {"dateTime": "2025-01-20T10:00:00+01:00"},
                "end": {"dateTime": "2025-01-20T11:00:00+01:00"}
            }
        ]

        assert is_slot_available(slot_time, busy_events) is False

    def test_slot_available_after_event(self):
        """Test slot is available after event ends."""
        slot_time = datetime(2025, 1, 20, 11, 0, tzinfo=TIMEZONE)

        # Event from 10:00-11:00 does not overlap with 11:00-11:30 slot
        busy_events = [
            {
                "start": {"dateTime": "2025-01-20T10:00:00+01:00"},
                "end": {"dateTime": "2025-01-20T11:00:00+01:00"}
            }
        ]

        assert is_slot_available(slot_time, busy_events) is True

    def test_slot_available_before_event(self):
        """Test slot is available before event starts."""
        slot_time = datetime(2025, 1, 20, 9, 30, tzinfo=TIMEZONE)

        # Event from 10:00-11:00 does not overlap with 9:30-10:00 slot
        busy_events = [
            {
                "start": {"dateTime": "2025-01-20T10:00:00+01:00"},
                "end": {"dateTime": "2025-01-20T11:00:00+01:00"}
            }
        ]

        assert is_slot_available(slot_time, busy_events) is True


# ============================================================================
# Database Query Tests
# ============================================================================


class TestGetStylistsByCategory:
    """Test stylist filtering by service category."""

    @pytest.mark.asyncio
    async def test_hairdressing_category(self):
        """Test querying stylists for Hairdressing category."""
        mock_stylist1 = MagicMock(spec=Stylist)
        mock_stylist1.id = uuid4()
        mock_stylist1.name = "Pilar"
        mock_stylist1.category = ServiceCategory.HAIRDRESSING
        mock_stylist1.google_calendar_id = "pilar@atrevete.com"
        mock_stylist1.is_active = True

        mock_stylist2 = MagicMock(spec=Stylist)
        mock_stylist2.id = uuid4()
        mock_stylist2.name = "Laura"
        mock_stylist2.category = ServiceCategory.BOTH
        mock_stylist2.google_calendar_id = "laura@atrevete.com"
        mock_stylist2.is_active = True

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_stylist1, mock_stylist2]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        with patch("agent.tools.calendar_tools.get_async_session", side_effect=create_mock_async_session(mock_session)):
            stylists = await get_stylists_by_category("Hairdressing")

            assert len(stylists) == 2
            assert stylists[0].name == "Pilar"
            assert stylists[1].name == "Laura"

    @pytest.mark.asyncio
    async def test_invalid_category(self):
        """Test invalid category returns empty list."""
        stylists = await get_stylists_by_category("InvalidCategory")

        assert len(stylists) == 0


# ============================================================================
# Holiday Detection Tests
# ============================================================================


class TestCheckHolidayClosure:
    """Test holiday detection across all calendars."""

    @pytest.mark.asyncio
    async def test_holiday_detected(self):
        """Test holiday event detected in calendar."""
        mock_stylist = MagicMock(spec=Stylist)
        mock_stylist.id = uuid4()
        mock_stylist.name = "Pilar"
        mock_stylist.google_calendar_id = "pilar@atrevete.com"
        mock_stylist.is_active = True

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_stylist]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result

        # Mock calendar API response with holiday event
        mock_service = MagicMock()
        mock_events_list = MagicMock()
        mock_events_list.execute.return_value = {
            "items": [
                {
                    "summary": "Festivo - Navidad",
                    "start": {"dateTime": "2025-12-25T00:00:00+01:00"},
                    "end": {"dateTime": "2025-12-25T23:59:59+01:00"}
                }
            ]
        }
        mock_service.events.return_value.list.return_value = mock_events_list

        target_date = datetime(2025, 12, 25, tzinfo=TIMEZONE)

        with patch("agent.tools.calendar_tools.get_async_session", side_effect=create_mock_async_session(mock_session)):
            result = await check_holiday_closure(mock_service, target_date, "test_conv")

            assert result is not None
            assert result["holiday_detected"] is True
            assert "Festivo" in result["reason"]
            assert result["calendar"] == "Pilar"

    @pytest.mark.asyncio
    async def test_no_holiday(self):
        """Test no holiday detected."""
        mock_stylist = MagicMock(spec=Stylist)
        mock_stylist.id = uuid4()
        mock_stylist.name = "Pilar"
        mock_stylist.google_calendar_id = "pilar@atrevete.com"
        mock_stylist.is_active = True

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_stylist]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result


        # Mock calendar API response with no holiday events
        mock_service = MagicMock()
        mock_events_list = MagicMock()
        mock_events_list.execute.return_value = {"items": []}
        mock_service.events.return_value.list.return_value = mock_events_list

        target_date = datetime(2025, 1, 20, tzinfo=TIMEZONE)

        with patch("agent.tools.calendar_tools.get_async_session", side_effect=create_mock_async_session(mock_session)):
            result = await check_holiday_closure(mock_service, target_date, "test_conv")

            assert result is None


# ============================================================================
# Tool Tests with Mocked Google Calendar API
# ============================================================================


class TestGetCalendarAvailability:
    """Test get_calendar_availability tool."""

    @pytest.mark.asyncio
    async def test_availability_with_hairdressing_category(self):
        """Test availability query filters by category correctly."""
        mock_stylist = MagicMock(spec=Stylist)
        mock_stylist.id = uuid4()
        mock_stylist.name = "Pilar"
        mock_stylist.category = ServiceCategory.HAIRDRESSING
        mock_stylist.google_calendar_id = "pilar@atrevete.com"
        mock_stylist.is_active = True

        # Mock database queries
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_stylist]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result


        # Mock calendar service
        mock_service = MagicMock()
        mock_events_list = MagicMock()
        mock_events_list.execute.return_value = {"items": []}  # No busy events
        mock_service.events.return_value.list.return_value = mock_events_list

        mock_calendar_client = MagicMock()
        mock_calendar_client.get_service.return_value = mock_service

        with patch("agent.tools.calendar_tools.get_async_session", side_effect=create_mock_async_session(mock_session)), \
             patch("agent.tools.calendar_tools.get_calendar_client", return_value=mock_calendar_client):

            result = await get_calendar_availability.ainvoke({
                "category": "Hairdressing",
                "date": "2025-01-20",  # Monday
                "conversation_id": "test_conv"
            })

            assert result["success"] is True
            assert len(result["available_slots"]) > 0
            assert result["available_slots"][0]["stylist_name"] == "Pilar"

    @pytest.mark.asyncio
    async def test_availability_with_busy_event(self):
        """Test busy event excludes slot from availability."""
        mock_stylist = MagicMock(spec=Stylist)
        mock_stylist.id = uuid4()
        mock_stylist.name = "Pilar"
        mock_stylist.category = ServiceCategory.HAIRDRESSING
        mock_stylist.google_calendar_id = "pilar@atrevete.com"
        mock_stylist.is_active = True

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_stylist]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result


        # Mock calendar with busy event at 10:00-11:00
        mock_service = MagicMock()
        mock_events_list = MagicMock()
        mock_events_list.execute.return_value = {
            "items": [
                {
                    "summary": "Existing Appointment",
                    "start": {"dateTime": "2025-01-20T10:00:00+01:00"},
                    "end": {"dateTime": "2025-01-20T11:00:00+01:00"}
                }
            ]
        }
        mock_service.events.return_value.list.return_value = mock_events_list

        mock_calendar_client = MagicMock()
        mock_calendar_client.get_service.return_value = mock_service

        with patch("agent.tools.calendar_tools.get_async_session", side_effect=create_mock_async_session(mock_session)), \
             patch("agent.tools.calendar_tools.get_calendar_client", return_value=mock_calendar_client):

            result = await get_calendar_availability.ainvoke({
                "category": "Hairdressing",
                "date": "2025-01-20",
                "conversation_id": "test_conv"
            })

            assert result["success"] is True

            # Check that 10:00 and 10:30 slots are excluded
            slot_times = [slot["time"] for slot in result["available_slots"]]
            assert "10:00" not in slot_times
            assert "10:30" not in slot_times

    @pytest.mark.asyncio
    async def test_availability_with_holiday(self):
        """Test holiday event returns empty availability."""
        mock_stylist = MagicMock(spec=Stylist)
        mock_stylist.id = uuid4()
        mock_stylist.name = "Pilar"
        mock_stylist.google_calendar_id = "pilar@atrevete.com"
        mock_stylist.is_active = True

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_stylist]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result


        # Mock calendar with holiday event
        mock_service = MagicMock()
        mock_events_list = MagicMock()
        mock_events_list.execute.return_value = {
            "items": [
                {
                    "summary": "Festivo - Navidad",
                    "start": {"dateTime": "2025-12-25T00:00:00+01:00"},
                    "end": {"dateTime": "2025-12-25T23:59:59+01:00"}
                }
            ]
        }
        mock_service.events.return_value.list.return_value = mock_events_list

        mock_calendar_client = MagicMock()
        mock_calendar_client.get_service.return_value = mock_service

        with patch("agent.tools.calendar_tools.get_async_session", side_effect=create_mock_async_session(mock_session)), \
             patch("agent.tools.calendar_tools.get_calendar_client", return_value=mock_calendar_client):

            result = await get_calendar_availability.ainvoke({
                "category": "Hairdressing",
                "date": "2025-12-25",
                "conversation_id": "test_conv"
            })

            assert result["success"] is True
            assert result["holiday_detected"] is True
            assert len(result["available_slots"]) == 0

    @pytest.mark.asyncio
    async def test_availability_rate_limit_error(self):
        """Test rate limit error after 3 retries."""
        mock_stylist = MagicMock(spec=Stylist)
        mock_stylist.id = uuid4()
        mock_stylist.name = "Pilar"
        mock_stylist.google_calendar_id = "pilar@atrevete.com"
        mock_stylist.is_active = True

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_stylist]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result


        # Mock 429 rate limit error
        mock_response = MagicMock()
        mock_response.status = 429
        http_error = HttpError(resp=mock_response, content=b"Rate limit exceeded")

        mock_service = MagicMock()
        mock_service.events.return_value.list.return_value.execute.side_effect = http_error

        mock_calendar_client = MagicMock()
        mock_calendar_client.get_service.return_value = mock_service

        with patch("agent.tools.calendar_tools.get_async_session", side_effect=create_mock_async_session(mock_session)), \
             patch("agent.tools.calendar_tools.get_calendar_client", return_value=mock_calendar_client):

            result = await get_calendar_availability.ainvoke({
                "category": "Hairdressing",
                "date": "2025-01-20",
                "conversation_id": "test_conv"
            })

            assert result["success"] is False
            assert "Rate limit exceeded" in result["error"]


class TestCreateCalendarEvent:
    """Test create_calendar_event tool."""

    @pytest.mark.asyncio
    async def test_create_provisional_event(self):
        """Test creating provisional event with yellow color."""
        stylist_id = uuid4()

        mock_stylist = MagicMock(spec=Stylist)
        mock_stylist.id = stylist_id
        mock_stylist.name = "Pilar"
        mock_stylist.google_calendar_id = "pilar@atrevete.com"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_stylist

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result


        # Mock calendar event creation
        mock_created_event = {
            "id": "event123",
            "summary": "[PROVISIONAL] Juan García - Corte de pelo",
            "start": {"dateTime": "2025-01-20T10:00:00+01:00"},
            "end": {"dateTime": "2025-01-20T10:30:00+01:00"}
        }

        mock_service = MagicMock()
        mock_insert = MagicMock()
        mock_insert.execute.return_value = mock_created_event
        mock_service.events.return_value.insert.return_value = mock_insert

        mock_calendar_client = MagicMock()
        mock_calendar_client.get_service.return_value = mock_service

        with patch("agent.tools.calendar_tools.get_async_session", side_effect=create_mock_async_session(mock_session)), \
             patch("agent.tools.calendar_tools.get_calendar_client", return_value=mock_calendar_client):

            result = await create_calendar_event.ainvoke({
                "stylist_id": str(stylist_id),
                "start_time": "2025-01-20T10:00:00+01:00",
                "duration_minutes": 30,
                "customer_name": "Juan García",
                "service_names": "Corte de pelo",
                "status": "provisional",
                "conversation_id": "test_conv"
            })

            assert result["success"] is True
            assert result["event_id"] == "event123"
            assert "[PROVISIONAL]" in result["summary"]

            # Verify color code was set correctly
            call_args = mock_service.events.return_value.insert.call_args
            assert call_args[1]["body"]["colorId"] == "5"  # Yellow

    @pytest.mark.asyncio
    async def test_create_confirmed_event(self):
        """Test creating confirmed event with green color."""
        stylist_id = uuid4()

        mock_stylist = MagicMock(spec=Stylist)
        mock_stylist.id = stylist_id
        mock_stylist.name = "Pilar"
        mock_stylist.google_calendar_id = "pilar@atrevete.com"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_stylist

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result


        # Mock calendar event creation
        mock_created_event = {
            "id": "event456",
            "summary": "Juan García - Corte de pelo",
            "start": {"dateTime": "2025-01-20T10:00:00+01:00"},
            "end": {"dateTime": "2025-01-20T10:30:00+01:00"}
        }

        mock_service = MagicMock()
        mock_insert = MagicMock()
        mock_insert.execute.return_value = mock_created_event
        mock_service.events.return_value.insert.return_value = mock_insert

        mock_calendar_client = MagicMock()
        mock_calendar_client.get_service.return_value = mock_service

        with patch("agent.tools.calendar_tools.get_async_session", side_effect=create_mock_async_session(mock_session)), \
             patch("agent.tools.calendar_tools.get_calendar_client", return_value=mock_calendar_client):

            result = await create_calendar_event.ainvoke({
                "stylist_id": str(stylist_id),
                "start_time": "2025-01-20T10:00:00+01:00",
                "duration_minutes": 30,
                "customer_name": "Juan García",
                "service_names": "Corte de pelo",
                "status": "confirmed",
                "conversation_id": "test_conv"
            })

            assert result["success"] is True
            assert result["event_id"] == "event456"
            assert "[PROVISIONAL]" not in result["summary"]

            # Verify color code was set correctly
            call_args = mock_service.events.return_value.insert.call_args
            assert call_args[1]["body"]["colorId"] == "10"  # Green


class TestDeleteCalendarEvent:
    """Test delete_calendar_event tool."""

    @pytest.mark.asyncio
    async def test_delete_event_success(self):
        """Test successful event deletion."""
        stylist_id = uuid4()

        mock_stylist = MagicMock(spec=Stylist)
        mock_stylist.id = stylist_id
        mock_stylist.name = "Pilar"
        mock_stylist.google_calendar_id = "pilar@atrevete.com"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_stylist

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result


        # Mock calendar event deletion
        mock_service = MagicMock()
        mock_delete = MagicMock()
        mock_delete.execute.return_value = None
        mock_service.events.return_value.delete.return_value = mock_delete

        mock_calendar_client = MagicMock()
        mock_calendar_client.get_service.return_value = mock_service

        with patch("agent.tools.calendar_tools.get_async_session", side_effect=create_mock_async_session(mock_session)), \
             patch("agent.tools.calendar_tools.get_calendar_client", return_value=mock_calendar_client):

            result = await delete_calendar_event.ainvoke({
                "stylist_id": str(stylist_id),
                "event_id": "event123",
                "conversation_id": "test_conv"
            })

            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_delete_event_already_deleted(self):
        """Test deleting event that's already deleted (404 handled gracefully)."""
        stylist_id = uuid4()

        mock_stylist = MagicMock(spec=Stylist)
        mock_stylist.id = stylist_id
        mock_stylist.name = "Pilar"
        mock_stylist.google_calendar_id = "pilar@atrevete.com"

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_stylist

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result


        # Mock 404 error
        mock_response = MagicMock()
        mock_response.status = 404
        http_error = HttpError(resp=mock_response, content=b"Not found")

        mock_service = MagicMock()
        mock_service.events.return_value.delete.return_value.execute.side_effect = http_error

        mock_calendar_client = MagicMock()
        mock_calendar_client.get_service.return_value = mock_service

        with patch("agent.tools.calendar_tools.get_async_session", side_effect=create_mock_async_session(mock_session)), \
             patch("agent.tools.calendar_tools.get_calendar_client", return_value=mock_calendar_client):

            result = await delete_calendar_event.ainvoke({
                "stylist_id": str(stylist_id),
                "event_id": "event123",
                "conversation_id": "test_conv"
            })

            # 404 should be treated as success (already deleted)
            assert result["success"] is True
