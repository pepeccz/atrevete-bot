"""
Integration tests for customer tools with real database operations.

Tests cover full lifecycle scenarios:
- Create customer → query by phone → update name → verify persistence
- Create customer → update preferences → query → verify
- Create customer → create appointment → get history → verify ordering

NOTE: These tests use the real PostgreSQL database (test environment).
They assume migrations have been applied (alembic upgrade head).
"""

from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text

from agent.tools.customer_tools import (
    create_customer,
    get_customer_by_phone,
    get_customer_history,
    update_customer_name,
    update_customer_preferences,
)
from database.connection import AsyncSessionLocal
from database.models import Appointment, AppointmentStatus, PaymentStatus, Service, Stylist
from database.seeds.services import seed_services
from database.seeds.stylists import seed_stylists


@pytest.fixture(scope="function", autouse=True)
async def setup_database():
    """
    Setup test database: clean existing data and seed dependencies.

    NOTE: Assumes migrations have been applied (alembic upgrade head).
    """
    # Clean existing data (truncate tables in reverse dependency order)
    async with AsyncSessionLocal() as session:
        await session.execute(text("TRUNCATE conversation_history, appointments, policies, packs, services, customers, stylists CASCADE"))
        await session.commit()

    # Seed dependencies (stylists, services)
    await seed_stylists()
    await seed_services()

    yield

    # Cleanup after test
    async with AsyncSessionLocal() as session:
        await session.execute(text("TRUNCATE conversation_history, appointments, policies, packs, services, customers, stylists CASCADE"))
        await session.commit()


@pytest.mark.asyncio
async def test_customer_lifecycle_create_query_update_verify():
    """
    Test full customer lifecycle: create → query → update → verify persistence.

    Sequence:
    1. Create customer with phone and name
    2. Query customer by phone to verify creation
    3. Update customer name
    4. Query again to verify name update persisted
    """
    # Step 1: Create customer
    create_result = await create_customer.ainvoke({
        "phone": "612345678",  # Will be normalized to +34612345678
        "first_name": "María",
        "last_name": "González"
    })

    assert "error" not in create_result
    assert create_result["phone"] == "+34612345678"
    assert create_result["first_name"] == "María"
    assert create_result["last_name"] == "González"
    customer_id = create_result["id"]

    # Step 2: Query by phone to verify creation
    query_result = await get_customer_by_phone.ainvoke({"phone": "+34612345678"})

    assert query_result is not None
    assert query_result["id"] == customer_id
    assert query_result["first_name"] == "María"
    assert query_result["last_name"] == "González"

    # Step 3: Update customer name
    update_result = await update_customer_name.ainvoke({
        "customer_id": customer_id,
        "first_name": "María Carmen",
        "last_name": "González Pérez"
    })

    assert update_result["success"] is True
    assert update_result["first_name"] == "María Carmen"
    assert update_result["last_name"] == "González Pérez"

    # Step 4: Query again to verify persistence
    verify_result = await get_customer_by_phone.ainvoke({"phone": "+34612345678"})

    assert verify_result is not None
    assert verify_result["first_name"] == "María Carmen"
    assert verify_result["last_name"] == "González Pérez"


@pytest.mark.asyncio
async def test_customer_lifecycle_create_update_preferences_verify():
    """
    Test customer preferences lifecycle: create → update preferences → verify.

    Sequence:
    1. Create customer
    2. Update preferred stylist
    3. Query to verify preference persisted
    """
    # Step 1: Create customer
    create_result = await create_customer.ainvoke({
        "phone": "+34623456789",
        "first_name": "Carlos",
        "last_name": "Rodríguez"
    })

    assert "error" not in create_result
    customer_id = create_result["id"]

    # Step 2: Get a stylist from seed data
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Stylist).limit(1))
        stylist = result.scalar_one()
        stylist_id = str(stylist.id)

    # Step 3: Update customer preferences
    update_result = await update_customer_preferences.ainvoke({
        "customer_id": customer_id,
        "preferred_stylist_id": stylist_id
    })

    assert update_result["success"] is True
    assert update_result["preferred_stylist_id"] == stylist_id

    # Step 4: Query to verify preference persisted
    verify_result = await get_customer_by_phone.ainvoke({"phone": "+34623456789"})

    assert verify_result is not None
    assert verify_result["preferred_stylist_id"] == stylist_id


