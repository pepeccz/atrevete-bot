"""Unit tests for pre_book_validated guard in agent.tools.book.

R2.3: book() MUST refuse with status='rejected' + next_step='pre_book_validation_required'
when pre_book_validated=False, and MUST NOT write any DB row.

B3 extension: even with pre_book_validated=True, book() must always call
check_slot_availability and reject if the slot is no longer available.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.tools.book import book

STATE_WITH_PHONE = {"customer_phone": "+5491112345678"}


@pytest.mark.asyncio
async def test_book_rejected_when_pre_book_validated_false() -> None:
    """book(pre_book_validated=False) returns rejected with pre_book_validation_required."""
    result = await book.coroutine(
        service_ids=["00000000-0000-0000-0000-000000000001"],
        stylist_id="00000000-0000-0000-0000-000000000002",
        start_iso="2026-05-10T10:00:00+00:00",
        customer_full_name="Ana García",
        confirmed=True,
        pre_book_validated=False,
        state=STATE_WITH_PHONE,
    )
    payload = json.loads(result)
    assert payload["status"] == "rejected"
    assert payload["next_step"] == "pre_book_validation_required"


@pytest.mark.asyncio
async def test_book_rejected_pre_book_validated_false_no_db_write() -> None:
    """book(pre_book_validated=False) must NOT touch the DB."""
    with patch("database.connection.get_async_session") as mock_session:
        result = await book.coroutine(
            service_ids=["00000000-0000-0000-0000-000000000001"],
            stylist_id="00000000-0000-0000-0000-000000000002",
            start_iso="2026-05-10T10:00:00+00:00",
            customer_full_name="Ana García",
            confirmed=True,
            pre_book_validated=False,
            state=STATE_WITH_PHONE,
        )
    mock_session.assert_not_called()
    payload = json.loads(result)
    assert payload["status"] == "rejected"


@pytest.mark.asyncio
async def test_book_proceeds_when_pre_book_validated_true() -> None:
    """book(pre_book_validated=True, confirmed=True) passes the gate and hits DB logic."""
    # We only test that the gate is NOT triggered — DB errors expected (no real DB).
    result = await book.coroutine(
        service_ids=["00000000-0000-0000-0000-000000000001"],
        stylist_id="00000000-0000-0000-0000-000000000002",
        start_iso="2026-05-10T10:00:00+00:00",
        customer_full_name="Ana García",
        confirmed=True,
        pre_book_validated=True,
        state=STATE_WITH_PHONE,
    )
    payload = json.loads(result)
    # Gate passed — will fail at DB but NOT with pre_book_validation_required
    assert payload.get("next_step") != "pre_book_validation_required"


@pytest.mark.asyncio
async def test_book_pre_book_validated_default_is_false() -> None:
    """Omitting pre_book_validated defaults to False → rejected."""
    result = await book.coroutine(
        service_ids=["00000000-0000-0000-0000-000000000001"],
        stylist_id="00000000-0000-0000-0000-000000000002",
        start_iso="2026-05-10T10:00:00+00:00",
        customer_full_name="Ana García",
        confirmed=True,
        # pre_book_validated omitted → should default False → rejected
        state=STATE_WITH_PHONE,
    )
    payload = json.loads(result)
    assert payload["status"] == "rejected"
    assert payload["next_step"] == "pre_book_validation_required"


# ---------------------------------------------------------------------------
# B3 — T10: unconditional server-side recheck even when pre_book_validated=True
# ---------------------------------------------------------------------------

SERVICE_ID_T10 = "00000000-0000-0000-0000-000000000001"
STYLIST_ID_T10 = "00000000-0000-0000-0000-000000000002"
START_ISO_T10 = "2026-05-10T10:00:00+02:00"
STATE_T10 = {"customer_phone": "+34611000050"}


def _make_session_ctx_t10(duration=30):
    """Minimal DB session mock for T10 tests."""
    session = AsyncMock()
    dur_result = MagicMock()
    dur_result.fetchall.return_value = [(duration,)]
    session.execute = AsyncMock(return_value=dur_result)
    session.add = MagicMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@pytest.mark.asyncio
async def test_book_rechecks_availability_despite_pre_book_validated():
    """B3: Even when pre_book_validated=True, book() must re-check slot availability.

    If the slot is no longer available, book must return rejected + reoffer_slots.
    """
    ctx = _make_session_ctx_t10()

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch(
            "agent.tools.book.check_slot_availability",
            new=AsyncMock(return_value={"available": False}),
        ),
    ):
        result = await book.coroutine(
            service_ids=[SERVICE_ID_T10],
            stylist_id=STYLIST_ID_T10,
            start_iso=START_ISO_T10,
            customer_full_name="Ana García",
            confirmed=True,
            pre_book_validated=True,
            state=STATE_T10,
        )

    payload = json.loads(result)
    assert payload["status"] == "rejected", (
        f"Expected rejected when slot no longer available, got: {payload}"
    )
    assert payload.get("next_step") == "reoffer_slots", (
        f"Expected next_step=reoffer_slots, got: {payload}"
    )


@pytest.mark.asyncio
async def test_book_proceeds_when_recheck_passes():
    """B3: When availability recheck passes (available=True), booking proceeds normally."""
    ctx = _make_session_ctx_t10()

    with (
        patch("database.connection.get_async_session", return_value=ctx),
        patch(
            "agent.tools.book.check_slot_availability",
            new=AsyncMock(return_value={"available": True}),
        ),
    ):
        result = await book.coroutine(
            service_ids=[SERVICE_ID_T10],
            stylist_id=STYLIST_ID_T10,
            start_iso=START_ISO_T10,
            customer_full_name="Ana García",
            confirmed=True,
            pre_book_validated=True,
            state=STATE_T10,
        )

    payload = json.loads(result)
    # Should NOT be rejected with reoffer_slots — recheck passed
    assert payload.get("next_step") != "reoffer_slots", (
        f"Expected recheck to pass, but got reoffer_slots: {payload}"
    )
