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
        """Test exact search for 'mechas' matches 'MECHAS'."""
        # Arrange: Query should find MECHAS service
        # (Service already exists from seed data)

        # Act
        service = await get_service_by_name("mechas", fuzzy=False)

        # Assert
        assert service is not None, "Service 'MECHAS' should be found"
        assert service.name == "MECHAS"
        assert service.duration_minutes == 120

    async def test_fuzzy_search_with_typo(self):
        """Test fuzzy search with typo 'mecha' matches 'MECHAS'."""
        # Act
        service = await get_service_by_name("mecha", fuzzy=True)

        # Assert
        assert service is not None, "Fuzzy search should find 'MECHAS'"
        assert service.name == "MECHAS"

    async def test_case_insensitive_search(self):
        """Test case-insensitive search with different casing."""
        # Act
        service = await get_service_by_name("CORTE DE PELO", fuzzy=False)

        # Assert
        assert service is not None
        assert service.name == "Corte de pelo"

    async def test_service_not_found(self):
        """Test search returns None for non-existent service."""
        # Act
        service = await get_service_by_name("nonexistent_service_xyz", fuzzy=False)

        # Assert
        assert service is None, "Non-existent service should return None"

    async def test_fuzzy_search_no_match_below_threshold(self):
        """Test fuzzy search returns None when similarity is below 0.6 threshold."""
        # Act: Search with very different string
        service = await get_service_by_name("xyz123", fuzzy=True)

        # Assert
        assert service is None, "Very different string should not match"

    async def test_verify_all_scenario_services_present(self):
        """Test all expected services from scenarios.md are seeded."""
        # Arrange: Expected service names from Story 3.1
        expected_services = {
            "MECHAS",
            "Corte de pelo",
            "Corte + Color",
            "OLEO PIGMENTO",
            "BARRO",
            "BARRO GOLD",
            "AGUA LLUVIA",
            "PEINADO LARGO",
            "CORTE CABALLERO",
            "Peinado",
            "MANICURA PERMANENTE",
            "BIOTERAPIA FACIAL",
            "Micropigmentación",
            "CONSULTA GRATUITA",
            "Consulta estética",
        }

        # Act: Query all active services
        from database.connection import get_async_session

        async for session in get_async_session():
            stmt = select(Service.name).where(Service.is_active == True)
            result = await session.execute(stmt)
            actual_services = set(result.scalars().all())

        # Assert: All expected services are present
        missing_services = expected_services - actual_services
        assert not missing_services, f"Missing services: {missing_services}"
        assert len(actual_services) >= 15, f"Expected at least 15 services, got {len(actual_services)}"

    async def test_inactive_service_not_returned(self):
        """Test inactive services are not returned."""
        from database.connection import get_async_session

        # Arrange: Create inactive service
        inactive_service_id = uuid4()
        async for session in get_async_session():
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
        service = await get_service_by_name("INACTIVE_TEST_SERVICE", fuzzy=False)

        # Assert
        assert service is None, "Inactive service should not be returned"


# DISABLED PACK TESTS REMOVED: Packs functionality eliminated
# DISABLED CALCULATE_TOTAL TESTS REMOVED: Pricing functionality eliminated November 10, 2025
# DISABLED VALIDATE_SERVICE_COMBINATION TESTS REMOVED: Moved to transaction_validators.py

