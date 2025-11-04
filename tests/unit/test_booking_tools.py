"""
Unit tests for booking_tools module.

Tests service query functions and pricing calculations.
Note: Pack-related tests disabled - packs functionality eliminated.
"""

from decimal import Decimal
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text

from agent.tools.booking_tools import (
    calculate_total,
    # get_packs_containing_service,  # Removed - packs functionality eliminated
    # get_packs_for_multiple_services,  # Removed - packs functionality eliminated
    get_service_by_name,
    validate_service_combination,
)
from database.connection import AsyncSessionLocal, engine
from database.models import Base, Service, ServiceCategory  # Pack removed - packs functionality eliminated
from database.seeds.services import seed_services
# from database.seeds.packs import seed_packs  # Removed - packs functionality eliminated


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
        assert service.price_euros == Decimal("60.00")
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
                price_euros=Decimal("10.00"),
                requires_advance_payment=False,
                description="Test inactive service",
                is_active=False,
            )
            session.add(inactive_service)
            await session.commit()

        # Act
        service = await get_service_by_name("INACTIVE_TEST_SERVICE", fuzzy=False)

        # Assert
        assert service is None, "Inactive service should not be returned"


# DISABLED PACK TESTS REMOVED: Packs functionality eliminated (lines 169-297 removed)

@pytest.mark.asyncio
class TestCalculateTotal:
    """Test calculate_total function."""

    async def test_single_service_total(self):
        """Test calculate total for single service (MECHAS)."""
        from database.connection import get_async_session

        # Arrange
        async for session in get_async_session():
            stmt = select(Service.id).where(Service.name == "MECHAS")
            result = await session.execute(stmt)
            mechas_id = result.scalar_one()

        # Act
        total = await calculate_total([mechas_id])

        # Assert
        assert total["total_price"] == Decimal("60.00")
        assert total["total_duration"] == 120
        assert total["service_count"] == 1
        assert len(total["services"]) == 1

    async def test_multiple_services_total(self):
        """Test calculate total for 3 services (BARRO GOLD + AGUA LLUVIA + PEINADO LARGO)."""
        from database.connection import get_async_session

        # Arrange
        async for session in get_async_session():
            stmt_barro = select(Service.id).where(Service.name == "BARRO GOLD")
            result_barro = await session.execute(stmt_barro)
            barro_id = result_barro.scalar_one()

            stmt_agua = select(Service.id).where(Service.name == "AGUA LLUVIA")
            result_agua = await session.execute(stmt_agua)
            agua_id = result_agua.scalar_one()

            stmt_peinado = select(Service.id).where(Service.name == "PEINADO LARGO")
            result_peinado = await session.execute(stmt_peinado)
            peinado_id = result_peinado.scalar_one()

        # Act
        total = await calculate_total([barro_id, agua_id, peinado_id])

        # Assert
        # BARRO GOLD (48€, 40min) + AGUA LLUVIA (20€, 25min) + PEINADO LARGO (22.5€, 45min)
        assert total["total_price"] == Decimal("90.50")
        assert total["total_duration"] == 110
        assert total["service_count"] == 3

    async def test_empty_list_returns_zero(self):
        """Test calculate total for empty list returns zero."""
        # Act
        total = await calculate_total([])

        # Assert
        assert total["total_price"] == Decimal("0.00")
        assert total["total_duration"] == 0
        assert total["service_count"] == 0
        assert total["services"] == []

    async def test_free_consultation_total(self):
        """Test calculate total for free consultation (0€)."""
        from database.connection import get_async_session

        # Arrange
        async for session in get_async_session():
            stmt = select(Service.id).where(Service.name == "CONSULTA GRATUITA")
            result = await session.execute(stmt)
            consulta_id = result.scalar_one()

        # Act
        total = await calculate_total([consulta_id])

        # Assert
        assert total["total_price"] == Decimal("0.00")
        assert total["total_duration"] == 15
        assert total["service_count"] == 1


