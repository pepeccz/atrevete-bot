"""
Unit tests for availability checking nodes.

Tests cover:
- Slot prioritization algorithm
- Same-day filtering logic
- Spanish day name formatting
- Alternative date suggestion
- Multi-stylist vs single stylist queries
- Load balancing
"""

import pytest
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo
from unittest.mock import AsyncMock, MagicMock, patch

from agent.nodes.availability_nodes import (
    check_availability,
    filter_same_day_slots,
    format_availability_response,
    format_spanish_date,
    get_spanish_day_name,
    prioritize_slots,
    suggest_alternative_dates,
)
from database.models import Service, ServiceCategory, Stylist

TIMEZONE = ZoneInfo("Europe/Madrid")


# ============================================================================
# Test Fixtures
# ============================================================================


@pytest.fixture
def sample_stylists():
    """Create sample stylist objects for testing."""
    return [
        Stylist(
            id=uuid4(),
            name="Pilar",
            category=ServiceCategory.HAIRDRESSING,
            google_calendar_id="pilar@calendar.com",
            is_active=True
        ),
        Stylist(
            id=uuid4(),
            name="Marta",
            category=ServiceCategory.HAIRDRESSING,
            google_calendar_id="marta@calendar.com",
            is_active=True
        ),
        Stylist(
            id=uuid4(),
            name="Rosa",
            category=ServiceCategory.HAIRDRESSING,
            google_calendar_id="rosa@calendar.com",
            is_active=True
        ),
    ]


@pytest.fixture
def sample_services():
    """Create sample service objects for testing."""
    return [
        Service(
            id=uuid4(),
            name="Corte de pelo",
            category=ServiceCategory.HAIRDRESSING,
            price_euros=25,
            duration_minutes=30,
            is_active=True
        ),
        Service(
            id=uuid4(),
            name="Mechas",
            category=ServiceCategory.HAIRDRESSING,
            price_euros=60,
            duration_minutes=120,
            is_active=True
        ),
    ]


@pytest.fixture
def sample_slots(sample_stylists):
    """Create sample available slots."""
    pilar_id = str(sample_stylists[0].id)
    marta_id = str(sample_stylists[1].id)
    rosa_id = str(sample_stylists[2].id)

    return [
        {"time": "10:00", "stylist_id": pilar_id, "stylist_name": "Pilar"},
        {"time": "10:30", "stylist_id": marta_id, "stylist_name": "Marta"},
        {"time": "11:00", "stylist_id": rosa_id, "stylist_name": "Rosa"},
        {"time": "11:30", "stylist_id": pilar_id, "stylist_name": "Pilar"},
        {"time": "14:00", "stylist_id": marta_id, "stylist_name": "Marta"},
        {"time": "14:30", "stylist_id": pilar_id, "stylist_name": "Pilar"},
    ]


# ============================================================================
# Helper Function Tests
# ============================================================================


def test_get_spanish_day_name():
    """Test Spanish day name conversion."""
    # Test various days of the week
    monday = datetime(2025, 3, 3, tzinfo=TIMEZONE)  # Monday
    friday = datetime(2025, 3, 7, tzinfo=TIMEZONE)  # Friday
    saturday = datetime(2025, 3, 8, tzinfo=TIMEZONE)  # Saturday
    sunday = datetime(2025, 3, 9, tzinfo=TIMEZONE)  # Sunday

    assert get_spanish_day_name(monday) == "lunes"
    assert get_spanish_day_name(friday) == "viernes"
    assert get_spanish_day_name(saturday) == "sábado"
    assert get_spanish_day_name(sunday) == "domingo"


def test_format_spanish_date():
    """Test Spanish date formatting."""
    date1 = datetime(2025, 3, 7, tzinfo=TIMEZONE)  # Friday, March 7
    date2 = datetime(2025, 12, 25, tzinfo=TIMEZONE)  # Thursday, December 25

    formatted1 = format_spanish_date(date1)
    formatted2 = format_spanish_date(date2)

    assert "viernes" in formatted1
    assert "7" in formatted1
    assert "marzo" in formatted1

    assert "jueves" in formatted2
    assert "25" in formatted2
    assert "diciembre" in formatted2


def test_filter_same_day_slots_future_date():
    """Test that future dates don't filter slots."""
    tomorrow = datetime.now(TIMEZONE) + timedelta(days=1)

    slots = [
        {"time": "10:00", "stylist_id": "id1", "stylist_name": "Pilar"},
        {"time": "14:00", "stylist_id": "id1", "stylist_name": "Pilar"},
        {"time": "18:00", "stylist_id": "id2", "stylist_name": "Marta"},
    ]

    filtered = filter_same_day_slots(slots, tomorrow)

    # All slots should pass through for future dates
    assert len(filtered) == 3
    assert filtered == slots


