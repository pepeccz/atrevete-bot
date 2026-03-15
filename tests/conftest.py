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

# jose (python-jose) — needed by api/routes/admin.py for JWT handling
if "jose" not in sys.modules:
    class _JWTError(Exception):
        """Minimal stub that mimics jose.JWTError."""
        pass

    def _jwt_encode(payload, key, algorithm=None):
        return "stub_token"

    def _jwt_decode(token, key, algorithms=None, **kwargs):
        return {"sub": "test"}

    sys.modules["jose"] = _make_stub_module("jose", JWTError=_JWTError)
    sys.modules["jose.jwt"] = _make_stub_module(
        "jose.jwt", encode=_jwt_encode, decode=_jwt_decode
    )

# passlib — needed by api/routes/admin.py for bcrypt password hashing
if "passlib" not in sys.modules:
    class _bcrypt_stub:
        """Minimal stub that mimics passlib.hash.bcrypt."""
        @staticmethod
        def hash(password):
            return "hashed_password_stub"

        @staticmethod
        def verify(password, hash):
            return True

    sys.modules["passlib"] = _make_stub_module("passlib")
    sys.modules["passlib.hash"] = _make_stub_module("passlib.hash", bcrypt=_bcrypt_stub)

# groq — needed by api/routes/chatwoot.py for audio transcription
if "groq" not in sys.modules:
    class _RateLimitError(Exception):
        """Minimal stub that mimics groq.RateLimitError."""
        pass

    class _APIError(Exception):
        """Minimal stub that mimics groq.APIError."""
        pass

    class _AsyncGroq_stub:
        """Minimal stub that mimics groq.AsyncGroq."""
        pass

    sys.modules["groq"] = _make_stub_module(
        "groq", RateLimitError=_RateLimitError, APIError=_APIError, AsyncGroq=_AsyncGroq_stub
    )

# pydub — needed by shared/audio_conversion.py for audio conversion
if "pydub" not in sys.modules:
    class _AudioSegment_stub:
        """Minimal stub that mimics pydub.AudioSegment."""
        @staticmethod
        def from_ogg(path):
            return _AudioSegment_stub()

        def export(self, path, format=None):
            return self

    sys.modules["pydub"] = _make_stub_module("pydub", AudioSegment=_AudioSegment_stub)


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
