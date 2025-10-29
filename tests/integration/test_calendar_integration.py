"""
Integration tests for Google Calendar API with real API calls.

Tests cover:
- Create event → query availability → verify busy slot → delete event
- Create holiday event → query availability → verify empty list
- Full workflow: create provisional → confirm → delete

NOTE: These tests use the REAL Google Calendar API with test credentials.
Requires:
- Google Service Account JSON key configured in .env (GOOGLE_SERVICE_ACCOUNT_JSON)
- Test Google Calendar IDs configured in .env (GOOGLE_CALENDAR_IDS)
- Stylists seeded in database with matching google_calendar_id values

IMPORTANT: Tests clean up all created events after execution.
Mark tests with @pytest.mark.skipif to skip if credentials unavailable.
"""

import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text

from agent.tools.calendar_tools import (
    create_calendar_event,
    delete_calendar_event,
    get_calendar_availability,
)
from database.connection import AsyncSessionLocal
from database.models import Stylist
from database.seeds.stylists import seed_stylists
from shared.config import get_settings

TIMEZONE = ZoneInfo("Europe/Madrid")

# Skip integration tests if Google credentials not configured
settings = get_settings()
SKIP_INTEGRATION = not os.path.exists(settings.GOOGLE_SERVICE_ACCOUNT_JSON)


@pytest.fixture(scope="function", autouse=True)
async def setup_database():
    """
    Setup test database: seed stylists for calendar integration.

    NOTE: Assumes migrations have been applied (alembic upgrade head).
    """
    # Clean stylists
    async with AsyncSessionLocal() as session:
        await session.execute(text("TRUNCATE stylists CASCADE"))
        await session.commit()

    # Seed stylists with Google Calendar IDs
    await seed_stylists()

    yield

    # Cleanup after test
    async with AsyncSessionLocal() as session:
        await session.execute(text("TRUNCATE stylists CASCADE"))
        await session.commit()


@pytest.mark.skipif(SKIP_INTEGRATION, reason="Google Calendar credentials not configured")
@pytest.mark.asyncio
async def test_create_event_detect_busy_delete():
    """
    Test full workflow: create event → detect busy slot → delete event.

    Steps:
    1. Query availability for Hairdressing (should have slots available)
    2. Create a provisional event at 10:00 AM tomorrow
    3. Query availability again → verify 10:00 slot is now busy
    4. Delete the event
    5. Verify event deletion successful
    """
    # Get a hairdressing stylist from database
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Stylist).where(
                Stylist.is_active == True,
                Stylist.category.in_(["Hairdressing", "Both"])
            ).limit(1)
        )
        stylist = result.scalar_one_or_none()

    assert stylist is not None, "No active hairdressing stylist found in database"

    # Calculate tomorrow at 10:00 AM
    tomorrow = datetime.now(TIMEZONE) + timedelta(days=1)
    tomorrow_date = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)
    date_str = tomorrow_date.strftime("%Y-%m-%d")
    start_time_str = tomorrow_date.isoformat()

    # Step 1: Check initial availability
    availability_before = await get_calendar_availability.ainvoke({
        "category": "Hairdressing",
        "date": date_str,
        "conversation_id": "test_integration"
    })

    assert availability_before["success"] is True
    initial_slot_count = len(availability_before["available_slots"])
    assert initial_slot_count > 0, "No available slots found"

    # Step 2: Create provisional event at 10:00
    create_result = await create_calendar_event.ainvoke({
        "stylist_id": str(stylist.id),
        "start_time": start_time_str,
        "duration_minutes": 30,
        "customer_name": "Test Customer",
        "service_names": "Test Service",
        "status": "provisional",
        "conversation_id": "test_integration"
    })

    assert create_result["success"] is True
    event_id = create_result["event_id"]

    try:
        # Step 3: Check availability again - 10:00 should be busy
        availability_after = await get_calendar_availability.ainvoke({
            "category": "Hairdressing",
            "date": date_str,
            "conversation_id": "test_integration"
        })

        assert availability_after["success"] is True

        # Verify 10:00 slot is now busy
        slot_times = [slot["time"] for slot in availability_after["available_slots"]]
        assert "10:00" not in slot_times, "10:00 slot should be busy after event creation"

        # Verify slot count decreased
        assert len(availability_after["available_slots"]) < initial_slot_count

    finally:
        # Step 4: Delete event (cleanup)
        delete_result = await delete_calendar_event.ainvoke({
            "stylist_id": str(stylist.id),
            "event_id": event_id,
            "conversation_id": "test_integration"
        })

        # Step 5: Verify deletion
        assert delete_result["success"] is True


