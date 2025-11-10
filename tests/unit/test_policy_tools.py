"""
Unit tests for policy_tools module.

Tests cancellation policy retrieval from database.
"""

import pytest
from sqlalchemy import text

from agent.tools.policy_tools import get_cancellation_policy
from database.connection import AsyncSessionLocal, engine
from database.models import Base
from database.seeds.policies import seed_policies


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

    # Seed policies
    await seed_policies()

    yield

    # Cleanup after test
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest.mark.asyncio
class TestGetCancellationPolicy:
    """Test get_cancellation_policy tool."""

    async def test_get_cancellation_policy_returns_threshold(self):
        """Test that get_cancellation_policy returns threshold_hours."""
        # Act
        result = await get_cancellation_policy.ainvoke({})

        # Assert
        assert "threshold_hours" in result
        assert "formatted" in result

    async def test_cancellation_threshold_is_24_hours(self):
        """Test that cancellation threshold is 24 hours as configured."""
        # Act
        result = await get_cancellation_policy.ainvoke({})

        # Assert
        assert result["threshold_hours"] == 24

    async def test_formatted_summary_is_readable(self):
        """Test that formatted summary is human-readable Spanish text."""
        # Act
        result = await get_cancellation_policy.ainvoke({})
        formatted = result["formatted"]

        # Assert
        assert isinstance(formatted, str)
        assert len(formatted) > 0
        # Should mention key concepts
        assert "Cancelación" in formatted or "cancelación" in formatted
        assert "24 horas" in formatted
        assert "reembolso" in formatted

    async def test_formatted_includes_refund_conditions(self):
        """Test that formatted text explains refund conditions."""
        # Act
        result = await get_cancellation_policy.ainvoke({})
        formatted = result["formatted"]

        # Assert
        # Should explain both scenarios (>24h and <=24h)
        assert "más de 24 horas" in formatted or "más de" in formatted
        assert "reembolso" in formatted

    async def test_handles_missing_policy_with_fallback(self):
        """Test tool returns fallback when cancellation policy missing."""
        # Arrange: Delete cancellation policy
        async with engine.begin() as conn:
            await conn.execute(text(
                "DELETE FROM policies WHERE key = 'cancellation_threshold_hours'"
            ))

        # Act
        result = await get_cancellation_policy.ainvoke({})

        # Assert
        assert "error" in result
        assert result["threshold_hours"] == 24  # Fallback default
