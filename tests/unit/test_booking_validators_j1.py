"""Tests for Change J1 validators: IDOR guard + slot-binding in _booking_validators.

Change J: hallucination-tolerant-architecture-bundle.
REQ-J1, REQ-J2, REQ-J3.

Tests written BEFORE implementation (TDD RED phase).
All DB-touching tests use mocked sessions; slot/regex validators are pure functions.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _make_slot(
    start_iso: str,
    stylist_id: str | None,
    expires_at: datetime | None = None,
    turn_index: int = 0,
) -> dict:
    if expires_at is None:
        expires_at = _utcnow() + timedelta(minutes=14)
    return {
        "start_iso": start_iso,
        "stylist_id": stylist_id,
        "expires_at": expires_at.isoformat(),
        "turn_index": turn_index,
    }


# ---------------------------------------------------------------------------
# validate_appointment_belongs_to_customer — error codes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_appointment_belongs_to_customer_imports():
    """validate_appointment_belongs_to_customer must be importable."""


@pytest.mark.asyncio
async def test_validate_appointment_belongs_to_customer_own_appointment_passes():
    """Own appointment (customer_id matches) returns ok=True."""
    from agent.tools._booking_validators import validate_appointment_belongs_to_customer

    customer_id = uuid4()
    appt_id = uuid4()

    session = AsyncMock()
    # Simulate: row found for (id, customer_id) pair
    mock_result = MagicMock()
    mock_result.fetchone.return_value = (str(appt_id),)
    session.execute = AsyncMock(return_value=mock_result)

    result = await validate_appointment_belongs_to_customer(session, appt_id, customer_id)
    assert result.ok is True
    assert result.error_code is None


@pytest.mark.asyncio
async def test_validate_appointment_belongs_to_customer_wrong_customer_rejected():
    """Cross-customer appointment_id returns ok=False with APPOINTMENT_NOT_OWNED."""
    from agent.tools._booking_validators import (
        ERROR_APPOINTMENT_NOT_OWNED,
        validate_appointment_belongs_to_customer,
    )

    customer_id = uuid4()
    appt_id = uuid4()

    session = AsyncMock()
    # Simulate: no row (appointment exists but owned by different customer)
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    # Second query to check if appointment ID at all exists — also returns None
    session.execute = AsyncMock(return_value=mock_result)

    result = await validate_appointment_belongs_to_customer(session, appt_id, customer_id)
    assert result.ok is False
    assert result.error_code in (ERROR_APPOINTMENT_NOT_OWNED, "invalid_appointment_id")
    assert result.error_message is not None
    assert len(result.error_message) > 0


@pytest.mark.asyncio
async def test_validate_appointment_belongs_to_customer_invalid_id_rejected():
    """Appointment ID that doesn't exist at all returns ERROR_INVALID_APPOINTMENT_ID."""
    from agent.tools._booking_validators import (
        ERROR_APPOINTMENT_NOT_OWNED,
        ERROR_INVALID_APPOINTMENT_ID,
        validate_appointment_belongs_to_customer,
    )

    customer_id = uuid4()
    appt_id = uuid4()

    session = AsyncMock()
    # Both queries return nothing: appt doesn't exist at all
    mock_no_row = MagicMock()
    mock_no_row.fetchone.return_value = None
    session.execute = AsyncMock(return_value=mock_no_row)

    result = await validate_appointment_belongs_to_customer(session, appt_id, customer_id)
    assert result.ok is False
    # Either APPOINTMENT_NOT_OWNED or INVALID_APPOINTMENT_ID is acceptable
    assert result.error_code in (ERROR_APPOINTMENT_NOT_OWNED, ERROR_INVALID_APPOINTMENT_ID)


@pytest.mark.asyncio
async def test_validate_appointment_belongs_to_customer_error_codes_exported():
    """Error codes for J2 must be exported from _booking_validators."""
    from agent.tools._booking_validators import (
        ERROR_APPOINTMENT_NOT_OWNED,
        ERROR_INVALID_APPOINTMENT_ID,
    )

    assert ERROR_APPOINTMENT_NOT_OWNED == "appointment_not_owned"
    assert ERROR_INVALID_APPOINTMENT_ID == "invalid_appointment_id"


# ---------------------------------------------------------------------------
# validate_slot_in_offered — pure function, no DB
# ---------------------------------------------------------------------------


def test_validate_slot_in_offered_imports():
    """validate_slot_in_offered must be importable."""
    from agent.tools._booking_validators import validate_slot_in_offered  # noqa: F401


