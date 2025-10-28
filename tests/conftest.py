"""
Test configuration and fixtures.

This module sets up test environment and provides shared fixtures for all tests.
"""

import asyncio
import os

import pytest

# Override DATABASE_URL and REDIS_URL for tests to use localhost instead of Docker hostname
# Must be set BEFORE any imports of database.connection or shared.config
os.environ["DATABASE_URL"] = (
    "postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db"
)
os.environ["REDIS_URL"] = "redis://localhost:6379/0"


@pytest.fixture(scope="function")
def event_loop():
    """
    Create a new event loop for each test function.

    This prevents "Future attached to a different loop" errors with SQLAlchemy async.
    Each test gets a fresh event loop that is properly closed after the test.
    """
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture(scope="function", autouse=True)
async def cleanup_engine():
    """
    Clean up database engine and Redis connections after each test.

    This ensures connection pools don't interfere between tests and
    prevents "Future attached to different loop" errors.
    """
    yield
    # Dispose engine after each test to release connections
    from database.connection import engine
    await engine.dispose()

    # Close Redis connections
    try:
        from shared.redis_client import get_redis_client
        redis_client = get_redis_client()
        if redis_client is not None:
            await redis_client.close()
    except Exception:  # noqa: S110
        pass  # Redis client may not be initialized