@pytest.mark.asyncio
async def test_customer_lifecycle_create_appointment_get_history_verify():
    """
    Test customer appointment history: create customer → create appointments → get history.

    Sequence:
    1. Create customer
    2. Create multiple appointments for the customer
    3. Get customer history
    4. Verify appointments are ordered by most recent first
    5. Verify limit parameter works
    """
    # Step 1: Create customer
    create_result = await create_customer.ainvoke({
        "phone": "+34634567890",
        "first_name": "Ana",
        "last_name": "Martín"
    })

    assert "error" not in create_result
    customer_id = create_result["id"]

    # Step 2: Create appointments directly in database
    async with AsyncSessionLocal() as session:
        # Get stylist and service from seed data
        stylist_result = await session.execute(select(Stylist).limit(1))
        stylist = stylist_result.scalar_one()

        service_result = await session.execute(select(Service).where(Service.name == "MECHAS"))
        service = service_result.scalar_one()

        # Create 3 appointments with different dates
        appointments_data = [
            {
                "start_time": datetime(2025, 10, 15, 10, 0, 0, tzinfo=ZoneInfo("Europe/Madrid")),
                "price": Decimal("50.00")
            },
            {
                "start_time": datetime(2025, 10, 20, 14, 0, 0, tzinfo=ZoneInfo("Europe/Madrid")),
                "price": Decimal("60.00")
            },
            {
                "start_time": datetime(2025, 10, 25, 16, 30, 0, tzinfo=ZoneInfo("Europe/Madrid")),
                "price": Decimal("75.00")
            },
        ]

        for apt_data in appointments_data:
            appointment = Appointment(
                customer_id=customer_id,
                stylist_id=stylist.id,
                service_ids=[service.id],
                start_time=apt_data["start_time"],
                duration_minutes=service.duration_minutes,
                total_price=apt_data["price"],
                advance_payment_amount=Decimal("0.00"),
                payment_status=PaymentStatus.CONFIRMED,
                status=AppointmentStatus.COMPLETED,
            )
            session.add(appointment)

        await session.commit()

    # Step 3: Get customer history (all appointments)
    history_result = await get_customer_history.ainvoke({
        "customer_id": customer_id,
        "limit": 5
    })

    assert "error" not in history_result
    assert len(history_result["appointments"]) == 3

    # Step 4: Verify ordering (most recent first)
    appointments = history_result["appointments"]
    assert appointments[0]["total_price"] == 75.00  # Oct 25 (most recent)
    assert appointments[1]["total_price"] == 60.00  # Oct 20
    assert appointments[2]["total_price"] == 50.00  # Oct 15 (oldest)

    # Step 5: Verify limit parameter works
    limited_result = await get_customer_history.ainvoke({
        "customer_id": customer_id,
        "limit": 2
    })

    assert len(limited_result["appointments"]) == 2
    assert limited_result["appointments"][0]["total_price"] == 75.00  # Most recent
    assert limited_result["appointments"][1]["total_price"] == 60.00  # Second most recent


@pytest.mark.asyncio
async def test_duplicate_phone_number_constraint():
    """
    Test that creating a customer with duplicate phone number fails gracefully.
    """
    # Create first customer
    first_result = await create_customer.ainvoke({
        "phone": "+34645678901",
        "first_name": "Pedro",
        "last_name": "López"
    })

    assert "error" not in first_result

    # Attempt to create second customer with same phone
    second_result = await create_customer.ainvoke({
        "phone": "+34645678901",  # Same phone
        "first_name": "Juan",
        "last_name": "García"
    })

    assert "error" in second_result
    assert "already exists" in second_result["error"]


@pytest.mark.asyncio
async def test_invalid_stylist_id_foreign_key_constraint():
    """
    Test that updating customer preferences with invalid stylist_id fails gracefully.
    """
    # Create customer
    create_result = await create_customer.ainvoke({
        "phone": "+34656789012",
        "first_name": "Laura",
        "last_name": "Fernández"
    })

    assert "error" not in create_result
    customer_id = create_result["id"]

    # Attempt to set invalid stylist_id
    import uuid
    invalid_stylist_id = str(uuid.uuid4())  # Random UUID that doesn't exist

    update_result = await update_customer_preferences.ainvoke({
        "customer_id": customer_id,
        "preferred_stylist_id": invalid_stylist_id
    })

    assert "error" in update_result
    assert "stylist does not exist" in update_result["error"]


@pytest.mark.asyncio
async def test_phone_normalization_consistency():
    """
    Test that phone number normalization is consistent across different formats.
    """
    # Create customer with phone without country code
    create_result = await create_customer.ainvoke({
        "phone": "667890123",  # No +34 prefix
        "first_name": "Sofía",
        "last_name": "Ruiz"
    })

    assert "error" not in create_result
    assert create_result["phone"] == "+34667890123"

    # Query with different format (with prefix and spaces)
    query_result = await get_customer_by_phone.ainvoke({
        "phone": "+34 667 89 01 23"  # Same phone with spaces
    })

    assert query_result is not None
    assert query_result["first_name"] == "Sofía"
    assert query_result["phone"] == "+34667890123"


@pytest.mark.asyncio
async def test_customer_not_found_returns_none():
    """
    Test that querying non-existent customer returns None.
    """
    result = await get_customer_by_phone.ainvoke({
        "phone": "+34699999999"  # Non-existent but valid format Spanish mobile
    })

    assert result is None


@pytest.mark.asyncio
async def test_empty_last_name_handling():
    """
    Test that customers can be created with empty last name.
    """
    create_result = await create_customer.ainvoke({
        "phone": "+34678901234",
        "first_name": "Miguel",
        "last_name": ""  # Empty last name
    })

    assert "error" not in create_result
    assert create_result["first_name"] == "Miguel"
    assert create_result["last_name"] == ""

    # Verify persistence
    query_result = await get_customer_by_phone.ainvoke({"phone": "+34678901234"})

    assert query_result is not None
    assert query_result["last_name"] == ""
