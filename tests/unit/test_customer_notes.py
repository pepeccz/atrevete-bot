"""
Unit tests for customer notes functionality.

Tests that the system correctly stores and retrieves customer notes
(allergies, preferences, special requests) through the manage_customer tool.
"""

import pytest
from sqlalchemy import text

from agent.tools.customer_tools import manage_customer
from database.connection import engine
from database.models import Base


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

    yield

    # Cleanup after test
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
class TestCustomerNotes:
    """Test customer notes storage and retrieval."""

    async def test_create_customer_with_notes(self):
        """Test creating a customer with notes field."""
        # Arrange
        phone = "+34612345678"
        first_name = "Pedro"
        last_name = "García"
        notes = "Alérgico al amoníaco"

        # Act
        result = await manage_customer(
            action="create",
            phone=phone,
            data={"first_name": first_name, "last_name": last_name, "notes": notes}
        )

        # Assert
        assert "id" in result
        assert result["phone"] == phone
        assert result["first_name"] == first_name
        assert result["last_name"] == last_name

        # Verify notes were stored by retrieving customer
        get_result = await manage_customer(action="get", phone=phone)
        assert get_result["notes"] == notes

    async def test_create_customer_without_notes(self):
        """Test creating a customer without notes (notes should be empty)."""
        # Arrange
        phone = "+34612345679"
        first_name = "María"
        last_name = "López"

        # Act
        result = await manage_customer(
            action="create",
            phone=phone,
            data={"first_name": first_name, "last_name": last_name}
        )

        # Assert
        assert "id" in result
        get_result = await manage_customer(action="get", phone=phone)
        assert get_result["notes"] == ""

    async def test_update_customer_notes(self):
        """Test updating customer notes after creation."""
        # Arrange: Create customer without notes
        phone = "+34612345680"
        first_name = "Ana"
        create_result = await manage_customer(
            action="create",
            phone=phone,
            data={"first_name": first_name, "last_name": "Martínez"}
        )
        customer_id = create_result["id"]

        # Act: Update with notes
        notes = "Prefiere agua fría para el lavado"
        update_result = await manage_customer(
            action="update",
            phone=phone,
            data={"customer_id": customer_id, "notes": notes}
        )

        # Assert
        assert update_result["success"] is True
        assert update_result["notes"] == notes

        # Verify persistence
        get_result = await manage_customer(action="get", phone=phone)
        assert get_result["notes"] == notes

    async def test_update_customer_notes_to_empty(self):
        """Test clearing customer notes by updating to empty string."""
        # Arrange: Create customer with notes
        phone = "+34612345681"
        first_name = "Luis"
        notes = "Piel sensible"
        create_result = await manage_customer(
            action="create",
            phone=phone,
            data={"first_name": first_name, "last_name": "Fernández", "notes": notes}
        )
        customer_id = create_result["id"]

        # Act: Update notes to empty
        update_result = await manage_customer(
            action="update",
            phone=phone,
            data={"customer_id": customer_id, "notes": ""}
        )

        # Assert
        assert update_result["success"] is True
        assert update_result["notes"] == ""

    async def test_update_customer_notes_without_changing_name(self):
        """Test updating only notes without changing name."""
        # Arrange: Create customer
        phone = "+34612345682"
        first_name = "Carmen"
        last_name = "Ruiz"
        create_result = await manage_customer(
            action="create",
            phone=phone,
            data={"first_name": first_name, "last_name": last_name}
        )
        customer_id = create_result["id"]

        # Act: Update only notes
        notes = "Prefiere citas por la mañana"
        update_result = await manage_customer(
            action="update",
            phone=phone,
            data={"customer_id": customer_id, "notes": notes}
        )

        # Assert: Name unchanged, notes updated
        assert update_result["success"] is True
        assert update_result["first_name"] == first_name
        assert update_result["last_name"] == last_name
        assert update_result["notes"] == notes

    async def test_get_customer_returns_notes_field(self):
        """Test that get_customer always returns notes field (even if empty)."""
        # Arrange: Create customer without notes
        phone = "+34612345683"
        await manage_customer(
            action="create",
            phone=phone,
            data={"first_name": "Juan", "last_name": "Sánchez"}
        )

        # Act
        result = await manage_customer(action="get", phone=phone)

        # Assert: notes field exists and is empty string
        assert "notes" in result
        assert result["notes"] == ""

    async def test_notes_with_special_characters(self):
        """Test notes field handles special characters correctly."""
        # Arrange
        phone = "+34612345684"
        first_name = "Sofía"
        notes = "Alérgica al tinte X-200. Prefiere productos \"naturales\". Evitar: ácido & amoníaco."

        # Act
        result = await manage_customer(
            action="create",
            phone=phone,
            data={"first_name": first_name, "last_name": "Moreno", "notes": notes}
        )

        # Assert
        get_result = await manage_customer(action="get", phone=phone)
        assert get_result["notes"] == notes

    async def test_notes_with_long_text(self):
        """Test notes field handles long text (up to 1000 characters)."""
        # Arrange
        phone = "+34612345685"
        first_name = "Roberto"
        # Create 500-character notes
        notes = "Información detallada del cliente. " * 20  # ~700 chars

        # Act
        result = await manage_customer(
            action="create",
            phone=phone,
            data={"first_name": first_name, "last_name": "Díaz", "notes": notes}
        )

        # Assert
        get_result = await manage_customer(action="get", phone=phone)
        assert get_result["notes"] == notes
        assert len(get_result["notes"]) > 500

    async def test_update_multiple_fields_including_notes(self):
        """Test updating name and notes simultaneously."""
        # Arrange: Create customer
        phone = "+34612345686"
        create_result = await manage_customer(
            action="create",
            phone=phone,
            data={"first_name": "Carlos", "last_name": "Vega"}
        )
        customer_id = create_result["id"]

        # Act: Update both name and notes
        update_result = await manage_customer(
            action="update",
            phone=phone,
            data={
                "customer_id": customer_id,
                "first_name": "Carlos Alberto",
                "last_name": "Vega Martín",
                "notes": "Cliente VIP - prioridad en agenda"
            }
        )

        # Assert
        assert update_result["success"] is True
        assert update_result["first_name"] == "Carlos Alberto"
        assert update_result["last_name"] == "Vega Martín"
        assert update_result["notes"] == "Cliente VIP - prioridad en agenda"
