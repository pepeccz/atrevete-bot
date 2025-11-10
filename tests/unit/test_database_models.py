"""
Unit tests for database models and migrations.

Tests cover:
- Model creation and field validation
- Foreign key relationships
- CHECK constraints
- Unique constraints
- Indexes
- Seed data script execution
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from database.connection import AsyncSessionLocal, engine
from database.models import Base, Customer, Service, ServiceCategory, Stylist  # Pack removed - packs functionality eliminated
from database.seeds.stylists import seed_stylists


@pytest.fixture(scope="function", autouse=True)
async def setup_database():
    """
    Setup test database: create all tables before each test.
    Clean up after each test.
    """
    # Create all tables
    async with engine.begin() as conn:
        # Drop existing tables
        await conn.run_sync(Base.metadata.drop_all)

        # Enable extensions FIRST (before creating tables)
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "pg_trgm"'))

        # Now create fresh tables (which depend on extensions)
        await conn.run_sync(Base.metadata.create_all)

        # Create trigger function
        await conn.execute(
            text("""
            CREATE OR REPLACE FUNCTION update_updated_at_column()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = NOW();
                RETURN NEW;
            END;
            $$ language 'plpgsql';
        """)
        )

        # Apply triggers
        for table in ["stylists", "services", "packs"]:
            # Drop trigger if exists (separate statement)
            await conn.execute(
                text(f"DROP TRIGGER IF EXISTS update_{table}_updated_at ON {table}")
            )
            # Create trigger (separate statement)
            await conn.execute(
                text(f"""
                CREATE TRIGGER update_{table}_updated_at
                BEFORE UPDATE ON {table}
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column()
            """)
            )

    yield

    # No cleanup needed - next test will drop/recreate


@pytest.fixture
async def session():
    """
    Create a fresh database session for each test.

    Automatically rolls back after each test.
    """
    async with AsyncSessionLocal() as session:
        yield session
        await session.rollback()


# ============================================================================
# Stylist Model Tests
# ============================================================================


@pytest.mark.asyncio
async def test_create_stylist(session):
    """Test creating a stylist with all fields."""
    stylist = Stylist(
        name="Test Stylist",
        category=ServiceCategory.HAIRDRESSING,
        google_calendar_id="test@atrevete.com",
        is_active=True,
        metadata_={"skills": ["haircut", "color"]},
    )
    session.add(stylist)
    await session.commit()

    # Verify UUID was generated
    assert stylist.id is not None
    assert stylist.name == "Test Stylist"
    assert stylist.category == ServiceCategory.HAIRDRESSING
    assert stylist.google_calendar_id == "test@atrevete.com"
    assert stylist.is_active is True
    assert stylist.metadata_ == {"skills": ["haircut", "color"]}
    assert stylist.created_at is not None
    assert stylist.updated_at is not None


@pytest.mark.asyncio
async def test_stylist_unique_calendar_id(session):
    """Test that google_calendar_id must be unique."""
    stylist1 = Stylist(
        name="Stylist 1",
        category=ServiceCategory.HAIRDRESSING,
        google_calendar_id="duplicate@atrevete.com",
    )
    session.add(stylist1)
    await session.commit()

    # Try to create another stylist with same calendar ID
    stylist2 = Stylist(
        name="Stylist 2",
        category=ServiceCategory.AESTHETICS,
        google_calendar_id="duplicate@atrevete.com",
    )
    session.add(stylist2)

    with pytest.raises(IntegrityError):
        await session.commit()


# ============================================================================
# Customer Model Tests
# ============================================================================


@pytest.mark.asyncio
async def test_create_customer_with_stylist(session):
    """Test creating a customer with preferred stylist."""
    # First create a stylist
    stylist = Stylist(
        name="Preferred Stylist",
        category=ServiceCategory.BOTH,
        google_calendar_id="preferred@atrevete.com",
    )
    session.add(stylist)
    await session.flush()

    # Create customer with preferred stylist
    customer = Customer(
        phone="+34612345678",
        first_name="John",
        last_name="Doe",
        preferred_stylist_id=stylist.id,
        total_spent=Decimal("150.50"),
        metadata_={"whatsapp_name": "Johnny"},
    )
    session.add(customer)
    await session.commit()

    # Verify relationship
    assert customer.preferred_stylist is not None
    assert customer.preferred_stylist.name == "Preferred Stylist"
    assert customer.phone == "+34612345678"
    assert customer.total_spent == Decimal("150.50")


@pytest.mark.asyncio
async def test_customer_phone_validation(session):
    """Test that phone number must be at least 10 characters."""
    customer = Customer(
        phone="+34123",  # Too short (8 chars)
        first_name="Test",
    )
    session.add(customer)

    with pytest.raises(IntegrityError) as exc_info:
        await session.commit()
    assert "check_phone_length" in str(exc_info.value)


@pytest.mark.asyncio
async def test_customer_unique_phone(session):
    """Test that phone number must be unique."""
    customer1 = Customer(phone="+34611111111", first_name="Customer 1")
    session.add(customer1)
    await session.commit()

    customer2 = Customer(phone="+34611111111", first_name="Customer 2")
    session.add(customer2)

    with pytest.raises(IntegrityError):
        await session.commit()


@pytest.mark.asyncio
async def test_customer_stylist_on_delete_set_null(session):
    """Test that deleting a stylist sets preferred_stylist_id to NULL."""
    stylist = Stylist(
        name="Temp Stylist",
        category=ServiceCategory.HAIRDRESSING,
        google_calendar_id="temp@atrevete.com",
    )
    session.add(stylist)
    await session.flush()

    customer = Customer(
        phone="+34622222222",
        first_name="Test",
        preferred_stylist_id=stylist.id,
    )
    session.add(customer)
    await session.commit()

    # Delete the stylist
    await session.delete(stylist)
    await session.commit()

    # Refresh customer and check preferred_stylist_id is NULL
    await session.refresh(customer)
    assert customer.preferred_stylist_id is None


# ============================================================================
# Service Model Tests
# ============================================================================


@pytest.mark.asyncio
async def test_create_service(session):
    """Test creating a service with all fields."""
    service = Service(
        name="Corte de pelo",
        category=ServiceCategory.HAIRDRESSING,
        duration_minutes=60,
        description="Haircut service",
        is_active=True,
    )
    session.add(service)
    await session.commit()

    assert service.id is not None
    assert service.name == "Corte de pelo"
    assert service.duration_minutes == 60
    assert service.description == "Haircut service"


@pytest.mark.asyncio
async def test_service_check_duration_positive(session):
    """Test that duration_minutes must be > 0."""
    service = Service(
        name="Invalid Service",
        category=ServiceCategory.HAIRDRESSING,
        duration_minutes=0,  # Invalid: must be > 0
    )
    session.add(service)

    with pytest.raises(IntegrityError) as exc_info:
        await session.commit()
    assert "check_duration_positive" in str(exc_info.value)


# ============================================================================
# Pack Model Tests - REMOVED (packs functionality eliminated)
# ============================================================================


# Seed Data Tests
# ============================================================================


@pytest.mark.asyncio
async def test_seed_stylists():
    """Test that seed script creates 5 stylists."""
    # Run seed script
    await seed_stylists()

    # Query all stylists
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Stylist))
        stylists = result.scalars().all()

        # Verify 5 stylists created
        assert len(stylists) >= 5  # >= because other tests may have created stylists

        # Verify specific stylists exist
        stylist_names = {s.name for s in stylists}
        assert "Pilar" in stylist_names
        assert "Marta" in stylist_names
        assert "Rosa" in stylist_names
        assert "Harol" in stylist_names
        assert "Víctor" in stylist_names

        # Verify categories
        pilar = next(s for s in stylists if s.name == "Pilar")
        assert pilar.category == ServiceCategory.HAIRDRESSING

        marta = next(s for s in stylists if s.name == "Marta")
        assert marta.category == ServiceCategory.BOTH


@pytest.mark.asyncio
async def test_seed_stylists_idempotent():
    """Test that running seed script twice doesn't create duplicates."""
    # Run seed script twice
    await seed_stylists()
    await seed_stylists()

    # Query all stylists
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Stylist))
        stylists = result.scalars().all()

        # Verify no duplicates (should still have only base count + 5)
        stylist_names = [s.name for s in stylists]
        assert stylist_names.count("Pilar") == 1
        assert stylist_names.count("Marta") == 1


# ============================================================================
# Index Tests
# ============================================================================


@pytest.mark.asyncio
async def test_customer_phone_index_exists(session):
    """Test that phone index exists for fast customer lookup."""
    # Get indexes for customers table (inspector must be created inside run_sync)
    async with engine.connect() as conn:
        indexes = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_indexes("customers")
        )

    # Check for phone index
    phone_indexes = [
        idx for idx in indexes
        if (name := idx.get("name")) is not None and "phone" in name
    ]
    assert len(phone_indexes) > 0
    assert phone_indexes[0]["unique"] is True


@pytest.mark.asyncio
async def test_stylist_calendar_id_index_exists(session):
    """Test that google_calendar_id index exists."""
    # Get indexes for stylists table (inspector must be created inside run_sync)
    async with engine.connect() as conn:
        indexes = await conn.run_sync(
            lambda sync_conn: inspect(sync_conn).get_indexes("stylists")
        )

    calendar_indexes = [
        idx for idx in indexes
        if (name := idx.get("name")) is not None and "google_calendar_id" in name
    ]
    assert len(calendar_indexes) > 0
    assert calendar_indexes[0]["unique"] is True
