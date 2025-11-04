"""
Unit tests for business_hours_tools module.

Tests business hours retrieval and formatting from database.
"""

import pytest
from sqlalchemy import text

from agent.tools.business_hours_tools import get_business_hours
from database.connection import AsyncSessionLocal, engine
from database.models import Base
from database.seeds.business_hours import seed_business_hours


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

        # Enable extensions FIRST
        await conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"'))

        # Create fresh tables
        await conn.run_sync(Base.metadata.create_all)

    # Seed business hours
    await seed_business_hours()

    yield

    # Cleanup after test
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
class TestGetBusinessHours:
    """Test get_business_hours tool."""

    async def test_get_business_hours_returns_all_days(self):
        """Test that get_business_hours returns data for all 7 days."""
        # Act
        result = await get_business_hours.ainvoke({})

        # Assert
        assert "schedule" in result
        assert "formatted" in result
        assert len(result["schedule"]) == 7, "Should return 7 days (Monday-Sunday)"

    async def test_business_hours_includes_closed_days(self):
        """Test that closed days (Monday, Sunday) are marked correctly."""
        # Act
        result = await get_business_hours.ainvoke({})
        schedule = result["schedule"]

        # Find Monday and Sunday
        monday = next((day for day in schedule if day["day"] == "Lunes"), None)
        sunday = next((day for day in schedule if day["day"] == "Domingo"), None)

        # Assert
        assert monday is not None
        assert monday["is_closed"] is True
        assert monday["hours"] == "Cerrado"

        assert sunday is not None
        assert sunday["is_closed"] is True
        assert sunday["hours"] == "Cerrado"

    async def test_business_hours_includes_open_days(self):
        """Test that open days have correct time ranges."""
        # Act
        result = await get_business_hours.ainvoke({})
        schedule = result["schedule"]

        # Find Tuesday (should be open 10:00-20:00)
        tuesday = next((day for day in schedule if day["day"] == "Martes"), None)

        # Assert
        assert tuesday is not None
        assert tuesday["is_closed"] is False
        assert "10:00" in tuesday["hours"]
        assert "20:00" in tuesday["hours"]

    async def test_formatted_summary_is_readable(self):
        """Test that formatted summary is human-readable Spanish text."""
        # Act
        result = await get_business_hours.ainvoke({})
        formatted = result["formatted"]

        # Assert
        assert isinstance(formatted, str)
        assert len(formatted) > 0
        # Should mention at least some days
        assert "Martes" in formatted or "Lunes" in formatted
        # Should include time format
        assert ":" in formatted  # Time separator

    async def test_schedule_is_ordered_by_day_of_week(self):
        """Test that schedule is ordered Monday (0) to Sunday (6)."""
        # Act
        result = await get_business_hours.ainvoke({})
        schedule = result["schedule"]

        # Assert
        day_names = [day["day"] for day in schedule]
        assert day_names[0] == "Lunes"  # Monday first
        assert day_names[6] == "Domingo"  # Sunday last

    async def test_handles_empty_database_gracefully(self):
        """Test tool returns error when no business hours configured."""
        # Arrange: Truncate business_hours table
        async with engine.begin() as conn:
            await conn.execute(text("TRUNCATE TABLE business_hours CASCADE"))

        # Act
        result = await get_business_hours.ainvoke({})

        # Assert
        assert "error" in result
        assert result["schedule"] == []
        assert "No hay horarios configurados" in result["formatted"]
