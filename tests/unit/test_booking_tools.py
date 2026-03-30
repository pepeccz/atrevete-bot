"""
Unit tests for booking_tools module.

Tests service query functions.
Note: Payment/pricing functionality eliminated November 10, 2025.
Note: Pack-related tests disabled - packs functionality eliminated.
"""

from uuid import uuid4

import pytest
from sqlalchemy import select, text

from agent.tools.booking_tools import get_service_by_name
from database.connection import engine
from database.models import Base, Service, ServiceCategory
from database.seeds.services import seed_services


@pytest.fixture(scope="function", autouse=True)
async def setup_database():
    """
    Setup test database: create all tables and seed data before each test.
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

    # Seed services for tests (packs removed)
    await seed_services()
    # await seed_packs()  # Removed - packs functionality eliminated

    yield

    # Cleanup after test
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
class TestGetServiceByName:
    """Test get_service_by_name function with exact and fuzzy search."""

    async def test_exact_search_mechas(self):
        """Test exact search for 'mechas' matches 'Mechas'."""
        # Arrange: Query should find Mechas service (from PDF catalog)
        # (Service already exists from seed data)

        # Act
        services = await get_service_by_name("mechas", fuzzy=False)

        # Assert - function returns a list
        assert len(services) > 0, "Service 'Mechas' should be found"
        assert services[0].name == "Mechas"
        assert services[0].duration_minutes == 60

    async def test_fuzzy_search_with_typo(self):
        """Test fuzzy search with typo 'mecha' matches 'Mechas'."""
        # Act
        services = await get_service_by_name("mecha", fuzzy=True)

        # Assert - function returns a list
        assert len(services) > 0, "Fuzzy search should find 'Mechas'"
        assert services[0].name == "Mechas"

    async def test_case_insensitive_search(self):
        """Test case-insensitive search with different casing."""
        # Act - "Cortar" is the new name in PDF catalog (was "Corte de pelo")
        services = await get_service_by_name("CORTAR", fuzzy=False)

        # Assert - function returns a list
        assert len(services) > 0
        assert services[0].name == "Cortar"

    async def test_service_not_found(self):
        """Test search returns empty list for non-existent service."""
        # Act
        services = await get_service_by_name("nonexistent_service_xyz", fuzzy=False)

        # Assert - function returns empty list, not None
        assert len(services) == 0, "Non-existent service should return empty list"

    async def test_fuzzy_search_no_match_below_threshold(self):
        """Test fuzzy search returns empty list when similarity is below threshold."""
        # Act: Search with very different string
        services = await get_service_by_name("xyz123", fuzzy=True)

        # Assert - function returns empty list, not None
        assert len(services) == 0, "Very different string should not match"

    async def test_verify_all_pdf_services_present(self):
        """Test all expected services from PDF catalog are seeded."""
        # Arrange: Expected service names from updated PDF catalog (77 services)
        expected_services = {
            # Peluquería services (sample of key services)
            "Óleo Pigmento",
            "Agua Tierra",
            "Corte de Flequillo",
            "Perilla",
            "Tratamiento Precolor",
            "Infoactivo Fuerza",
            "Infoactivo Sensitivo",
            "Mechas Localizadas",
            "Color Caballero",
            "Moldeado",
            "Recogido",
            "Semirecogido",
            "Recogido Novia",
            "Corte Bebé",
            "Mechas",
            "Mechas Extras",
            "Barro Gold",
            "Mechas Localizadas Express",
            "Óleo Extra",
            "Barro Extra",
            "Barba",
            "Moldeado Extra",
            "Agua Lluvia",
            "Cultura de Color Extra",
            "Prepigmentar",
            "Cortar",
            "Peinado Largo",
            "Barro",
            "Peinado Extra",
            "Corte Niña",
            "Cultura de Color",
            "Peinado Niña Comunión",
            "Secado",
            "Peinado",
            "Corte Niño",
            "Corte Caballero",
            # Estética services (sample of key services)
            "Masaje Corporal (60 min)",
            "Maquillaje",
            "Tinte de Pestañas",
            "Peeling Corporal",
            "Tinte + Permanente de Pestañas",
            "Permanente de Pestañas",
            "Bioterapia Facial + Radiofrecuencia (30 min)",
            "Bioterapia Facial",
            "Maquillaje Express",
            "Cejas",
            "Manicura Permanente + Bio",
            "Bioterapia Sculptor + Radiofrecuencia 30 min",
            "Limar y Pintar Manos Permanente",
            "Bioterapia de Senos",
            "Piernas Perfectas + Presoterapia (30 min)",
            "Cera Enteras",
            "Pubis Completo",
            "Bioterapia Sculptor Completo",
            "Bioterapia Podal",
            "Pedicura Permanente con Bioterapia",
            "Manicura Caballero",
            "Labio",
        }

        # Act: Query all active services
        from database.connection import get_async_session

        async with get_async_session() as session:
            stmt = select(Service.name).where(Service.is_active == True)
            result = await session.execute(stmt)
            actual_services = set(result.scalars().all())

        # Assert: All expected services are present
        missing_services = expected_services - actual_services
        assert not missing_services, f"Missing services: {missing_services}"
        # Updated: 77 services in new catalog (was 69 in old catalog)
        assert len(actual_services) == 77, f"Expected 77 services, got {len(actual_services)}"

    async def test_inactive_service_not_returned(self):
        """Test inactive services are not returned."""
        from database.connection import get_async_session

        # Arrange: Create inactive service
        inactive_service_id = uuid4()
        async with get_async_session() as session:
            inactive_service = Service(
                id=inactive_service_id,
                name="INACTIVE_TEST_SERVICE",
                category=ServiceCategory.HAIRDRESSING,
                duration_minutes=30,
                description="Test inactive service",
                is_active=False,
            )
            session.add(inactive_service)
            await session.commit()

        # Act
        services = await get_service_by_name("INACTIVE_TEST_SERVICE", fuzzy=False)

        # Assert - function returns empty list for inactive services
        assert len(services) == 0, "Inactive service should not be returned"


# DISABLED PACK TESTS REMOVED: Packs functionality eliminated
# DISABLED CALCULATE_TOTAL TESTS REMOVED: Pricing functionality eliminated November 10, 2025
# DISABLED VALIDATE_SERVICE_COMBINATION TESTS REMOVED: Moved to transaction_validators.py


@pytest.mark.asyncio
class TestBookTool:
    """Test book() tool with emoji Calendar integration and PENDING status."""

    async def test_book_creates_appointment_with_pending_status(self):
        """
        AC1: Verify book() creates appointment with status=PENDING.

        Tests that when book() is called, it creates a database record with:
        - status=PENDING (not CONFIRMED)
        - All required fields populated
        """
        from agent.tools.booking_tools import book
        from agent.tools.calendar_tools import create_calendar_event
        from database.connection import get_async_session
        from database.models import Appointment, AppointmentStatus, Customer, Stylist
        from unittest.mock import patch
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        # Arrange: Create customer and stylist
        customer_id = uuid4()
        stylist_id = uuid4()
        MADRID_TZ = ZoneInfo("Europe/Madrid")
        start_time = datetime.now(MADRID_TZ) + timedelta(
            days=4
        )  # 4 days in future (passes 3-day rule)

        async with get_async_session() as session:
            customer = Customer(
                id=customer_id, phone="+34600000001", first_name="Test", last_name="Customer"
            )
            stylist = Stylist(
                id=stylist_id,
                name="Test Stylist",
                category=ServiceCategory.HAIRDRESSING,
                google_calendar_id="test@calendar.com",
            )
            session.add(customer)
            session.add(stylist)
            await session.commit()

        # Mock Calendar API to avoid actual API calls
        mock_calendar_response = {
            "success": True,
            "event_id": "mock_event_123",
            "calendar_id": "test@calendar.com",
            "start_time": start_time.isoformat(),
            "end_time": (start_time + timedelta(minutes=30)).isoformat(),
        }

        with patch(
            "agent.tools.calendar_tools.create_calendar_event", return_value=mock_calendar_response
        ):
            # Act: Call book() tool using ainvoke
            # Using "Cortar" from new PDF catalog (was "Cortar" in old catalog)
            result = await book.ainvoke(
                {
                    "customer_id": str(customer_id),
                    "first_name": "María",
                    "last_name": "López",
                    "notes": "Cliente prefiere estilista Ana",
                    "services": ["Cortar"],
                    "stylist_id": str(stylist_id),
                    "start_time": start_time.isoformat(),
                    "conversation_id": "test_conv_123",
                }
            )

        # Assert: Booking succeeded
        assert result["success"] is True, f"Booking failed: {result}"
        assert "appointment_id" in result
        assert result["status"] == "pending"

        # Assert: Appointment created in DB with PENDING status
        async with get_async_session() as session:
            stmt = select(Appointment).where(Appointment.id == result["appointment_id"])
            db_appointment = (await session.execute(stmt)).scalar_one_or_none()

            assert db_appointment is not None
            assert db_appointment.status == AppointmentStatus.PENDING  # NOT CONFIRMED
            assert db_appointment.first_name == "María"
            assert db_appointment.last_name == "López"
            assert db_appointment.notes == "Cliente prefiere estilista Ana"
            assert db_appointment.google_calendar_event_id == "mock_event_123"

    async def test_book_creates_calendar_event_with_yellow_emoji(self):
        """
        AC2: Verify Calendar event has emoji 🟡 in title.

        Tests that create_calendar_event is called with status="pending"
        which should result in emoji 🟡 format: "🟡 {first_name} - {service_names}"
        """
        from agent.tools.calendar_tools import create_calendar_event
        from database.connection import get_async_session
        from database.models import Stylist, ServiceCategory
        from unittest.mock import AsyncMock, patch
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        # Arrange: Create stylist
        stylist_id = uuid4()
        MADRID_TZ = ZoneInfo("Europe/Madrid")
        start_time = datetime.now(MADRID_TZ) + timedelta(days=4)

        async with get_async_session() as session:
            stylist = Stylist(
                id=stylist_id,
                name="Test Stylist",
                category=ServiceCategory.HAIRDRESSING,
                google_calendar_id="test@calendar.com",
            )
            session.add(stylist)
            await session.commit()

        # Mock Google Calendar API service
        mock_service = AsyncMock()
        mock_service.events().insert().execute.return_value = {
            "id": "calendar_event_456",
            "summary": "🟡 María - Cortar",
        }

        with patch("agent.tools.calendar_tools.get_calendar_client") as mock_get_client:
            mock_client = AsyncMock()
            mock_client.get_service.return_value = mock_service
            mock_get_client.return_value = mock_client

            # Act: Call create_calendar_event with status="pending"
            result = await create_calendar_event(
                stylist_id=str(stylist_id),
                start_time=start_time.isoformat(),
                duration_minutes=30,
                customer_name="María",
                service_names="Cortar",
                status="pending",
                conversation_id="test_conv",
            )

        # Assert: Event created successfully
        assert result["success"] is True
        assert result["event_id"] == "calendar_event_456"

        # Assert: Event summary has emoji 🟡 format
        call_args = mock_service.events().insert.call_args
        event_body = call_args.kwargs["body"]
        assert "🟡" in event_body["summary"], (
            f"Expected emoji 🟡 in summary: {event_body['summary']}"
        )
        assert event_body["summary"] == "🟡 María - Cortar"

    async def test_book_saves_chatwoot_conversation_id(self):
        """
        AC4: Verify book() saves chatwoot_conversation_id in customer table.

        Tests that when conversation_id is provided, it gets saved to customer.chatwoot_conversation_id.
        """
        from agent.tools.booking_tools import book
        from database.connection import get_async_session
        from database.models import Customer, Stylist, ServiceCategory
        from unittest.mock import patch
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        # Arrange: Create customer and stylist
        customer_id = uuid4()
        stylist_id = uuid4()
        MADRID_TZ = ZoneInfo("Europe/Madrid")
        start_time = datetime.now(MADRID_TZ) + timedelta(days=4)

        async with get_async_session() as session:
            customer = Customer(
                id=customer_id,
                phone="+34600000002",
                first_name="Test",
                chatwoot_conversation_id=None,  # Initially NULL
            )
            stylist = Stylist(
                id=stylist_id,
                name="Test Stylist",
                category=ServiceCategory.HAIRDRESSING,
                google_calendar_id="test@calendar.com",
            )
            session.add(customer)
            session.add(stylist)
            await session.commit()

        # Mock Calendar API
        mock_calendar_response = {
            "success": True,
            "event_id": "mock_event_789",
            "calendar_id": "test@calendar.com",
            "start_time": start_time.isoformat(),
            "end_time": (start_time + timedelta(minutes=30)).isoformat(),
        }

        with patch(
            "agent.tools.calendar_tools.create_calendar_event", return_value=mock_calendar_response
        ):
            # Act: Call book() with conversation_id using ainvoke
            result = await book.ainvoke(
                {
                    "customer_id": str(customer_id),
                    "first_name": "Pedro",
                    "last_name": None,
                    "notes": None,
                    "services": ["Cortar"],
                    "stylist_id": str(stylist_id),
                    "start_time": start_time.isoformat(),
                    "conversation_id": "chatwoot_conv_456",  # Provide conversation_id
                }
            )

        # Assert: Booking succeeded
        assert result["success"] is True

        # Assert: Customer's chatwoot_conversation_id was updated
        async with get_async_session() as session:
            stmt = select(Customer).where(Customer.id == customer_id)
            updated_customer = (await session.execute(stmt)).scalar_one()

            assert updated_customer.chatwoot_conversation_id == "chatwoot_conv_456"

    async def test_book_rollback_on_calendar_error(self):
        """
        AC6: Verify transaction rollback if Calendar API fails.

        Tests that if create_calendar_event fails, the DB transaction is rolled back
        and NO appointment record remains in the database.
        """
        from agent.tools.booking_tools import book
        from database.connection import get_async_session
        from database.models import Appointment, Customer, Stylist, ServiceCategory
        from unittest.mock import patch
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo

        # Arrange: Create customer and stylist
        customer_id = uuid4()
        stylist_id = uuid4()
        MADRID_TZ = ZoneInfo("Europe/Madrid")
        start_time = datetime.now(MADRID_TZ) + timedelta(days=4)

        async with get_async_session() as session:
            customer = Customer(id=customer_id, phone="+34600000003", first_name="Test")
            stylist = Stylist(
                id=stylist_id,
                name="Test Stylist",
                category=ServiceCategory.HAIRDRESSING,
                google_calendar_id="test@calendar.com",
            )
            session.add(customer)
            session.add(stylist)
            await session.commit()

        # Mock Calendar API to simulate failure
        mock_calendar_failure = {"success": False, "error": "Google Calendar API unavailable"}

        with patch(
            "agent.tools.calendar_tools.create_calendar_event", return_value=mock_calendar_failure
        ):
            # Act: Call book() - should fail using ainvoke
            result = await book.ainvoke(
                {
                    "customer_id": str(customer_id),
                    "first_name": "Ana",
                    "last_name": None,
                    "notes": None,
                    "services": ["Cortar"],
                    "stylist_id": str(stylist_id),
                    "start_time": start_time.isoformat(),
                }
            )

        # Assert: Booking failed
        assert result["success"] is False
        assert result["error_code"] == "CALENDAR_EVENT_FAILED"
        assert "No pudimos completar tu reserva" in result["error_message"]

        # Assert: NO appointment created in DB (rollback succeeded)
        async with get_async_session() as session:
            stmt = select(Appointment).where(Appointment.customer_id == customer_id)
            appointments = (await session.execute(stmt)).scalars().all()

            assert len(appointments) == 0, "Appointment should NOT exist after rollback"


# ===========================================================================
# REQ-3: book() audience passthrough to resolve_service_names
# ===========================================================================


@pytest.mark.asyncio
class TestBookAudiencePassthrough:
    """Verify that book() accepts and forwards the audience kwarg to resolve_service_names."""

    async def test_book_passes_audience_to_resolve_service_names(self):
        """book() must pass audience kwarg to resolve_service_names()."""
        from unittest.mock import AsyncMock, patch
        from uuid import uuid4

        from agent.tools.booking_tools import book

        service_uuid = uuid4()
        customer_uuid = uuid4()
        stylist_uuid = uuid4()

        mock_resolve = AsyncMock(return_value=([service_uuid], None))

        with patch("agent.tools.booking_tools.resolve_service_names", mock_resolve):
            # Call via ainvoke — audience injected
            from agent.transactions.booking_transaction import BookingTransaction

            with patch.object(
                BookingTransaction,
                "execute",
                AsyncMock(
                    return_value={
                        "success": True,
                        "appointment_id": str(uuid4()),
                        "google_calendar_event_id": "cal123",
                        "start_time": "2026-04-10T10:00:00+02:00",
                        "end_time": "2026-04-10T11:00:00+02:00",
                        "duration_minutes": 60,
                        "customer_id": str(customer_uuid),
                        "stylist_id": str(stylist_uuid),
                        "service_ids": [str(service_uuid)],
                    }
                ),
            ):
                result = await book.ainvoke(
                    {
                        "customer_id": str(customer_uuid),
                        "first_name": "Ana",
                        "last_name": None,
                        "notes": None,
                        "services": ["Cortar"],
                        "stylist_id": str(stylist_uuid),
                        "start_time": "2026-04-10T10:00:00+02:00",
                        "audience": "adult_female",
                    }
                )

        # Verify resolve_service_names was called with audience kwarg
        mock_resolve.assert_called_once()
        call_kwargs = mock_resolve.call_args
        # Either positional or keyword — the audience must be present
        assert call_kwargs.kwargs.get("audience") == "adult_female" or (
            len(call_kwargs.args) > 1 and call_kwargs.args[1] == "adult_female"
        ), f"Expected audience='adult_female' in call to resolve_service_names. Got: {call_kwargs}"

    async def test_book_passes_none_audience_when_absent(self):
        """book() passes audience=None to resolve_service_names when not provided."""
        from unittest.mock import AsyncMock, patch
        from uuid import uuid4

        from agent.tools.booking_tools import book

        service_uuid = uuid4()
        customer_uuid = uuid4()
        stylist_uuid = uuid4()

        mock_resolve = AsyncMock(return_value=([service_uuid], None))

        with patch("agent.tools.booking_tools.resolve_service_names", mock_resolve):
            from agent.transactions.booking_transaction import BookingTransaction

            with patch.object(
                BookingTransaction,
                "execute",
                AsyncMock(
                    return_value={
                        "success": True,
                        "appointment_id": str(uuid4()),
                        "google_calendar_event_id": "cal456",
                        "start_time": "2026-04-10T10:00:00+02:00",
                        "end_time": "2026-04-10T11:00:00+02:00",
                        "duration_minutes": 60,
                        "customer_id": str(customer_uuid),
                        "stylist_id": str(stylist_uuid),
                        "service_ids": [str(service_uuid)],
                    }
                ),
            ):
                await book.ainvoke(
                    {
                        "customer_id": str(customer_uuid),
                        "first_name": "Juan",
                        "last_name": None,
                        "notes": None,
                        "services": ["Barba"],
                        "stylist_id": str(stylist_uuid),
                        "start_time": "2026-04-10T10:00:00+02:00",
                        # No audience provided
                    }
                )

        mock_resolve.assert_called_once()
        call_kwargs = mock_resolve.call_args
        # audience should be None (default)
        assert call_kwargs.kwargs.get("audience") is None, (
            f"Expected audience=None. Got: {call_kwargs}"
        )
