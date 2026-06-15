"""Integration fixtures for booking regression tests (PR-4 / Slice 4).

Fixtures:
  - db_with_seeds: session-scoped async DB session with services catalog seeded.
    Skips gracefully if Postgres is unreachable (same pattern used across the
    integration suite).
  - stub_llm: simple callable that returns canned tool-call responses without
    hitting a real LLM. Suitable for structural prompt assertions.
  - conv_factory: helper that builds a minimal conversation state dict for
    tool-level invocations.

Refs: design §2 Slice 4, tasks 4.1
"""

from __future__ import annotations

import os
import re
import socket
from typing import Any
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Postgres reachability probe — reads port from DATABASE_URL env var
# ---------------------------------------------------------------------------

_POSTGRES_REACHABLE: bool | None = None  # cached per session


def _db_host_port() -> tuple[str, int]:
    """Extract host and port from DATABASE_URL env var.

    Falls back to localhost:5432 when DATABASE_URL is absent or unparseable.
    Supports the asyncpg URL scheme used in CI:
        postgresql+asyncpg://user:pass@host:port/dbname
    """
    url = os.environ.get("DATABASE_URL", "")
    m = re.search(r"@([^:/]+):(\d+)/", url)
    if m:
        return m.group(1), int(m.group(2))
    return "localhost", 5432


def _postgres_is_reachable() -> bool:
    """Probe the configured test DB host:port once per session."""
    global _POSTGRES_REACHABLE
    if _POSTGRES_REACHABLE is not None:
        return _POSTGRES_REACHABLE
    host, port = _db_host_port()
    try:
        s = socket.create_connection((host, port), timeout=2)
        s.close()
        _POSTGRES_REACHABLE = True
    except OSError:
        _POSTGRES_REACHABLE = False
    return _POSTGRES_REACHABLE


# ---------------------------------------------------------------------------
# _seed_catalog — idempotent one-time seeding helper (module-scoped)
# ---------------------------------------------------------------------------

_CATALOG_SEEDED: bool = False  # module-level flag, reset per process


async def _ensure_catalog_seeded() -> None:
    """Seed the services catalog if the table is empty.

    Idempotent: checks row count first; only seeds when the table is empty.
    This avoids TRUNCATE (which would cascade to appointments) while still
    guaranteeing a seeded state for CI where the test DB starts empty.
    """
    global _CATALOG_SEEDED
    if _CATALOG_SEEDED:
        return

    from sqlalchemy import text

    from database.connection import get_async_session
    from database.seeds.services import seed_services
    from database.seeds.stylists import seed_stylists

    async with get_async_session() as s:
        row = await s.execute(text("SELECT COUNT(*) FROM services"))
        count = row.scalar()

    if count == 0:
        await seed_services()
        await seed_stylists()

    _CATALOG_SEEDED = True


# ---------------------------------------------------------------------------
# db_with_seeds — function-scoped async DB session, catalog pre-seeded
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_with_seeds():
    """Async session connected to the test DB with the service catalog seeded.

    Function-scoped (matches asyncio_default_fixture_loop_scope="function" in pyproject.toml).

    Lifecycle:
    1. Skip gracefully when Postgres is not reachable (local dev without Docker
       or CI without DB service).
    2. Seed services + stylists if the services table is empty (idempotent).
    3. Yield a fresh session for the test body.

    The seed step only runs once per process (module-level flag). Subsequent
    tests in the same session reuse the already-seeded catalog.
    """
    if not _postgres_is_reachable():
        pytest.skip("Postgres not reachable — skipping DB-dependent integration test")

    try:
        await _ensure_catalog_seeded()
    except Exception as exc:
        pytest.skip(f"Catalog seed failed ({type(exc).__name__}: {exc})")

    try:
        from database.connection import get_async_session

        async with get_async_session() as session:
            yield session
    except Exception as exc:
        pytest.skip(f"DB session failed ({type(exc).__name__}: {exc})")


# ---------------------------------------------------------------------------
# stub_llm — canned assistant turn generator (no real LLM)
# ---------------------------------------------------------------------------


class StubLLM:
    """Minimal fake LLM for structural prompt assertions.

    Returns canned responses based on the last tool call or a fixed default.
    Not meant to simulate conversational quality — only used to assert that
    the PROMPT REACHES the model with the right content.
    """

    def __init__(self, canned_responses: list[str] | None = None) -> None:
        self._responses = list(canned_responses or ["Canned LLM response."])
        self._call_count = 0

    def __call__(self, *args: Any, **kwargs: Any) -> str:
        idx = min(self._call_count, len(self._responses) - 1)
        self._call_count += 1
        return self._responses[idx]

    def reset(self) -> None:
        self._call_count = 0


@pytest.fixture(scope="module")
def stub_llm() -> StubLLM:
    """Module-scoped fake LLM returning canned responses."""
    return StubLLM()


# ---------------------------------------------------------------------------
# conv_factory — minimal conversation state builder for tool-level tests
# ---------------------------------------------------------------------------


def _make_conv_state(
    services: list[str] | None = None,
    customer_phone: str = "+34600000099",
    customer_name: str | None = None,
    today_iso: str = "2026-05-11",
    conversation_id: str | None = None,
) -> dict[str, Any]:
    """Build a minimal conversation state dict for tool invocations.

    Provides the essential keys that update_booking and availability tools
    read from AgentState without requiring a full LangGraph execution.
    """
    return {
        "conversation_id": conversation_id or str(uuid4()),
        "customer_phone": customer_phone,
        "customer_name": customer_name,
        "today_iso": today_iso,
        "messages": [],
        "booking_context": {
            "services": services or [],
            "stylist_id": None,
            "date_iso": None,
            "slot_iso": None,
            "customer_full_name": customer_name,
            "notes": None,
            "extras_asked": False,
            "notes_asked": False,
            "customer_known": customer_name is not None,
            "no_more_services": False,
        },
    }


@pytest.fixture
def conv_factory():
    """Return the _make_conv_state helper for building conversation state seeds."""
    return _make_conv_state
