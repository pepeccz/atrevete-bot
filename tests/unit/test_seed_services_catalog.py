"""
Unit tests for service catalog seed data.

Tests that all 77 services from the PDF catalog are correctly seeded
with deterministic UUIDs and proper field validation.
"""

import pytest
from sqlalchemy import select, text
from uuid import UUID

from database.connection import engine
from database.models import Base, Service, ServiceCategory
from database.seeds.services import (
    seed_services,
    generate_service_uuid,
    HAIRDRESSING_SERVICES,
    AESTHETICS_SERVICES,
    ALL_SERVICES,
    SERVICE_UUID_NAMESPACE,
)


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
class TestServiceCatalogSeed:
    """Test the complete service catalog seeding from PDF."""

    async def test_all_77_services_seeded(self):
        """Test that all 77 services from PDF are present in database."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            stmt = select(Service).where(Service.is_active == True)
            result = await session.execute(stmt)
            services = list(result.scalars().all())

        # Assert: Exactly 77 services
        assert len(services) == 77, f"Expected 77 services, got {len(services)}"

    async def test_hairdressing_service_count(self):
        """Test that 36 hairdressing services are seeded."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            stmt = select(Service).where(
                Service.category == ServiceCategory.HAIRDRESSING,
                Service.is_active == True
            )
            result = await session.execute(stmt)
            services = list(result.scalars().all())

        assert len(services) == 36, f"Expected 36 hairdressing services, got {len(services)}"

    async def test_aesthetics_service_count(self):
        """Test that 41 aesthetics services are seeded."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            stmt = select(Service).where(
                Service.category == ServiceCategory.AESTHETICS,
                Service.is_active == True
            )
            result = await session.execute(stmt)
            services = list(result.scalars().all())

        assert len(services) == 41, f"Expected 41 aesthetics services, got {len(services)}"

    async def test_service_uuid_determinism(self):
        """Test that UUIDs are deterministic based on service name."""
        # Generate UUID for same service name twice
        uuid1 = generate_service_uuid("Cortar")
        uuid2 = generate_service_uuid("Cortar")

        # Should be identical
        assert uuid1 == uuid2, "UUIDs should be deterministic for same name"
        assert isinstance(uuid1, UUID), "Should return UUID object"

    async def test_different_services_have_different_uuids(self):
        """Test that different service names produce different UUIDs."""
        uuid_cortar = generate_service_uuid("Cortar")
        uuid_peinado = generate_service_uuid("Peinado")

        assert uuid_cortar != uuid_peinado, "Different services should have different UUIDs"

    async def test_mechas_localizadas_vs_express_different_uuids(self):
        """Test that 'Mechas Localizadas' and 'Mechas Localizadas Express' have different UUIDs."""
        uuid_localizadas = generate_service_uuid("Mechas Localizadas")
        uuid_express = generate_service_uuid("Mechas Localizadas Express")

        assert uuid_localizadas != uuid_express, (
            "Mechas Localizadas and Mechas Localizadas Express should have different UUIDs"
        )

    async def test_all_services_have_required_fields(self):
        """Test that every service has name, category, and duration."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            stmt = select(Service).where(Service.is_active == True)
            result = await session.execute(stmt)
            services = list(result.scalars().all())

        for service in services:
            assert service.name, f"Service {service.id} missing name"
            assert service.category in [ServiceCategory.HAIRDRESSING, ServiceCategory.AESTHETICS], (
                f"Service {service.name} has invalid category"
            )
            assert service.duration_minutes > 0, (
                f"Service {service.name} has invalid duration"
            )
            assert service.id is not None, f"Service {service.name} missing UUID"

    async def test_seed_data_matches_database(self):
        """Test that seed data constants match what's in the database."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            for service_data in ALL_SERVICES:
                expected_uuid = generate_service_uuid(service_data["name"])

                # Query database for this service
                stmt = select(Service).where(Service.id == expected_uuid)
                result = await session.execute(stmt)
                db_service = result.scalar_one_or_none()

                assert db_service is not None, (
                    f"Service '{service_data['name']}' not found in database"
                )
                assert db_service.name == service_data["name"], (
                    f"Name mismatch for {service_data['name']}"
                )
                assert db_service.category == service_data["category"], (
                    f"Category mismatch for {service_data['name']}"
                )
                assert db_service.duration_minutes == service_data["duration_minutes"], (
                    f"Duration mismatch for {service_data['name']}"
                )

    async def test_service_names_are_unique(self):
        """Test that all service names are unique."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            stmt = select(Service.name).where(Service.is_active == True)
            result = await session.execute(stmt)
            names = [row[0] for row in result.all()]

        # Check no duplicates
        unique_names = set(names)
        assert len(names) == len(unique_names), (
            f"Duplicate service names found: {[n for n in names if names.count(n) > 1]}"
        )

    async def test_key_pdf_services_present(self):
        """Test that key services from the PDF catalog are present."""
        from database.connection import get_async_session

        key_services = [
            # Critical services that must exist
            "Cortar",
            "Peinado",
            "Mechas",
            "Mechas Localizadas",
            "Mechas Localizadas Express",
            "Óleo Pigmento",
            "Barro",
            "Barro Gold",
            "Agua Lluvia",
            "Agua Tierra",
            "Corte Caballero",
            "Barba",
            "Color Caballero",
            "Recogido Novia",
            "Maquillaje Novia",
            "Bioterapia Facial",
            "Manicura Permanente + Bio",
            "Pedicura Permanente con Bioterapia",
            "Cera Enteras",
            "Masaje Corporal (60 min)",
        ]

        async with get_async_session() as session:
            for service_name in key_services:
                stmt = select(Service).where(
                    Service.name == service_name,
                    Service.is_active == True
                )
                result = await session.execute(stmt)
                service = result.scalar_one_or_none()

                assert service is not None, f"Key service '{service_name}' not found in database"

    async def test_mechas_variants_have_different_durations(self):
        """Test that Mechas variants have different durations as per PDF."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            # Mechas Localizadas: 20 min
            stmt = select(Service).where(Service.name == "Mechas Localizadas")
            result = await session.execute(stmt)
            localizadas = result.scalar_one()
            assert localizadas.duration_minutes == 20

            # Mechas Localizadas Express: 15 min
            stmt = select(Service).where(Service.name == "Mechas Localizadas Express")
            result = await session.execute(stmt)
            express = result.scalar_one()
            assert express.duration_minutes == 15

            # Regular Mechas: 60 min
            stmt = select(Service).where(Service.name == "Mechas")
            result = await session.execute(stmt)
            mechas = result.scalar_one()
            assert mechas.duration_minutes == 60

            # Mechas Extras: 70 min
            stmt = select(Service).where(Service.name == "Mechas Extras")
            result = await session.execute(stmt)
            extras = result.scalar_one()
            assert extras.duration_minutes == 70

    async def test_seed_idempotent(self):
        """Test that running seed_services multiple times is idempotent."""
        from database.connection import get_async_session

        # Run seed again
        await seed_services()

        # Count should still be 77
        async with get_async_session() as session:
            stmt = select(Service).where(Service.is_active == True)
            result = await session.execute(stmt)
            services = list(result.scalars().all())

        assert len(services) == 77, "Seed should be idempotent"