def test_filter_same_day_slots_current_day():
    """Test same-day filtering removes slots too soon."""
    # Mock current time to 14:00
    now = datetime.now(TIMEZONE).replace(hour=14, minute=0, second=0, microsecond=0)
    today = now

    slots = [
        {"time": "10:00", "stylist_id": "id1", "stylist_name": "Pilar"},
        {"time": "14:30", "stylist_id": "id1", "stylist_name": "Pilar"},  # < 1h
        {"time": "15:30", "stylist_id": "id2", "stylist_name": "Marta"},  # >= 1h
        {"time": "18:00", "stylist_id": "id2", "stylist_name": "Marta"},  # >= 1h
    ]

    with patch('agent.nodes.availability_nodes.datetime') as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.strptime = datetime.strptime
        filtered = filter_same_day_slots(slots, today)

    # Should filter out 10:00 and 14:30 (both < 1h from 14:00)
    assert len(filtered) == 2
    assert filtered[0]["time"] == "15:30"
    assert filtered[1]["time"] == "18:00"


def test_prioritize_slots_no_preference_load_balancing(sample_slots):
    """Test slot prioritization with load balancing (no preference)."""
    prioritized = prioritize_slots(sample_slots, preferred_stylist_id=None, load_balancing=True)

    # Should select 3 slots
    assert len(prioritized) == 3

    # Should prioritize diversity (different stylists)
    stylist_names = [s["stylist_name"] for s in prioritized]
    # All 3 should be from different stylists
    assert len(set(stylist_names)) == 3

    # Should be earliest times: 10:00, 10:30, 11:00
    assert prioritized[0]["time"] == "10:00"
    assert prioritized[1]["time"] == "10:30"
    assert prioritized[2]["time"] == "11:00"


def test_prioritize_slots_preferred_stylist_available(sample_slots, sample_stylists):
    """Test prioritization with preferred stylist that has availability."""
    pilar_id = sample_stylists[0].id

    prioritized = prioritize_slots(
        sample_slots,
        preferred_stylist_id=pilar_id,
        load_balancing=True
    )

    # Should select up to 3 slots from Pilar only
    assert len(prioritized) <= 3

    # All should be from Pilar
    for slot in prioritized:
        assert slot["stylist_name"] == "Pilar"

    # Should be Pilar's earliest times: 10:00, 11:30, 14:30
    assert prioritized[0]["time"] == "10:00"
    assert prioritized[1]["time"] == "11:30"
    assert prioritized[2]["time"] == "14:30"


def test_prioritize_slots_preferred_stylist_unavailable(sample_slots, sample_stylists):
    """Test prioritization when preferred stylist has no slots."""
    # Create a stylist ID that's not in the slots
    unavailable_stylist_id = uuid4()

    prioritized = prioritize_slots(
        sample_slots,
        preferred_stylist_id=unavailable_stylist_id,
        load_balancing=True
    )

    # Should fall back to other stylists with load balancing
    assert len(prioritized) == 3

    # Should have diversity
    stylist_names = [s["stylist_name"] for s in prioritized]
    assert len(set(stylist_names)) >= 2  # At least 2 different stylists


def test_prioritize_slots_single_stylist_available(sample_stylists):
    """Test prioritization when only one stylist has availability."""
    pilar_id = str(sample_stylists[0].id)

    slots = [
        {"time": "10:00", "stylist_id": pilar_id, "stylist_name": "Pilar"},
        {"time": "11:00", "stylist_id": pilar_id, "stylist_name": "Pilar"},
        {"time": "14:00", "stylist_id": pilar_id, "stylist_name": "Pilar"},
        {"time": "15:00", "stylist_id": pilar_id, "stylist_name": "Pilar"},
    ]

    prioritized = prioritize_slots(slots, preferred_stylist_id=None, load_balancing=True)

    # Should select 3 slots from same stylist
    assert len(prioritized) == 3
    assert all(s["stylist_name"] == "Pilar" for s in prioritized)

    # Should be earliest times
    assert prioritized[0]["time"] == "10:00"
    assert prioritized[1]["time"] == "11:00"
    assert prioritized[2]["time"] == "14:00"


def test_prioritize_slots_empty_list():
    """Test prioritization with empty slot list."""
    prioritized = prioritize_slots([], preferred_stylist_id=None)
    assert prioritized == []


def test_format_availability_response_single_slot(sample_stylists):
    """Test response formatting for single slot."""
    date = datetime(2025, 3, 7, tzinfo=TIMEZONE)  # Friday
    slots = [
        {"time": "10:00", "stylist_id": str(sample_stylists[0].id), "stylist_name": "Pilar"}
    ]

    response = format_availability_response(slots, date)

    assert "viernes" in response
    assert "10:00" in response
    assert "Pilar" in response
    assert "¿Te viene bien?" in response


