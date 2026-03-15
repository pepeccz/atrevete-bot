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
        """Test that all 77 services from catalog are present in database."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            stmt = select(Service).where(Service.is_active == True)
            result = await session.execute(stmt)
            services = list(result.scalars().all())

        # Assert: Exactly 77 services (36 hairdressing + 41 aesthetics)
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

        # Count should still be 77 (36 hairdressing + 41 aesthetics)
        async with get_async_session() as session:
            stmt = select(Service).where(Service.is_active == True)
            result = await session.execute(stmt)
            services = list(result.scalars().all())

        assert len(services) == 77, "Seed should be idempotent"


@pytest.mark.asyncio
class TestServiceDisambiguationMetadata:
    """Tests for Phase 1 disambiguation metadata seeded on ambiguous service families."""

    # ------------------------------------------------------------------ helpers

    async def _get_service(self, session, name: str) -> "Service":
        from database.connection import get_async_session  # noqa: F401

        stmt = select(Service).where(Service.name == name)
        result = await session.execute(stmt)
        svc = result.scalar_one_or_none()
        assert svc is not None, f"Service '{name}' not found in database"
        return svc

    # ------------------------------------------------------------------ haircut family

    async def test_corte_bebe_metadata(self):
        """Corte Bebé must have family=haircut, audience=baby, no ask_if_missing."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            svc = await self._get_service(session, "Corte Bebé")

        assert svc.metadata_["family"] == "haircut"
        assert svc.metadata_["audience"] == "baby"
        assert svc.metadata_["ask_if_missing"] == []
        assert svc.duration_minutes == 20

    async def test_corte_nino_metadata(self):
        """Corte Niño must have family=haircut, audience=child_male."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            svc = await self._get_service(session, "Corte Niño")

        assert svc.metadata_["family"] == "haircut"
        assert svc.metadata_["audience"] == "child_male"
        assert svc.metadata_["ask_if_missing"] == []
        assert svc.duration_minutes == 30

    async def test_corte_nina_metadata(self):
        """Corte Niña must have family=haircut, audience=child_female."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            svc = await self._get_service(session, "Corte Niña")

        assert svc.metadata_["family"] == "haircut"
        assert svc.metadata_["audience"] == "child_female"
        assert svc.metadata_["ask_if_missing"] == []
        assert svc.duration_minutes == 30

    async def test_corte_caballero_metadata(self):
        """Corte Caballero must have family=haircut, audience=adult_male."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            svc = await self._get_service(session, "Corte Caballero")

        assert svc.metadata_["family"] == "haircut"
        assert svc.metadata_["audience"] == "adult_male"
        assert svc.metadata_["ask_if_missing"] == []
        assert svc.duration_minutes == 40

    async def test_cortar_metadata(self):
        """Cortar (corte dama) must have family=haircut, audience=adult_female, ask_if_missing empty."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            svc = await self._get_service(session, "Cortar")

        assert svc.metadata_["family"] == "haircut"
        assert svc.metadata_["audience"] == "adult_female"
        assert svc.metadata_["ask_if_missing"] == []
        assert svc.duration_minutes == 40

    # ------------------------------------------------------------------ highlights family

    async def test_mechas_metadata(self):
        """Mechas must have family=highlights, hair_density=normal, ask_if_missing hair_density."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            svc = await self._get_service(session, "Mechas")

        assert svc.metadata_["family"] == "highlights"
        assert svc.metadata_["hair_density"] == "normal"
        assert svc.metadata_["variant"] == "standard"
        assert "hair_density" in svc.metadata_["ask_if_missing"]
        assert svc.duration_minutes == 60

    async def test_mechas_extras_metadata(self):
        """Mechas Extras must have family=highlights, hair_density=extra, no ask_if_missing."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            svc = await self._get_service(session, "Mechas Extras")

        assert svc.metadata_["family"] == "highlights"
        assert svc.metadata_["hair_density"] == "extra"
        assert svc.metadata_["variant"] == "extra"
        assert svc.metadata_["ask_if_missing"] == []
        assert svc.duration_minutes == 70

    # ------------------------------------------------------------------ hairstyle family

    async def test_peinado_metadata(self):
        """Peinado must have family=hairstyle, hair_length=short_medium, ask_if_missing hair_length."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            svc = await self._get_service(session, "Peinado")

        assert svc.metadata_["family"] == "hairstyle"
        assert svc.metadata_["hair_length"] == "short_medium"
        assert svc.metadata_["variant"] == "standard"
        assert "hair_length" in svc.metadata_["ask_if_missing"]
        assert svc.duration_minutes == 40

    async def test_peinado_largo_metadata(self):
        """Peinado Largo must have family=hairstyle, hair_length=long, no ask_if_missing."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            svc = await self._get_service(session, "Peinado Largo")

        assert svc.metadata_["family"] == "hairstyle"
        assert svc.metadata_["hair_length"] == "long"
        assert svc.metadata_["variant"] == "long"
        assert svc.metadata_["ask_if_missing"] == []
        assert svc.duration_minutes == 45

    async def test_peinado_extra_metadata(self):
        """Peinado Extra must have family=hairstyle, hair_length=long, hair_density=extra."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            svc = await self._get_service(session, "Peinado Extra")

        assert svc.metadata_["family"] == "hairstyle"
        assert svc.metadata_["hair_length"] == "long"
        assert svc.metadata_["hair_density"] == "extra"
        assert svc.metadata_["variant"] == "extra"
        assert svc.metadata_["ask_if_missing"] == []
        assert svc.duration_minutes == 70

    # ------------------------------------------------------------------ perm family

    async def test_moldeado_metadata(self):
        """Moldeado must have family=perm, hair_density=normal, ask_if_missing hair_density."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            svc = await self._get_service(session, "Moldeado")

        assert svc.metadata_["family"] == "perm"
        assert svc.metadata_["hair_density"] == "normal"
        assert svc.metadata_["variant"] == "standard"
        assert "hair_density" in svc.metadata_["ask_if_missing"]
        assert svc.duration_minutes == 50

    async def test_moldeado_extra_metadata(self):
        """Moldeado Extra must have family=perm, hair_density=extra, no ask_if_missing."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            svc = await self._get_service(session, "Moldeado Extra")

        assert svc.metadata_["family"] == "perm"
        assert svc.metadata_["hair_density"] == "extra"
        assert svc.metadata_["variant"] == "extra"
        assert svc.metadata_["ask_if_missing"] == []
        assert svc.duration_minutes == 70

    # ------------------------------------------------------------------ color family

    async def test_cultura_de_color_metadata(self):
        """Cultura de Color must have family=color, hair_density=normal, ask_if_missing hair_density."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            svc = await self._get_service(session, "Cultura de Color")

        assert svc.metadata_["family"] == "color"
        assert svc.metadata_["hair_density"] == "normal"
        assert svc.metadata_["variant"] == "standard"
        assert "hair_density" in svc.metadata_["ask_if_missing"]
        assert svc.duration_minutes == 40

    async def test_cultura_de_color_extra_metadata(self):
        """Cultura de Color Extra must have family=color, hair_density=extra, no ask_if_missing."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            svc = await self._get_service(session, "Cultura de Color Extra")

        assert svc.metadata_["family"] == "color"
        assert svc.metadata_["hair_density"] == "extra"
        assert svc.metadata_["variant"] == "extra"
        assert svc.metadata_["ask_if_missing"] == []
        assert svc.duration_minutes == 50

    # ------------------------------------------------------------------ non-seeded services have empty metadata

    async def test_non_seeded_services_have_empty_metadata(self):
        """Services not in ambiguous families must have metadata_ == {}."""
        from database.connection import get_async_session

        # Services explicitly outside Phase 1 scope
        non_seeded = [
            "Óleo Pigmento",
            "Agua Tierra",
            "Barba",
            "Barro",
            "Barro Gold",
            "Mechas Localizadas",
            "Mechas Localizadas Express",
            "Recogido",
            "Semirecogido",
            "Recogido Novia",
            "Color Caballero",
            "Perilla",
            "Corte de Flequillo",
            "Peinado Niña Comunión",
            "Secado",
        ]

        async with get_async_session() as session:
            for name in non_seeded:
                svc = await self._get_service(session, name)
                assert svc.metadata_ == {}, (
                    f"Service '{name}' should have empty metadata_ but got: {svc.metadata_}"
                )

    # ------------------------------------------------------------------ duration spot-checks

    async def test_haircut_family_durations(self):
        """Verify exact durations for all haircut-family services."""
        from database.connection import get_async_session

        expected_durations = {
            "Corte Bebé": 20,
            "Corte Niño": 30,
            "Corte Niña": 30,
            "Corte Caballero": 40,
            "Cortar": 40,
        }

        async with get_async_session() as session:
            for name, expected_duration in expected_durations.items():
                svc = await self._get_service(session, name)
                assert svc.duration_minutes == expected_duration, (
                    f"Service '{name}' expected {expected_duration} min, got {svc.duration_minutes}"
                )

    async def test_all_seeded_services_have_disambiguation_tags(self):
        """All services with non-empty metadata_ must have non-empty disambiguation_tags."""
        from database.connection import get_async_session

        async with get_async_session() as session:
            stmt = select(Service).where(Service.is_active == True)
            result = await session.execute(stmt)
            services = list(result.scalars().all())

        for svc in services:
            if svc.metadata_:
                tags = svc.metadata_.get("disambiguation_tags", [])
                assert isinstance(tags, list), (
                    f"Service '{svc.name}' disambiguation_tags must be a list"
                )
                assert len(tags) > 0, (
                    f"Service '{svc.name}' has metadata but empty disambiguation_tags"
                )
