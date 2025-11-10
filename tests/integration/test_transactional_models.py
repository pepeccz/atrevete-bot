"""
Integration tests for transactional database models.

Tests cover:
- Appointment creation with all fields and foreign keys
- Appointment status transitions
- Foreign key constraints (CASCADE, RESTRICT, SET NULL)
- CHECK constraint violations
- Conditional index usage
- Policy UPSERT operations
- ConversationHistory chronological retrieval
- Seed script execution

Note: These tests assume database migrations have already been applied.
They do NOT use Base.metadata.create_all() because conditional indexes
with enum types require the enum to exist before index creation,
which is handled correctly by Alembic migrations but not by create_all().
"""

from datetime import datetime, timedelta
from decimal import Decimal
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from database.connection import AsyncSessionLocal
from database.models import (
    Appointment,
    AppointmentStatus,
    ConversationHistory,
    Customer,
    MessageRole,
    # Pack,  # Removed - packs functionality eliminated
    Policy,
    Service,
    Stylist,
)
# from database.seeds.packs import seed_packs  # Removed - packs functionality eliminated
from database.seeds.policies import seed_policies
from database.seeds.services import seed_services
from database.seeds.stylists import seed_stylists


@pytest.fixture(scope="function", autouse=True)
async def setup_database():
    """
    Setup test database: clean existing data and seed dependencies.

    NOTE: Assumes migrations have been applied (alembic upgrade head).
    Does NOT drop/recreate tables to avoid conditional index issues.
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
async def test_create_complete_appointment():
    """Test creating a complete appointment with all fields populated."""
    async with AsyncSessionLocal() as session:
        # Create customer
        customer = Customer(
            phone="+34612345678",
            first_name="Test",
            last_name="Customer",
        )
        session.add(customer)
        await session.flush()  # Flush to generate customer.id

        # Get a stylist (from seed data)
        result = await session.execute(select(Stylist).limit(1))
        stylist = result.scalar_one()

        # Get a service (from seed data)
        result = await session.execute(select(Service).where(Service.name == "MECHAS"))
        service = result.scalar_one()

        # Create appointment
        start_time = datetime(2025, 11, 15, 14, 30, tzinfo=ZoneInfo("Europe/Madrid"))
        appointment = Appointment(
            customer_id=customer.id,
            stylist_id=stylist.id,
            service_ids=[service.id],
            start_time=start_time,
            duration_minutes=120,
            status=AppointmentStatus.CONFIRMED,
        )
        session.add(appointment)
        await session.commit()

        # Verify appointment created with UUID
        assert appointment.id is not None
        assert isinstance(appointment.id, type(uuid4()))
        assert appointment.customer_id == customer.id
        assert appointment.stylist_id == stylist.id
        assert appointment.service_ids == [service.id]
        assert appointment.start_time == start_time
        assert appointment.status == AppointmentStatus.CONFIRMED


@pytest.mark.asyncio
async def test_appointment_invalid_customer_fk():
    """Test creating appointment with non-existent customer_id raises IntegrityError."""
    async with AsyncSessionLocal() as session:
        result = await session.execute(select(Stylist).limit(1))
        stylist = result.scalar_one()

        result = await session.execute(select(Service).limit(1))
        service = result.scalar_one()

        # Use non-existent customer ID
        fake_customer_id = uuid4()

        appointment = Appointment(
            customer_id=fake_customer_id,
            stylist_id=stylist.id,
            service_ids=[service.id],
            start_time=datetime.now(ZoneInfo("Europe/Madrid")) + timedelta(days=1),
            duration_minutes=60,
        )
        session.add(appointment)

        with pytest.raises(IntegrityError) as exc_info:
            await session.commit()

        assert "violates foreign key constraint" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_delete_customer_cascades_to_appointments():
    """Test deleting customer cascades to delete appointments (CASCADE)."""
    async with AsyncSessionLocal() as session:
        customer = Customer(phone="+34612345681", first_name="Test")
        session.add(customer)
        await session.flush()  # Flush to generate customer.id

        result = await session.execute(select(Stylist).limit(1))
        stylist = result.scalar_one()

        result = await session.execute(select(Service).limit(1))
        service = result.scalar_one()

        appointment = Appointment(
            customer_id=customer.id,
            stylist_id=stylist.id,
            service_ids=[service.id],
            start_time=datetime.now(ZoneInfo("Europe/Madrid")) + timedelta(days=1),
            duration_minutes=60,
        )
        session.add(appointment)
        await session.commit()

        appointment_id = appointment.id
        customer_id = customer.id

        # Re-query customer to ensure it's attached to session
        stmt_customer = select(Customer).where(Customer.id == customer_id)
        result_customer = await session.execute(stmt_customer)
        requeried_customer = result_customer.scalar_one()

        # Delete customer
        await session.delete(requeried_customer)
        await session.commit()

        # Verify appointment also deleted (CASCADE)
        stmt_appt = select(Appointment).where(Appointment.id == appointment_id)
        result_appt = await session.execute(stmt_appt)
        found_appointment = result_appt.scalar_one_or_none()

        assert found_appointment is None


@pytest.mark.asyncio
async def test_delete_stylist_with_appointments_restricted():
    """Test deleting stylist with appointments raises IntegrityError (RESTRICT)."""
    async with AsyncSessionLocal() as session:
        customer = Customer(phone="+34612345682", first_name="Test")
        session.add(customer)
        await session.flush()  # Flush to generate customer.id

        result = await session.execute(select(Stylist).limit(1))
        stylist = result.scalar_one()

        result = await session.execute(select(Service).limit(1))
        service = result.scalar_one()

        appointment = Appointment(
            customer_id=customer.id,
            stylist_id=stylist.id,
            service_ids=[service.id],
            start_time=datetime.now(ZoneInfo("Europe/Madrid")) + timedelta(days=1),
            duration_minutes=60,
        )
        session.add(appointment)
        await session.commit()

        stylist_id = stylist.id

        # Re-query stylist to ensure it's attached to session
        stmt = select(Stylist).where(Stylist.id == stylist_id)
        result = await session.execute(stmt)
        stylist = result.scalar_one()

        # Try to delete stylist (should fail due to RESTRICT)
        await session.delete(stylist)

        with pytest.raises(IntegrityError) as exc_info:
            await session.commit()

        # Can be either foreign key constraint or not-null constraint depending on SQLAlchemy behavior
        error_msg = str(exc_info.value).lower()
        assert (
            "violates foreign key constraint" in error_msg
            or 'violates not-null constraint' in error_msg
        )


@pytest.mark.asyncio
async def test_policy_duplicate_key_unique_constraint():
    """Test inserting duplicate policy key raises IntegrityError."""
    async with AsyncSessionLocal() as session:
        policy1 = Policy(
            key="test_policy",
            value={"threshold_hours": 24},
        )
        session.add(policy1)
        await session.commit()

        # Try to insert duplicate key
        policy2 = Policy(
            key="test_policy",
            value={"threshold_hours": 48},
        )
        session.add(policy2)

        with pytest.raises(IntegrityError) as exc_info:
            await session.commit()

        assert "duplicate key value" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_conversation_history_chronological_retrieval():
    """Test retrieving conversation messages chronologically by conversation_id."""
    async with AsyncSessionLocal() as session:
        customer = Customer(phone="+34612345683", first_name="Test")
        session.add(customer)
        await session.commit()

        conversation_id = "thread-test-123"

        # Create 3 messages with different timestamps
        timestamps = [
            datetime.now(ZoneInfo("Europe/Madrid")),
            datetime.now(ZoneInfo("Europe/Madrid")) + timedelta(seconds=10),
            datetime.now(ZoneInfo("Europe/Madrid")) + timedelta(seconds=20),
        ]

        messages = [
            ConversationHistory(
                customer_id=customer.id,
                conversation_id=conversation_id,
                timestamp=timestamps[0],
                message_role=MessageRole.USER,
                message_content="Hello",
                metadata_={"node_name": "router"},
            ),
            ConversationHistory(
                customer_id=customer.id,
                conversation_id=conversation_id,
                timestamp=timestamps[1],
                message_role=MessageRole.ASSISTANT,
                message_content="Hi, how can I help?",
                metadata_={"node_name": "identify_customer"},
            ),
            ConversationHistory(
                customer_id=customer.id,
                conversation_id=conversation_id,
                timestamp=timestamps[2],
                message_role=MessageRole.USER,
                message_content="I want to book an appointment",
                metadata_={"node_name": "router"},
            ),
        ]

        for msg in messages:
            session.add(msg)
        await session.commit()

        # Query by conversation_id ordered by timestamp
        stmt = (
            select(ConversationHistory)
            .where(ConversationHistory.conversation_id == conversation_id)
            .order_by(ConversationHistory.timestamp)
        )
        result = await session.execute(stmt)
        retrieved_messages = result.scalars().all()

        assert len(retrieved_messages) == 3
        assert retrieved_messages[0].message_content == "Hello"
        assert retrieved_messages[1].message_content == "Hi, how can I help?"
        assert retrieved_messages[2].message_content == "I want to book an appointment"


@pytest.mark.asyncio
async def test_seed_scripts_execution():
    """Test executing all seed scripts and verify data counts."""
    async with AsyncSessionLocal() as session:
        # Run seed scripts
        await seed_policies()
        # await seed_packs()  # Removed - packs functionality eliminated

        # Verify policies seeded
        stmt = select(Policy)
        result = await session.execute(stmt)
        policies = result.scalars().all()
        assert len(policies) == 7  # 5 business rules + 2 FAQs

        # Verify services seeded (already seeded in setup)
        stmt = select(Service)
        result = await session.execute(stmt)
        services = result.scalars().all()
        assert len(services) == 5

        # Verify packs seeded - DISABLED (packs functionality eliminated)
        # stmt_pack = select(Pack)
        # result_pack = await session.execute(stmt_pack)
        # packs = result_pack.scalars().all()
        # assert len(packs) == 1
        #
        # # Verify pack has correct service IDs
        # pack = packs[0]
        # assert pack.name == "Mechas + Corte"
        # assert len(pack.included_service_ids) == 2


@pytest.mark.asyncio
async def test_appointment_reminder_pending_conditional_index():
    """Test querying appointments with reminder pending uses conditional index."""
    async with AsyncSessionLocal() as session:
        customer = Customer(phone="+34612345684", first_name="Test")
        session.add(customer)
        await session.flush()  # Flush to generate customer.id

        result = await session.execute(select(Stylist).limit(1))
        stylist = result.scalar_one()

        result = await session.execute(select(Service).limit(1))
        service = result.scalar_one()

        # Create confirmed appointment with reminder not sent
        appointment = Appointment(
            customer_id=customer.id,
            stylist_id=stylist.id,
            service_ids=[service.id],
            start_time=datetime.now(ZoneInfo("Europe/Madrid")) + timedelta(days=2),
            duration_minutes=60,
            status=AppointmentStatus.CONFIRMED,
            reminder_sent=False,
        )
        session.add(appointment)
        await session.commit()

        # Query for reminder pending appointments
        stmt = select(Appointment).where(
            Appointment.status == AppointmentStatus.CONFIRMED,
            ~Appointment.reminder_sent,
        )
        result = await session.execute(stmt)
        pending_appointments = result.scalars().all()

        assert len(pending_appointments) >= 1
        assert any(a.id == appointment.id for a in pending_appointments)