def test_format_availability_response_two_slots(sample_stylists):
    """Test response formatting for two slots."""
    date = datetime(2025, 3, 7, tzinfo=TIMEZONE)  # Friday
    slots = [
        {"time": "10:00", "stylist_id": str(sample_stylists[0].id), "stylist_name": "Pilar"},
        {"time": "10:30", "stylist_id": str(sample_stylists[1].id), "stylist_name": "Marta"},
    ]

    response = format_availability_response(slots, date)

    assert "viernes" in response
    assert "10:00" in response
    assert "Pilar" in response
    assert "10:30" in response
    assert "Marta" in response
    assert "¿Cuál prefieres?" in response


def test_format_availability_response_three_slots(sample_stylists):
    """Test response formatting for three slots."""
    date = datetime(2025, 3, 7, tzinfo=TIMEZONE)  # Friday
    slots = [
        {"time": "10:00", "stylist_id": str(sample_stylists[0].id), "stylist_name": "Pilar"},
        {"time": "10:30", "stylist_id": str(sample_stylists[1].id), "stylist_name": "Marta"},
        {"time": "11:00", "stylist_id": str(sample_stylists[2].id), "stylist_name": "Rosa"},
    ]

    response = format_availability_response(slots, date)

    assert "viernes" in response
    assert "10:00" in response and "Pilar" in response
    assert "10:30" in response and "Marta" in response
    assert "11:00" in response and "Rosa" in response
    assert "¿Cuál te viene mejor?" in response


def test_format_availability_response_empty_slots():
    """Test response formatting for no slots."""
    date = datetime(2025, 3, 7, tzinfo=TIMEZONE)
    slots = []

    response = format_availability_response(slots, date)

    assert "No tenemos disponibilidad" in response or "viernes" in response


# ============================================================================
# Integration Node Tests (with mocking)
# ============================================================================


@pytest.mark.asyncio
async def test_check_availability_no_services():
    """Test check_availability with no services requested."""
    state = {
        "conversation_id": "test-123",
        "requested_services": [],
        "requested_date": "2025-03-07",
    }

    result = await check_availability(state)

    assert "error" in result
    assert result["available_slots"] == []
    assert result["prioritized_slots"] == []


@pytest.mark.asyncio
async def test_check_availability_no_date():
    """Test check_availability with no date requested."""
    state = {
        "conversation_id": "test-123",
        "requested_services": [uuid4()],
        "requested_date": None,
    }

    result = await check_availability(state)

    assert "error" in result
    assert result["available_slots"] == []
    assert result["prioritized_slots"] == []


@pytest.mark.asyncio
async def test_check_availability_invalid_date():
    """Test check_availability with invalid date format."""
    state = {
        "conversation_id": "test-123",
        "requested_services": [uuid4()],
        "requested_date": "invalid-date",
    }

    result = await check_availability(state)

    assert "error" in result
    assert "Formato de fecha inválido" in result["error"] or result["available_slots"] == []


@pytest.mark.asyncio
@patch('agent.nodes.availability_nodes.get_async_session')
@patch('agent.nodes.availability_nodes.get_stylists_by_category')
@patch('agent.nodes.availability_nodes.query_all_stylists_parallel')
@patch('agent.nodes.availability_nodes.check_holiday_closure')
@patch('agent.nodes.availability_nodes.get_calendar_client')
async def test_check_availability_success(
    mock_calendar_client,
    mock_holiday,
    mock_parallel_query,
    mock_get_stylists,
    mock_session,
    sample_services,
    sample_stylists,
    sample_slots
):
    """Test successful availability check with multiple stylists."""
    # Mock database session
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = sample_services
    mock_execute = AsyncMock(return_value=mock_result)

    mock_session_instance = MagicMock()
    mock_session_instance.execute = mock_execute
    mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
    mock_session_instance.__aexit__ = AsyncMock(return_value=None)

    mock_session.return_value = mock_session_instance

    # Mock holiday check (no holiday)
    mock_holiday.return_value = None

    # Mock stylists query
    mock_get_stylists.return_value = sample_stylists

    # Mock parallel query
    mock_parallel_query.return_value = sample_slots

    # Mock calendar client
    mock_calendar_client.return_value = MagicMock()

    # Test state
    service_ids = [s.id for s in sample_services]
    state = {
        "conversation_id": "test-123",
        "requested_services": service_ids,
        "requested_date": "2025-03-07",  # Friday
        "preferred_stylist_id": None,
    }

    result = await check_availability(state)

    # Verify results
    assert "available_slots" in result
    assert "prioritized_slots" in result
    assert "bot_response" in result
    assert len(result["prioritized_slots"]) <= 3
    assert "viernes" in result["bot_response"]