@pytest.mark.skipif(SKIP_INTEGRATION, reason="Google Calendar credentials not configured")
@pytest.mark.asyncio
async def test_holiday_event_blocks_availability():
    """
    Test holiday event detection: create holiday → verify empty availability.

    Steps:
    1. Create a holiday event with "Festivo" in summary for tomorrow
    2. Query availability for tomorrow
    3. Verify empty availability list with holiday_detected=true
    4. Delete the holiday event (cleanup)
    """
    # Get any active stylist
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Stylist).where(Stylist.is_active == True).limit(1)
        )
        stylist = result.scalar_one_or_none()

    assert stylist is not None, "No active stylist found in database"

    # Calculate tomorrow
    tomorrow = datetime.now(TIMEZONE) + timedelta(days=1)
    tomorrow_start = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
    tomorrow_end = tomorrow.replace(hour=23, minute=59, second=59, microsecond=0)
    date_str = tomorrow_start.strftime("%Y-%m-%d")

    # Step 1: Create holiday event (all-day event)
    create_result = await create_calendar_event.ainvoke({
        "stylist_id": str(stylist.id),
        "start_time": tomorrow_start.isoformat(),
        "duration_minutes": 1439,  # Almost 24 hours (23:59)
        "customer_name": "SALON",
        "service_names": "Festivo - Test Holiday",
        "status": "confirmed",
        "conversation_id": "test_integration"
    })

    assert create_result["success"] is True
    event_id = create_result["event_id"]

    try:
        # Step 2: Query availability
        availability_result = await get_calendar_availability.ainvoke({
            "category": "Hairdressing",
            "date": date_str,
            "conversation_id": "test_integration"
        })

        # Step 3: Verify holiday detected
        assert availability_result["success"] is True
        assert availability_result.get("holiday_detected") is True
        assert len(availability_result["available_slots"]) == 0
        assert "Festivo" in availability_result.get("reason", "")

    finally:
        # Step 4: Delete holiday event (cleanup)
        delete_result = await delete_calendar_event.ainvoke({
            "stylist_id": str(stylist.id),
            "event_id": event_id,
            "conversation_id": "test_integration"
        })

        assert delete_result["success"] is True


@pytest.mark.skipif(SKIP_INTEGRATION, reason="Google Calendar credentials not configured")
@pytest.mark.asyncio
async def test_provisional_to_confirmed_workflow():
    """
    Test booking workflow: create provisional → confirm → delete.

    Steps:
    1. Create provisional event (yellow color)
    2. Verify event created with [PROVISIONAL] prefix
    3. Update to confirmed (would normally be a separate update, but we'll create a new confirmed one)
    4. Delete both events (cleanup)
    """
    # Get a stylist
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Stylist).where(Stylist.is_active == True).limit(1)
        )
        stylist = result.scalar_one_or_none()

    assert stylist is not None, "No active stylist found in database"

    # Calculate tomorrow at 14:00
    tomorrow = datetime.now(TIMEZONE) + timedelta(days=1)
    tomorrow_time = tomorrow.replace(hour=14, minute=0, second=0, microsecond=0)
    start_time_str = tomorrow_time.isoformat()

    # Step 1: Create provisional event
    provisional_result = await create_calendar_event.ainvoke({
        "stylist_id": str(stylist.id),
        "start_time": start_time_str,
        "duration_minutes": 60,
        "customer_name": "María González",
        "service_names": "Corte y tinte",
        "status": "provisional",
        "appointment_id": "test-appt-123",
        "customer_id": "test-cust-456",
        "conversation_id": "test_integration"
    })

    assert provisional_result["success"] is True
    assert "[PROVISIONAL]" in provisional_result["summary"]
    provisional_event_id = provisional_result["event_id"]

    try:
        # Step 2: Create confirmed event (simulating confirmation)
        confirmed_result = await create_calendar_event.ainvoke({
            "stylist_id": str(stylist.id),
            "start_time": start_time_str,
            "duration_minutes": 60,
            "customer_name": "María González",
            "service_names": "Corte y tinte",
            "status": "confirmed",
            "appointment_id": "test-appt-123",
            "customer_id": "test-cust-456",
            "conversation_id": "test_integration"
        })

        assert confirmed_result["success"] is True
        assert "[PROVISIONAL]" not in confirmed_result["summary"]
        confirmed_event_id = confirmed_result["event_id"]

        # Verify both events created successfully
        assert provisional_event_id != confirmed_event_id

    finally:
        # Step 3: Delete both events (cleanup)
        delete_provisional = await delete_calendar_event.ainvoke({
            "stylist_id": str(stylist.id),
            "event_id": provisional_event_id,
            "conversation_id": "test_integration"
        })

        delete_confirmed = await delete_calendar_event.ainvoke({
            "stylist_id": str(stylist.id),
            "event_id": confirmed_event_id,
            "conversation_id": "test_integration"
        })

        assert delete_provisional["success"] is True
        assert delete_confirmed["success"] is True


@pytest.mark.skipif(SKIP_INTEGRATION, reason="Google Calendar credentials not configured")
@pytest.mark.asyncio
async def test_delete_nonexistent_event():
    """
    Test deleting an event that doesn't exist (should succeed gracefully).

    Steps:
    1. Attempt to delete a non-existent event ID
    2. Verify operation succeeds (404 treated as success)
    """
    # Get a stylist
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(Stylist).where(Stylist.is_active == True).limit(1)
        )
        stylist = result.scalar_one_or_none()

    assert stylist is not None, "No active stylist found in database"

    # Try to delete non-existent event
    delete_result = await delete_calendar_event.ainvoke({
        "stylist_id": str(stylist.id),
        "event_id": "nonexistent_event_id_12345",
        "conversation_id": "test_integration"
    })

    # Should succeed gracefully (404 = already deleted)
    assert delete_result["success"] is True
