"""
Test configuration and fixtures.

This module sets up test environment and provides shared fixtures for all tests.
"""

import asyncio
import os
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest



# Override DATABASE_URL and REDIS_URL for tests to use localhost instead of Docker hostname
# Must be set BEFORE any imports of database.connection or shared.config
# Skip override if running inside Docker (where postgres/redis hostnames resolve)
def _is_running_in_docker() -> bool:
    """Check if we're running inside a Docker container."""
    import socket
    # Try to resolve Docker service hostnames
    docker_hosts = ["postgres", "redis", "atrevete-postgres", "atrevete-redis"]
    for host in docker_hosts:
        try:
            socket.gethostbyname(host)
            return True  # Can resolve Docker hostname, we're in Docker
        except socket.gaierror:
            continue
    return False


if not _is_running_in_docker():
    # Only override when running locally (not in Docker)
    os.environ["DATABASE_URL"] = (
        "postgresql+asyncpg://atrevete:changeme_min16chars_secure_password@localhost:5432/atrevete_db"
    )
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"


# ---------------------------------------------------------------------------
# Stub Docker-only packages that are not installed in the local test environment.
#
# These packages are only available inside the Docker container but several
# project modules import them at the top level (not lazily). We stub them here
# so that `import agent.services.*` works in all unit tests without Docker.
#
# Pattern: create a real ModuleType (not MagicMock) so that
#   `from pkg import name`
# works — Python's import machinery does a real getattr() on the module object.
# ---------------------------------------------------------------------------
def _make_stub_module(name: str, **attrs) -> ModuleType:
    mod = ModuleType(name)
    mod.__name__ = name
    mod.__package__ = name.split(".")[0]
    mod.__spec__ = None
    for k, v in attrs.items():
        setattr(mod, k, v)
    return mod


# google_auth_oauthlib — needed by agent/services/google_oauth_service.py
if "google_auth_oauthlib" not in sys.modules:
    sys.modules["google_auth_oauthlib"] = _make_stub_module("google_auth_oauthlib")
    sys.modules["google_auth_oauthlib.flow"] = _make_stub_module(
        "google_auth_oauthlib.flow", Flow=MagicMock()
    )

# googleapiclient — needed by gcal_push_service, calendar_tools, gcal_sync_worker.
# HttpError must be a proper class (not just `Exception`) so that tests which
# construct it via `HttpError(resp=..., content=...)` still work correctly.
if "googleapiclient" not in sys.modules:
    class _HttpError(Exception):
        """Minimal stub that mimics googleapiclient.errors.HttpError."""
        def __init__(self, resp=None, content=b"", uri=None, **kwargs):
            self.resp = resp
            self.content = content
            self.uri = uri
            super().__init__(str(resp))

    sys.modules["googleapiclient"] = _make_stub_module("googleapiclient")
    sys.modules["googleapiclient.discovery"] = _make_stub_module(
        "googleapiclient.discovery", build=MagicMock()
    )
    sys.modules["googleapiclient.errors"] = _make_stub_module(
        "googleapiclient.errors", HttpError=_HttpError
    )


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
    # Only if we're using a real engine (not mocked)
    from database.connection import engine
    from unittest.mock import Mock
    if hasattr(engine, 'dispose') and not isinstance(engine, Mock):
        await engine.dispose()

    # Close Redis connections
    try:
        from shared.redis_client import get_redis_client
        redis_client = get_redis_client()
        if redis_client is not None and not isinstance(redis_client, Mock):
            await redis_client.close()
    except Exception:  # noqa: S110
        pass  # Redis client may not be initialized