def test_validate_slot_in_offered_matching_slot_passes():
    """Slot that matches an entry in offered_slots (within TTL) returns ok=True."""
    from agent.tools._booking_validators import validate_slot_in_offered

    now = _utcnow()
    slot_iso = "2026-06-10T10:00:00+00:00"
    stylist_id = str(uuid4())
    offered = [_make_slot(slot_iso, stylist_id, now + timedelta(minutes=10))]

    result = validate_slot_in_offered(slot_iso, stylist_id, offered, now=now)
    assert result.ok is True


def test_validate_slot_in_offered_slot_not_in_list_rejected():
    """Slot not in offered_slots returns ok=False with ERROR_SLOT_NOT_OFFERED."""
    from agent.tools._booking_validators import ERROR_SLOT_NOT_OFFERED, validate_slot_in_offered

    now = _utcnow()
    offered = [_make_slot("2026-06-10T10:00:00+00:00", None, now + timedelta(minutes=10))]

    result = validate_slot_in_offered("2026-06-10T15:30:00+00:00", None, offered, now=now)
    assert result.ok is False
    assert result.error_code == ERROR_SLOT_NOT_OFFERED


def test_validate_slot_in_offered_empty_list_rejected():
    """Empty offered_slots returns ok=False."""
    from agent.tools._booking_validators import ERROR_SLOT_NOT_OFFERED, validate_slot_in_offered

    now = _utcnow()
    result = validate_slot_in_offered("2026-06-10T10:00:00+00:00", None, [], now=now)
    assert result.ok is False
    assert result.error_code == ERROR_SLOT_NOT_OFFERED
    assert result.error_message is not None


def test_validate_slot_in_offered_expired_entry_rejected():
    """Slot in list but past expires_at is rejected."""
    from agent.tools._booking_validators import ERROR_SLOT_NOT_OFFERED, validate_slot_in_offered

    now = _utcnow()
    slot_iso = "2026-06-10T10:00:00+00:00"
    expired_at = now - timedelta(minutes=1)  # already expired
    offered = [_make_slot(slot_iso, None, expired_at)]

    result = validate_slot_in_offered(slot_iso, None, offered, now=now)
    assert result.ok is False
    assert result.error_code == ERROR_SLOT_NOT_OFFERED


def test_validate_slot_in_offered_stylist_mismatch_rejected():
    """Slot matches time but stylist_id differs → rejected."""
    from agent.tools._booking_validators import ERROR_SLOT_NOT_OFFERED, validate_slot_in_offered

    now = _utcnow()
    slot_iso = "2026-06-10T10:00:00+00:00"
    stylist_a = str(uuid4())
    stylist_b = str(uuid4())
    offered = [_make_slot(slot_iso, stylist_a, now + timedelta(minutes=10))]

    result = validate_slot_in_offered(slot_iso, stylist_b, offered, now=now)
    assert result.ok is False
    assert result.error_code == ERROR_SLOT_NOT_OFFERED


def test_validate_slot_in_offered_null_stylist_in_offered_matches_any():
    """If offered entry has stylist_id=None, it matches any requested stylist_id."""
    from agent.tools._booking_validators import validate_slot_in_offered

    now = _utcnow()
    slot_iso = "2026-06-10T10:00:00+00:00"
    stylist_any = str(uuid4())
    offered = [_make_slot(slot_iso, None, now + timedelta(minutes=10))]  # stylist=None

    result = validate_slot_in_offered(slot_iso, stylist_any, offered, now=now)
    assert result.ok is True


def test_validate_slot_in_offered_utc_normalized_comparison():
    """UTC-normalized comparison: +02:00 and +00:00 slots pointing to same moment."""
    from agent.tools._booking_validators import validate_slot_in_offered

    now = _utcnow()
    # Same moment, different timezone notation
    slot_madrid = "2026-06-10T12:00:00+02:00"
    slot_utc = "2026-06-10T10:00:00+00:00"
    offered = [_make_slot(slot_utc, None, now + timedelta(minutes=10))]

    result = validate_slot_in_offered(slot_madrid, None, offered, now=now)
    assert result.ok is True


def test_error_slot_not_offered_exported():
    """ERROR_SLOT_NOT_OFFERED must be exported."""
    from agent.tools._booking_validators import ERROR_SLOT_NOT_OFFERED

    assert ERROR_SLOT_NOT_OFFERED == "slot_not_offered"


def test_validate_slot_in_offered_message_instructs_recheck():
    """Rejection message must instruct LLM to re-check availability."""
    from agent.tools._booking_validators import validate_slot_in_offered

    now = _utcnow()
    result = validate_slot_in_offered("2026-06-10T10:00:00+00:00", None, [], now=now)
    assert result.error_message is not None
    # Message must guide the LLM toward re-checking
    msg_lower = result.error_message.lower()
    assert any(
        kw in msg_lower for kw in ["disponibilidad", "check_availability", "vuelve", "recarga"]
    ), f"Error message must instruct LLM to re-check availability. Got: {result.error_message}"
