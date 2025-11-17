"""
Unit tests for category validation in booking system.

Tests that the system correctly rejects attempts to book services from
different categories (Peluquería + Estética) in the same appointment.
"""

from uuid import uuid4

import pytest
from sqlalchemy import text

from agent.validators.transaction_validators import validate_category_consistency
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

    # Seed services for tests
    await seed_services()

    yield

    # Cleanup after test
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
class TestCategoryValidation:
    """Test category consistency validation for booking transactions."""

    async def test_single_service_always_valid(self):
        """Test single service booking is always valid (no category mixing)."""
        # Arrange: Create a single service
        from database.connection import get_async_session
        from sqlalchemy import select

        async for session in get_async_session():
            stmt = select(Service).where(Service.category == ServiceCategory.HAIRDRESSING).limit(1)
            result = await session.execute(stmt)
            service = result.scalar_one()
            break

        # Act
        validation = await validate_category_consistency([service.id])

        # Assert
        assert validation["valid"] is True
        assert validation["error_code"] is None
        assert validation["error_message"] is None
        assert validation["categories_found"] == ["Peluquería"]

    async def test_multiple_hairdressing_services_valid(self):
        """Test multiple Peluquería services can be booked together."""
        # Arrange: Get multiple hairdressing services
        from database.connection import get_async_session
        from sqlalchemy import select

        async for session in get_async_session():
            stmt = select(Service).where(Service.category == ServiceCategory.HAIRDRESSING).limit(3)
            result = await session.execute(stmt)
            services = list(result.scalars().all())
            break

        assert len(services) >= 2, "Need at least 2 hairdressing services for test"
        service_ids = [s.id for s in services[:2]]

        # Act
        validation = await validate_category_consistency(service_ids)

        # Assert
        assert validation["valid"] is True
        assert validation["error_code"] is None
        assert validation["categories_found"] == ["Peluquería"]

    async def test_multiple_aesthetics_services_valid(self):
        """Test multiple Estética services can be booked together."""
        # Arrange: Get multiple aesthetics services
        from database.connection import get_async_session
        from sqlalchemy import select

        async for session in get_async_session():
            stmt = select(Service).where(Service.category == ServiceCategory.AESTHETICS).limit(3)
            result = await session.execute(stmt)
            services = list(result.scalars().all())
            break

        assert len(services) >= 2, "Need at least 2 aesthetics services for test"
        service_ids = [s.id for s in services[:2]]

        # Act
        validation = await validate_category_consistency(service_ids)

        # Assert
        assert validation["valid"] is True
        assert validation["error_code"] is None
        assert validation["categories_found"] == ["Estética"]

    async def test_mixed_categories_rejected(self):
        """Test mixing Peluquería + Estética services is rejected."""
        # Arrange: Get one service from each category
        from database.connection import get_async_session
        from sqlalchemy import select

        async for session in get_async_session():
            # Get one hairdressing service
            stmt_hair = select(Service).where(Service.category == ServiceCategory.HAIRDRESSING).limit(1)
            result_hair = await session.execute(stmt_hair)
            hair_service = result_hair.scalar_one()

            # Get one aesthetics service
            stmt_aes = select(Service).where(Service.category == ServiceCategory.AESTHETICS).limit(1)
            result_aes = await session.execute(stmt_aes)
            aesthetics_service = result_aes.scalar_one()
            break

        service_ids = [hair_service.id, aesthetics_service.id]

        # Act
        validation = await validate_category_consistency(service_ids)

        # Assert
        assert validation["valid"] is False
        assert validation["error_code"] == "CATEGORY_MISMATCH"
        assert "Lo siento, no puedo agendar servicios de diferentes categorías" in validation["error_message"]
        assert "Por favor, elige servicios de una sola categoría" in validation["error_message"]
        assert set(validation["categories_found"]) == {"Peluquería", "Estética"}

    async def test_mixed_categories_error_message_contains_both_categories(self):
        """Test error message lists both categories when mix is detected."""
        # Arrange: Get one service from each category
        from database.connection import get_async_session
        from sqlalchemy import select

        async for session in get_async_session():
            stmt_hair = select(Service).where(Service.category == ServiceCategory.HAIRDRESSING).limit(1)
            result_hair = await session.execute(stmt_hair)
            hair_service = result_hair.scalar_one()

            stmt_aes = select(Service).where(Service.category == ServiceCategory.AESTHETICS).limit(1)
            result_aes = await session.execute(stmt_aes)
            aesthetics_service = result_aes.scalar_one()
            break

        service_ids = [hair_service.id, aesthetics_service.id]

        # Act
        validation = await validate_category_consistency(service_ids)

        # Assert
        error_msg = validation["error_message"]
        assert "Peluquería" in error_msg or "Estética" in error_msg
        assert validation["categories_found"] == ["Peluquería", "Estética"] or \
               validation["categories_found"] == ["Estética", "Peluquería"]

    async def test_empty_service_list_valid(self):
        """Test empty service list returns valid (edge case)."""
        # Act
        validation = await validate_category_consistency([])

        # Assert
        assert validation["valid"] is True
        assert validation["error_code"] is None
        assert validation["categories_found"] == []

    async def test_three_services_same_category_valid(self):
        """Test three services from same category can be booked together."""
        # Arrange: Get three hairdressing services
        from database.connection import get_async_session
        from sqlalchemy import select

        async for session in get_async_session():
            stmt = select(Service).where(Service.category == ServiceCategory.HAIRDRESSING).limit(3)
            result = await session.execute(stmt)
            services = list(result.scalars().all())
            break

        assert len(services) == 3, "Need exactly 3 hairdressing services for test"
        service_ids = [s.id for s in services]

        # Act
        validation = await validate_category_consistency(service_ids)

        # Assert
        assert validation["valid"] is True
        assert validation["categories_found"] == ["Peluquería"]

    async def test_nonexistent_service_ids(self):
        """Test validation with non-existent service IDs."""
        # Arrange: Use random UUIDs that don't exist
        fake_service_ids = [uuid4(), uuid4()]

        # Act
        validation = await validate_category_consistency(fake_service_ids)

        # Assert: Should return valid=True with empty categories (no services found)
        assert validation["valid"] is True
        assert validation["categories_found"] == []
