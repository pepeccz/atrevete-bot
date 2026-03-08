"""
Integration tests for Google Calendar API with real API calls.

Tests cover:
- Create event → query availability → verify busy slot → delete event
- Create holiday event → query availability → verify empty list
- Full workflow: create provisional → confirm → delete
- DB-first calendar: get_calendar_events_for_range N+1 fix verification

NOTE: Tests marked with @pytest.mark.skipif skip if Google credentials unavailable.
      Tests marked with @pytest.mark.skipif(SKIP_DB, ...) skip if DB is unavailable.

IMPORTANT: Tests clean up all created data after execution.
"""

import os
from datetime import datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text

from agent.tools.calendar_tools import (
    create_calendar_event,
    delete_calendar_event,
    get_calendar_availability,
)
from database.connection import AsyncSessionLocal
from database.models import (
    Appointment,
    AppointmentStatus,
    Service,
    ServiceCategory,
    Stylist,
)
from database.seeds.stylists import seed_stylists
from shared.config import get_settings

TIMEZONE = ZoneInfo("Europe/Madrid")

# Skip integration tests if Google credentials not configured
settings = get_settings()
SKIP_INTEGRATION = not os.path.exists(settings.GOOGLE_SERVICE_ACCOUNT_JSON)

# Skip DB-dependent tests if database is not reachable
try:
    import asyncio

    async def _check_db() -> bool:
        try:
            async with AsyncSessionLocal() as session:
                from sqlalchemy import text as _text

                await session.execute(_text("SELECT 1"))
            return True
        except Exception:
            return False

    SKIP_DB = not asyncio.get_event_loop().run_until_complete(_check_db())
except Exception:
    SKIP_DB = True


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


# ============================================================================
# DB-First Calendar: N+1 Fix Integration Tests (Task 3.1 & 3.2)
# ============================================================================


@pytest.mark.skipif(SKIP_DB, reason="Database not available")
@pytest.mark.asyncio
async def test_calendar_events_single_service_query():
    """
    Seed 5 real appointments with services, call get_calendar_events_for_range(),
    and verify all returned events have correct title containing service names.

    This proves the batch query works end-to-end: service names are resolved
    from the DB and appear in the event titles.
    """
    from agent.services.availability_service import get_calendar_events_for_range

    stylist_id = uuid4()
    start = datetime(2026, 3, 10, 9, 0, 0, tzinfo=TIMEZONE)
    end = datetime(2026, 3, 10, 20, 0, 0, tzinfo=TIMEZONE)

    async with AsyncSessionLocal() as session:
        # Create a minimal stylist
        stylist = Stylist(
            id=stylist_id,
            name="Test Stylist N1",
            category=ServiceCategory.HAIRDRESSING,
            is_active=True,
            google_calendar_id="test_n1@atrevete.com",
        )
        session.add(stylist)
        await session.flush()

        # Create a service
        svc = Service(
            id=uuid4(),
            name="Corte Test",
            category=ServiceCategory.HAIRDRESSING,
            duration_minutes=60,
        )
        session.add(svc)
        await session.flush()

        # Create 5 appointments referencing the service
        appts = []
        for i in range(5):
            appt = Appointment(
                id=uuid4(),
                stylist_id=stylist_id,
                customer_id=uuid4(),
                first_name=f"Cliente{i}",
                last_name="Test",
                start_time=start + timedelta(hours=i),
                duration_minutes=60,
                status=AppointmentStatus.CONFIRMED,
                service_ids=[svc.id],
            )
            session.add(appt)
            appts.append(appt)

        await session.commit()

    try:
        events = await get_calendar_events_for_range(
            stylist_ids=[stylist_id],
            start_time=start,
            end_time=end,
        )

        appt_events = [e for e in events if e["extendedProps"]["type"] == "appointment"]
        assert len(appt_events) == 5, f"Expected 5 appointment events, got {len(appt_events)}"

        # Every appointment event must include the service name in its title
        for event in appt_events:
            assert "Corte Test" in event["title"], (
                f"Expected 'Corte Test' in title, got: {event['title']}"
            )

    finally:
        # Cleanup
        async with AsyncSessionLocal() as session:
            for appt in appts:
                obj = await session.get(Appointment, appt.id)
                if obj:
                    await session.delete(obj)
            svc_obj = await session.get(Service, svc.id)
            if svc_obj:
                await session.delete(svc_obj)
            stylist_obj = await session.get(Stylist, stylist_id)
            if stylist_obj:
                await session.delete(stylist_obj)
            await session.commit()


@pytest.mark.skipif(SKIP_DB, reason="Database not available")
@pytest.mark.asyncio
async def test_calendar_events_deleted_service_graceful():
    """
    Seed an appointment whose service_id does NOT exist in the services table.
    get_calendar_events_for_range() must NOT raise an exception — the event
    is returned with an empty service name (graceful degradation).
    """
    from agent.services.availability_service import get_calendar_events_for_range

    stylist_id = uuid4()
    nonexistent_service_id = uuid4()  # Intentionally not inserted in DB
    start = datetime(2026, 3, 11, 9, 0, 0, tzinfo=TIMEZONE)
    end = datetime(2026, 3, 11, 20, 0, 0, tzinfo=TIMEZONE)

    async with AsyncSessionLocal() as session:
        stylist = Stylist(
            id=stylist_id,
            name="Test Stylist Deleted Svc",
            category=ServiceCategory.HAIRDRESSING,
            is_active=True,
            google_calendar_id="test_deleted_svc@atrevete.com",
        )
        session.add(stylist)
        await session.flush()

        appt = Appointment(
            id=uuid4(),
            stylist_id=stylist_id,
            customer_id=uuid4(),
            first_name="OrfanCita",
            last_name=None,
            start_time=start + timedelta(hours=1),
            duration_minutes=60,
            status=AppointmentStatus.CONFIRMED,
            service_ids=[nonexistent_service_id],
        )
        session.add(appt)
        await session.commit()

    try:
        # Must NOT raise — graceful degradation
        events = await get_calendar_events_for_range(
            stylist_ids=[stylist_id],
            start_time=start,
            end_time=end,
        )

        appt_events = [e for e in events if e["extendedProps"]["type"] == "appointment"]
        assert len(appt_events) == 1, f"Expected 1 event returned, got {len(appt_events)}"

        # Title is built even without service name
        assert "OrfanCita" in appt_events[0]["title"]

    finally:
        async with AsyncSessionLocal() as session:
            obj = await session.get(Appointment, appt.id)
            if obj:
                await session.delete(obj)
            stylist_obj = await session.get(Stylist, stylist_id)
            if stylist_obj:
                await session.delete(stylist_obj)
            await session.commit()
