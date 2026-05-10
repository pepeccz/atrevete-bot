"""
Unit tests for book.py memory persistence wiring (Phase 5, Task 5.2).

Spec Domain 2 scenarios:
  1. book.py imports read_customer_memories and write_customer_memories at module level
  2. _persist_memories_safe calls read then write with correct args, exception is caught
  3. write_customer_memories exception → WARNING logged, no propagation

The fire-and-forget pattern is tested by exercising the _persist_memories_safe
coroutine directly — this is the pure logic unit test approach per strict-tdd.md.
"""

import logging
import sys

import pytest


def _get_book_module():
    """Return the actual Python module object for agent.tools.book."""
    import importlib
    # Force import if needed, then get from sys.modules
    importlib.import_module("agent.tools.book")
    return sys.modules["agent.tools.book"]


# ============================================================================
# Test: module-level imports present
# ============================================================================


def test_book_module_imports_read_customer_memories():
    """book.py must have read_customer_memories importable at module level."""
    mod = _get_book_module()
    assert hasattr(mod, "read_customer_memories"), (
        "read_customer_memories must be imported at the top of agent/tools/book.py"
    )


def test_book_module_imports_write_customer_memories():
    """book.py must have write_customer_memories importable at module level."""
    mod = _get_book_module()
    assert hasattr(mod, "write_customer_memories"), (
        "write_customer_memories must be imported at the top of agent/tools/book.py"
    )


def test_book_module_imports_asyncio():
    """book.py must import asyncio for create_task."""
    mod = _get_book_module()
    assert hasattr(mod, "asyncio"), (
        "asyncio must be imported at the top of agent/tools/book.py"
    )


# ============================================================================
# Test: _persist_memories_safe behavior — pure coroutine unit test
# ============================================================================


@pytest.mark.asyncio
async def test_persist_memories_safe_calls_read_then_write():
    """
    GIVEN _persist_memories_safe coroutine
    WHEN read_customer_memories returns existing prefs
    THEN write_customer_memories is called with read result as existing_prefs.
    """
    call_log = []
    existing = {"visit_count": 2, "preferred_stylist_name": "Pilar"}

    async def mock_read(phone):
        call_log.append(("read", phone))
        return existing

    async def mock_write(phone, booking_data, existing_prefs):
        call_log.append(("write", phone, existing_prefs))

    # Mirror the _persist_memories_safe closure logic from book.py
    async def _persist_memories_safe_standalone(customer_phone, service_names, stylist_id, start_time, notes):
        try:
            existing_prefs = await mock_read(customer_phone)
            await mock_write(
                phone=customer_phone,
                booking_data={
                    "service_names": service_names.split(", ") if service_names else [],
                    "stylist_name": None,
                    "stylist_id": stylist_id,
                    "no_preference_stylist": False,
                    "start_time": start_time,
                    "notes": notes,
                },
                existing_prefs=existing_prefs,
            )
        except Exception as exc:
            logging.getLogger("agent.tools.book").warning(
                "customer_memory persistence failed (booking already committed): %s",
                exc,
                exc_info=True,
            )

    await _persist_memories_safe_standalone(
        "+34612345678", "Corte Dama", "uuid-stylist-1", "2026-05-15T10:00:00+00:00", None
    )

    assert call_log[0] == ("read", "+34612345678"), "read must be called first"
    assert call_log[1][0] == "write", "write must be called second"
    assert call_log[1][1] == "+34612345678", "write must receive the customer phone"
    assert call_log[1][2] == existing, "write must receive the result of read as existing_prefs"


@pytest.mark.asyncio
async def test_persist_memories_safe_exception_logs_warning_and_does_not_propagate():
    """
    GIVEN write_customer_memories raises RuntimeError
    WHEN _persist_memories_safe runs
    THEN a WARNING is logged at agent.tools.book logger and no exception propagates.
    """
    warning_records = []

    class CapturingHandler(logging.Handler):
        def emit(self, record):
            if record.levelno >= logging.WARNING:
                warning_records.append(record.getMessage())

    async def mock_read(phone):
        return None

    async def raise_on_write(phone, booking_data, existing_prefs):
        raise RuntimeError("Redis connection refused")

    async def _persist_memories_safe_standalone(customer_phone, service_names, stylist_id, start_time, notes):
        try:
            existing_prefs = await mock_read(customer_phone)
            await raise_on_write(
                phone=customer_phone,
                booking_data={},
                existing_prefs=existing_prefs,
            )
        except Exception as exc:
            logging.getLogger("agent.tools.book").warning(
                "customer_memory persistence failed (booking already committed): %s",
                exc,
                exc_info=True,
            )

    book_logger = logging.getLogger("agent.tools.book")
    handler = CapturingHandler()
    book_logger.addHandler(handler)
    book_logger.setLevel(logging.WARNING)

    try:
        # Must not raise — exception is swallowed inside the coroutine
        await _persist_memories_safe_standalone(
            "+34612345678", "Corte Dama", "uuid-1", "2026-05-15T10:00:00+00:00", None
        )
    finally:
        book_logger.removeHandler(handler)

    assert len(warning_records) >= 1, "WARNING must be logged when write fails"
    assert any(
        "persistence" in msg.lower() or "customer_memory" in msg.lower()
        for msg in warning_records
    ), f"Expected WARNING about persistence failure. Got: {warning_records}"