@pytest.mark.asyncio
@patch('agent.nodes.availability_nodes.get_async_session')
@patch('agent.nodes.availability_nodes.get_stylist_by_id')
@patch('agent.nodes.availability_nodes.query_all_stylists_parallel')
@patch('agent.nodes.availability_nodes.check_holiday_closure')
@patch('agent.nodes.availability_nodes.get_calendar_client')
async def test_check_availability_preferred_stylist(
    mock_calendar_client,
    mock_holiday,
    mock_parallel_query,
    mock_get_stylist,
    mock_session,
    sample_services,
    sample_stylists,
    sample_slots
):
    """Test availability check with preferred stylist filter."""
    # Mock database session
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = sample_services
    mock_execute = AsyncMock(return_value=mock_result)

    mock_session_instance = MagicMock()
    mock_session_instance.execute = mock_execute
    mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
    mock_session_instance.__aexit__ = AsyncMock(return_value=None)

    mock_session.return_value = mock_session_instance

    # Mock holiday check
    mock_holiday.return_value = None

    # Mock single stylist query
    pilar = sample_stylists[0]
    mock_get_stylist.return_value = pilar

    # Mock parallel query (only Pilar's slots)
    pilar_slots = [s for s in sample_slots if s["stylist_name"] == "Pilar"]
    mock_parallel_query.return_value = pilar_slots

    # Mock calendar client
    mock_calendar_client.return_value = MagicMock()

    # Test state with preferred stylist
    service_ids = [s.id for s in sample_services]
    state = {
        "conversation_id": "test-123",
        "requested_services": service_ids,
        "requested_date": "2025-03-07",
        "preferred_stylist_id": pilar.id,
    }

    result = await check_availability(state)

    # Verify only Pilar was queried
    mock_get_stylist.assert_called_once_with(pilar.id)

    # Verify results contain only Pilar's slots
    assert all(s["stylist_name"] == "Pilar" for s in result["prioritized_slots"])


@pytest.mark.asyncio
@patch('agent.nodes.availability_nodes.get_async_session')
@patch('agent.nodes.availability_nodes.get_stylists_by_category')
@patch('agent.nodes.availability_nodes.query_all_stylists_parallel')
@patch('agent.nodes.availability_nodes.suggest_alternative_dates')
@patch('agent.nodes.availability_nodes.check_holiday_closure')
@patch('agent.nodes.availability_nodes.get_calendar_client')
async def test_check_availability_fully_booked(
    mock_calendar_client,
    mock_holiday,
    mock_alternatives,
    mock_parallel_query,
    mock_get_stylists,
    mock_session,
    sample_services,
    sample_stylists
):
    """Test availability check when fully booked (suggests alternatives)."""
    # Mock database session
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = sample_services
    mock_execute = AsyncMock(return_value=mock_result)

    mock_session_instance = MagicMock()
    mock_session_instance.execute = mock_execute
    mock_session_instance.__aenter__ = AsyncMock(return_value=mock_session_instance)
    mock_session_instance.__aexit__ = AsyncMock(return_value=None)

    mock_session.return_value = mock_session_instance

    # Mock holiday check
    mock_holiday.return_value = None

    # Mock stylists query
    mock_get_stylists.return_value = sample_stylists

    # Mock parallel query (no availability)
    mock_parallel_query.return_value = []

    # Mock alternative dates
    mock_alternatives.return_value = [
        {
            "date": datetime(2025, 3, 8, tzinfo=TIMEZONE),
            "day_name": "sábado",
            "formatted": "sábado 8 de marzo",
            "available_count": 10
        },
        {
            "date": datetime(2025, 3, 10, tzinfo=TIMEZONE),
            "day_name": "lunes",
            "formatted": "lunes 10 de marzo",
            "available_count": 15
        }
    ]

    # Mock calendar client
    mock_calendar_client.return_value = MagicMock()

    # Test state
    service_ids = [s.id for s in sample_services]
    state = {
        "conversation_id": "test-123",
        "requested_services": service_ids,
        "requested_date": "2025-03-07",
        "preferred_stylist_id": None,
    }

    result = await check_availability(state)

    # Verify no slots found
    assert result["available_slots"] == []
    assert result["prioritized_slots"] == []

    # Verify alternatives suggested
    assert "suggested_dates" in result
    assert len(result["suggested_dates"]) == 2

    # Verify response mentions alternatives
    assert "no tenemos disponibilidad" in result["bot_response"].lower()
    assert "sábado 8 de marzo" in result["bot_response"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