@pytest.mark.asyncio
class TestExceptionHandling:
    """Test exception handling paths in booking_tools functions."""

    async def test_get_service_by_name_database_error(self, monkeypatch):
        """Test get_service_by_name handles database exceptions gracefully."""
        from unittest.mock import AsyncMock
        from database.connection import get_async_session

        # Arrange: Mock get_async_session to raise database exception
        async def mock_session_error():
            raise Exception("Simulated database connection error")
            yield  # Make it a generator

        monkeypatch.setattr("agent.tools.booking_tools.get_async_session", mock_session_error)

        # Act
        service = await get_service_by_name("MECHAS")

        # Assert: Should return None on error
        assert service is None

    async def test_get_packs_containing_service_database_error(self, monkeypatch):
        """Test get_packs_containing_service handles database exceptions gracefully."""
        from unittest.mock import AsyncMock

        # Arrange: Mock get_async_session to raise database exception
        async def mock_session_error():
            raise Exception("Simulated database connection error")
            yield  # Make it a generator

        monkeypatch.setattr("agent.tools.booking_tools.get_async_session", mock_session_error)

        # Act
        packs = await get_packs_containing_service(uuid4())

        # Assert: Should return empty list on error
        assert packs == []

    async def test_get_packs_for_multiple_services_database_error(self, monkeypatch):
        """Test get_packs_for_multiple_services handles database exceptions gracefully."""
        # Arrange: Mock get_async_session to raise database exception
        async def mock_session_error():
            raise Exception("Simulated database connection error")
            yield  # Make it a generator

        monkeypatch.setattr("agent.tools.booking_tools.get_async_session", mock_session_error)

        # Act
        packs = await get_packs_for_multiple_services([uuid4(), uuid4()])

        # Assert: Should return empty list on error
        assert packs == []

    async def test_calculate_total_database_error(self, monkeypatch):
        """Test calculate_total handles database exceptions gracefully."""
        # Arrange: Mock get_async_session to raise database exception
        async def mock_session_error():
            raise Exception("Simulated database connection error")
            yield  # Make it a generator

        monkeypatch.setattr("agent.tools.booking_tools.get_async_session", mock_session_error)

        # Act
        total = await calculate_total([uuid4()])

        # Assert: Should return zero totals on error
        assert total["total_price"] == Decimal("0.00")
        assert total["total_duration"] == 0
        assert total["service_count"] == 0
        assert total["services"] == []


