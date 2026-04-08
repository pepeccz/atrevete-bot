"""
Integration smoke tests for the Store API cross-conversation memory round-trip (TASK-7).

Uses InMemoryStore — no real Redis, no real PostgreSQL.

Tests:
- test_full_round_trip_new_to_returning_customer: end-to-end read → write → inject cycle
  across two bookings, verifying visit_count increments and prompt injection works.
- test_store_down_graceful_degradation: ConnectionError on every Store call → both
  read and write return without raising.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langgraph.store.memory import InMemoryStore

from agent.prompts.loader import _build_customer_memory_context, _build_simple_dynamic_context
from agent.services.customer_memory_service import read_customer_memories, write_customer_memories

# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

PHONE = "+34611223344"

# A PG session that always returns None (no customer row → forces Store-only path)
_NULL_PG_SESSION_CTX = None


def _null_pg_session():
    """Async context manager that yields a session returning None from every execute."""

    @asynccontextmanager
    async def _ctx():
        session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=result_mock)
        session.commit = AsyncMock()
        yield session

    return _ctx()


def _make_booking(services, stylist_name, stylist_id, start_time, notes=None):
    return {
        "service_names": services,
        "stylist_name": stylist_name,
        "stylist_id": stylist_id,
        "no_preference_stylist": False,
        "start_time": start_time,
        "notes": notes,
    }


# ────────────────────────────────────────────────────────────────────────────
# Test 1 — Full round-trip: new → returning customer
# ────────────────────────────────────────────────────────────────────────────


async def test_full_round_trip_new_to_returning_customer():
    """
    Exercises the complete read → write → inject pipeline using InMemoryStore only.

    Steps:
    1. Read for unknown phone → None (Store miss, PG miss)
    2. Write first booking → preferences stored with visit_count=1
    3. Read again → returns stored preferences (visit_count=1)
    4. Write second booking → preferences updated with visit_count=2
    5. Read again → visit_count=2
    6. Build dynamic context → contains '## Historial del cliente' and 'Visitas anteriores: 2'
    """
    store = InMemoryStore()

    booking_1 = _make_booking(
        services=["CORTE"],
        stylist_name="Pilar",
        stylist_id="stylist-uuid-1",
        start_time="2026-04-10T10:00:00",
    )
    booking_2 = _make_booking(
        services=["TINTE"],
        stylist_name="Pilar",
        stylist_id="stylist-uuid-1",
        start_time="2026-04-17T11:00:00",
    )

    with (
        patch("agent.services.customer_memory_service.get_store", return_value=store),
        patch(
            "agent.services.customer_memory_service.get_async_session",
            side_effect=lambda: _null_pg_session(),
        ),
    ):
        # ── Step 1: first read → None (new customer, Store empty)
        result_before = await read_customer_memories(PHONE)
        assert result_before is None, "New customer should have no memories"

        # ── Step 2: write first booking (existing_prefs=None)
        await write_customer_memories(PHONE, booking_1, existing_prefs=None)

        # ── Step 3: read after first write → visit_count=1
        memories_after_1 = await read_customer_memories(PHONE)
        assert memories_after_1 is not None, "Memories should be present after first booking"
        assert memories_after_1["visit_count"] == 1
        assert "CORTE" in memories_after_1["typical_services"]

        # ── Step 4: write second booking, passing existing prefs
        await write_customer_memories(PHONE, booking_2, existing_prefs=memories_after_1)

        # ── Step 5: read again → visit_count=2
        memories_after_2 = await read_customer_memories(PHONE)
        assert memories_after_2 is not None
        assert memories_after_2["visit_count"] == 2, (
            f"Expected visit_count=2, got {memories_after_2['visit_count']}"
        )

        # ── Step 6: build dynamic context → assert memory section injected
        context = _build_simple_dynamic_context(
            {"customer_memories": memories_after_2, "customer_phone": PHONE}
        )
        assert "## Historial del cliente" in context, (
            "Dynamic context must contain memory section header"
        )
        assert "Visitas anteriores: 2" in context, (
            "Dynamic context must show visit_count=2"
        )

        # Also verify _build_customer_memory_context directly
        direct_section = _build_customer_memory_context(memories_after_2)
        assert "## Historial del cliente" in direct_section
        assert "Visitas anteriores: 2" in direct_section


# ────────────────────────────────────────────────────────────────────────────
# Test 2 — Graceful degradation when Store is down
# ────────────────────────────────────────────────────────────────────────────


async def test_store_down_graceful_degradation():
    """
    Both read and write must return without raising when Store raises ConnectionError.

    Patches get_store() to return a mock whose aget/aput raise ConnectionError.
    PG fallback also returns None (no row found).
    Verifies: no exception propagates, read returns None.
    """
    broken_store = AsyncMock()
    broken_store.aget = AsyncMock(side_effect=ConnectionError("Redis is down"))
    broken_store.aput = AsyncMock(side_effect=ConnectionError("Redis is down"))

    booking = _make_booking(
        services=["BRUSHING"],
        stylist_name="Laura",
        stylist_id="stylist-uuid-2",
        start_time="2026-04-11T09:00:00",
    )

    with (
        patch("agent.services.customer_memory_service.get_store", return_value=broken_store),
        patch(
            "agent.services.customer_memory_service.get_async_session",
            side_effect=lambda: _null_pg_session(),
        ),
    ):
        # read must not raise — returns None (Store error + PG miss)
        result = await read_customer_memories(PHONE)
        assert result is None, "read_customer_memories must return None when Store is down"

        # write must not raise — Store fails, PG session proceeds but returns None row
        await write_customer_memories(PHONE, booking, existing_prefs=None)
        # If we reach here without an exception, degradation is working correctly
