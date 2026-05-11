"""Integration fixtures for booking regression tests (PR-4 / Slice 4).

Fixtures:
  - db_with_seeds: session-scoped async DB session. Skips gracefully if Postgres
    is unreachable (same pattern used across the integration suite).
  - stub_llm: simple callable that returns canned tool-call responses without
    hitting a real LLM. Suitable for structural prompt assertions.
  - conv_factory: helper that builds a minimal conversation state dict for
    tool-level invocations.

Refs: design §2 Slice 4, tasks 4.1
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Postgres reachability probe — shared graceful-skip helper
# ---------------------------------------------------------------------------

_POSTGRES_REACHABLE: bool | None = None  # cached per session


def _postgres_is_reachable() -> bool:
    """Probe the test DB once per session. Returns False if unreachable."""
    global _POSTGRES_REACHABLE
    if _POSTGRES_REACHABLE is not None:
        return _POSTGRES_REACHABLE
    try:
        import socket

        s = socket.create_connection(("localhost", 5432), timeout=1)
        s.close()
        _POSTGRES_REACHABLE = True
    except OSError:
        _POSTGRES_REACHABLE = False
    return _POSTGRES_REACHABLE


# ---------------------------------------------------------------------------
# db_with_seeds — session-scoped async DB session (skips if no Postgres)
# ---------------------------------------------------------------------------


@pytest.fixture
async def db_with_seeds():
    """Async session connected to the test DB (post-alembic-upgrade state).

    Function-scoped (matches asyncio_default_fixture_loop_scope="function" in pyproject.toml).
    Skips the test gracefully when Postgres is not reachable (local dev without
    Docker or CI without DB service). The skip matches the pattern established
    by PR-2 DB-dependent tests.
    """
    if not _postgres_is_reachable():
        pytest.skip("Postgres not reachable — skipping DB-dependent integration test")

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