@pytest.mark.asyncio
class TestValidateServiceCombination:
    """Test validate_service_combination function for service category mixing (Story 3.6)."""

    async def test_single_hairdressing_service_valid(self):
        """Test single Hairdressing service is valid."""
        # Arrange: Get a Hairdressing service
        async with AsyncSessionLocal() as session:
            stmt = select(Service).where(
                Service.name == "Corte de pelo",
                Service.category == ServiceCategory.HAIRDRESSING,
            )
            result = await session.execute(stmt)
            corte_service = result.scalar_one()

            # Act
            validation = await validate_service_combination([corte_service.id], session)

            # Assert
            assert validation["valid"] is True
            assert validation["reason"] is None
            assert len(validation["services_by_category"]) == 1
            assert ServiceCategory.HAIRDRESSING in validation["services_by_category"]

    async def test_single_aesthetics_service_valid(self):
        """Test single Aesthetics service is valid."""
        # Arrange: Get an Aesthetics service
        async with AsyncSessionLocal() as session:
            stmt = select(Service).where(
                Service.name == "BIOTERAPIA FACIAL",
                Service.category == ServiceCategory.AESTHETICS,
            )
            result = await session.execute(stmt)
            bioterapia_service = result.scalar_one()

            # Act
            validation = await validate_service_combination([bioterapia_service.id], session)

            # Assert
            assert validation["valid"] is True
            assert validation["reason"] is None
            assert len(validation["services_by_category"]) == 1
            assert ServiceCategory.AESTHETICS in validation["services_by_category"]

    async def test_two_hairdressing_services_valid(self):
        """Test two Hairdressing services (AC 10: 'corte + color') is valid."""
        # Arrange: Get two Hairdressing services
        async with AsyncSessionLocal() as session:
            stmt = select(Service).where(
                Service.name.in_(["Corte de pelo", "Corte + Color"]),
                Service.category == ServiceCategory.HAIRDRESSING,
            )
            result = await session.execute(stmt)
            services = list(result.scalars().all())
            service_ids = [s.id for s in services]

            # Act
            validation = await validate_service_combination(service_ids, session)

            # Assert
            assert validation["valid"] is True, "Two Hairdressing services should be valid (AC 10)"
            assert validation["reason"] is None
            assert len(validation["services_by_category"]) == 1
            assert ServiceCategory.HAIRDRESSING in validation["services_by_category"]

    async def test_two_aesthetics_services_valid(self):
        """Test two Aesthetics services is valid."""
        # Arrange: Get two Aesthetics services
        async with AsyncSessionLocal() as session:
            stmt = select(Service).where(
                Service.name.in_(["MANICURA PERMANENTE", "BIOTERAPIA FACIAL"]),
                Service.category == ServiceCategory.AESTHETICS,
            )
            result = await session.execute(stmt)
            services = list(result.scalars().all())
            service_ids = [s.id for s in services]

            # Act
            validation = await validate_service_combination(service_ids, session)

            # Assert
            assert validation["valid"] is True
            assert validation["reason"] is None
            assert len(validation["services_by_category"]) == 1
            assert ServiceCategory.AESTHETICS in validation["services_by_category"]

    async def test_mixed_categories_invalid(self):
        """Test mixed Hairdressing + Aesthetics (AC 8: 'corte + bioterapia facial') is invalid."""
        # Arrange: Get one Hairdressing and one Aesthetics service
        async with AsyncSessionLocal() as session:
            # Get Hairdressing service
            stmt_hair = select(Service).where(
                Service.name == "Corte de pelo",
                Service.category == ServiceCategory.HAIRDRESSING,
            )
            result_hair = await session.execute(stmt_hair)
            corte_service = result_hair.scalar_one()

            # Get Aesthetics service
            stmt_aes = select(Service).where(
                Service.name == "BIOTERAPIA FACIAL",
                Service.category == ServiceCategory.AESTHETICS,
            )
            result_aes = await session.execute(stmt_aes)
            bioterapia_service = result_aes.scalar_one()

            service_ids = [corte_service.id, bioterapia_service.id]

            # Act
            validation = await validate_service_combination(service_ids, session)

            # Assert
            assert validation["valid"] is False, "Mixed categories should be invalid (AC 8)"
            assert validation["reason"] == "mixed_categories"
            assert len(validation["services_by_category"]) == 2
            assert ServiceCategory.HAIRDRESSING in validation["services_by_category"]
            assert ServiceCategory.AESTHETICS in validation["services_by_category"]

    async def test_three_hairdressing_services_valid(self):
        """Test three Hairdressing services is valid."""
        # Arrange: Get three Hairdressing services
        async with AsyncSessionLocal() as session:
            stmt = select(Service).where(
                Service.name.in_(["MECHAS", "Corte de pelo", "OLEO PIGMENTO"]),
                Service.category == ServiceCategory.HAIRDRESSING,
            )
            result = await session.execute(stmt)
            services = list(result.scalars().all())
            service_ids = [s.id for s in services]

            # Act
            validation = await validate_service_combination(service_ids, session)

            # Assert
            assert validation["valid"] is True
            assert validation["reason"] is None
            assert len(validation["services_by_category"]) == 1

    async def test_empty_service_list_valid(self):
        """Test empty service list is valid (edge case)."""
        # Arrange: Empty list
        async with AsyncSessionLocal() as session:
            # Act
            validation = await validate_service_combination([], session)

            # Assert
            assert validation["valid"] is True, "Empty list should be valid (edge case)"
            assert validation["reason"] is None
            assert validation["services_by_category"] == {}

    async def test_non_existent_service_id_invalid(self):
        """Test non-existent service_id returns invalid with error logged."""
        # Arrange: Random UUID that doesn't exist
        fake_id = uuid4()

        async with AsyncSessionLocal() as session:
            # Act
            validation = await validate_service_combination([fake_id], session)

            # Assert
            assert validation["valid"] is False, "Non-existent service_id should be invalid"
            assert validation["reason"] == "invalid_service_ids"
            assert validation["services_by_category"] == {}

    async def test_corte_plus_color_valid(self):
        """Test specific AC 10 example: 'corte + color' (both Hairdressing) is valid."""
        # Arrange: Get "Corte de pelo" and a color-related service
        async with AsyncSessionLocal() as session:
            # Using "Corte + Color" which is a hairdressing service
            # and "Corte de pelo" which is also hairdressing
            stmt = select(Service).where(
                Service.name.in_(["Corte de pelo", "Corte + Color"]),
                Service.category == ServiceCategory.HAIRDRESSING,
            )
            result = await session.execute(stmt)
            services = list(result.scalars().all())
            service_ids = [s.id for s in services]

            # Act
            validation = await validate_service_combination(service_ids, session)

            # Assert
            assert validation["valid"] is True, "AC 10: 'corte + color' should be valid"
            assert validation["reason"] is None
            assert len(validation["services_by_category"]) == 1
            assert ServiceCategory.HAIRDRESSING in validation["services_by_category"]

    async def test_corte_plus_bioterapia_invalid(self):
        """Test specific AC 8 example: 'corte + bioterapia facial' is invalid."""
        # Arrange: Get "Corte de pelo" (Hairdressing) and "BIOTERAPIA FACIAL" (Aesthetics)
        async with AsyncSessionLocal() as session:
            stmt_corte = select(Service).where(
                Service.name == "Corte de pelo",
                Service.category == ServiceCategory.HAIRDRESSING,
            )
            result_corte = await session.execute(stmt_corte)
            corte_service = result_corte.scalar_one()

            stmt_bio = select(Service).where(
                Service.name == "BIOTERAPIA FACIAL",
                Service.category == ServiceCategory.AESTHETICS,
            )
            result_bio = await session.execute(stmt_bio)
            bioterapia_service = result_bio.scalar_one()

            service_ids = [corte_service.id, bioterapia_service.id]

            # Act
            validation = await validate_service_combination(service_ids, session)

            # Assert
            assert validation["valid"] is False, "AC 8: 'corte + bioterapia facial' should be invalid"
            assert validation["reason"] == "mixed_categories"
            assert len(validation["services_by_category"]) == 2
            # Verify both categories are present
            hairdressing_services = validation["services_by_category"].get(ServiceCategory.HAIRDRESSING, [])
            aesthetics_services = validation["services_by_category"].get(ServiceCategory.AESTHETICS, [])
            assert len(hairdressing_services) == 1
            assert len(aesthetics_services) == 1
