"""Unit tests for the pure assertion helpers in assert_notifications.py.

No DB, no Redis, no network.  All tests operate on fabricated capture dicts so
they pass in any environment that has pytest installed.
"""

from __future__ import annotations

import pytest

from tests.e2e.harness.assert_notifications import (
    assert_idempotent,
    assert_no_failures,
    assert_send_attempt,
    assert_timestamp_stamped,
    find_db_state,
    find_send_attempts,
)

# ---------------------------------------------------------------------------
# Fixtures — fabricated capture dicts
# ---------------------------------------------------------------------------

APPT_ID = "11111111-1111-1111-1111-111111111111"
OTHER_ID = "22222222-2222-2222-2222-222222222222"

_ATTEMPT_REMINDER = {
    "handler": "reminder_24h",
    "appointment_id": APPT_ID,
    "customer_phone": "+34999000001",
    "template_name": "test_reminder_24h",
    "body_params": {"1": "Ana", "2": "2026-07-01", "3": "10:00"},
    "category": "UTILITY",
    "language": "es",
    "success": True,
}

_ATTEMPT_CONFIRM = {
    "handler": "confirm_48h",
    "appointment_id": APPT_ID,
    "customer_phone": "+34999000001",
    "template_name": "test_confirm_48h",
    "body_params": {"1": "Ana", "2": "2026-07-02", "3": "10:00"},
    "category": "UTILITY",
    "language": "es",
    "success": True,
}

_DB_STATE_REMINDER_STAMPED = {
    "appointment_id": APPT_ID,
    "reminder_sent_at": "2026-06-30T10:00:01+00:00",
    "confirmation_sent_at": None,
    "reminder_failed": False,
    "notification_failed": False,
    "status": "confirmed",
}

_DB_STATE_CONFIRM_STAMPED = {
    "appointment_id": APPT_ID,
    "reminder_sent_at": None,
    "confirmation_sent_at": "2026-06-30T10:00:01+00:00",
    "reminder_failed": False,
    "notification_failed": False,
    "status": "pending",
}


def _capture(
    attempts: list[dict],
    db_state: list[dict] | None = None,
) -> dict:
    return {
        "run_at": "2026-06-30T10:00:00+00:00",
        "handlers_fired": ["reminder_24h", "confirm_48h"],
        "send_attempts": attempts,
        "db_state": db_state or [],
    }


# ---------------------------------------------------------------------------
# find_send_attempts
# ---------------------------------------------------------------------------


def test_find_by_appointment_and_handler_match():
    cap = _capture([_ATTEMPT_REMINDER])
    result = find_send_attempts(cap, appointment_id=APPT_ID, handler="reminder_24h")
    assert len(result) == 1
    assert result[0]["template_name"] == "test_reminder_24h"


def test_find_wrong_handler_returns_empty():
    cap = _capture([_ATTEMPT_REMINDER])
    result = find_send_attempts(cap, appointment_id=APPT_ID, handler="confirm_48h")
    assert result == []


def test_find_wrong_appointment_id_returns_empty():
    cap = _capture([_ATTEMPT_REMINDER])
    result = find_send_attempts(cap, appointment_id=OTHER_ID, handler="reminder_24h")
    assert result == []


def test_find_no_filter_returns_all():
    cap = _capture([_ATTEMPT_REMINDER, _ATTEMPT_CONFIRM])
    result = find_send_attempts(cap)
    assert len(result) == 2


def test_find_empty_capture_returns_empty():
    cap = _capture([])
    result = find_send_attempts(cap, appointment_id=APPT_ID)
    assert result == []


# ---------------------------------------------------------------------------
# find_db_state
# ---------------------------------------------------------------------------


def test_find_db_state_found():
    cap = _capture([], db_state=[_DB_STATE_REMINDER_STAMPED])
    row = find_db_state(cap, APPT_ID)
    assert row is not None
    assert row["reminder_sent_at"] is not None


def test_find_db_state_not_found():
    cap = _capture([], db_state=[_DB_STATE_REMINDER_STAMPED])
    row = find_db_state(cap, OTHER_ID)
    assert row is None


# ---------------------------------------------------------------------------
# assert_send_attempt
# ---------------------------------------------------------------------------


def test_assert_send_attempt_positive():
    cap = _capture([_ATTEMPT_REMINDER])
    matched = assert_send_attempt(cap, appointment_id=APPT_ID, handler="reminder_24h")
    assert matched["template_name"] == "test_reminder_24h"


def test_assert_send_attempt_missing_raises():
    cap = _capture([])
    with pytest.raises(AssertionError, match="Expected a send attempt"):
        assert_send_attempt(cap, appointment_id=APPT_ID, handler="reminder_24h")


def test_assert_send_attempt_duplicate_raises():
    cap = _capture([_ATTEMPT_REMINDER, _ATTEMPT_REMINDER])
    with pytest.raises(AssertionError, match="exactly 1"):
        assert_send_attempt(cap, appointment_id=APPT_ID, handler="reminder_24h")


# ---------------------------------------------------------------------------
# assert_timestamp_stamped
# ---------------------------------------------------------------------------


def test_assert_timestamp_stamped_reminder_pass():
    cap = _capture([_ATTEMPT_REMINDER], db_state=[_DB_STATE_REMINDER_STAMPED])
    assert_timestamp_stamped(cap, appointment_id=APPT_ID, handler="reminder_24h")


def test_assert_timestamp_stamped_confirm_pass():
    cap = _capture([_ATTEMPT_CONFIRM], db_state=[_DB_STATE_CONFIRM_STAMPED])
    assert_timestamp_stamped(cap, appointment_id=APPT_ID, handler="confirm_48h")


def test_assert_timestamp_stamped_null_raises():
    unstamped = {**_DB_STATE_REMINDER_STAMPED, "reminder_sent_at": None}
    cap = _capture([_ATTEMPT_REMINDER], db_state=[unstamped])
    with pytest.raises(AssertionError, match="reminder_sent_at"):
        assert_timestamp_stamped(cap, appointment_id=APPT_ID, handler="reminder_24h")


def test_assert_timestamp_stamped_missing_db_state_raises():
    cap = _capture([_ATTEMPT_REMINDER], db_state=[])
    with pytest.raises(AssertionError, match="No DB state entry"):
        assert_timestamp_stamped(cap, appointment_id=APPT_ID, handler="reminder_24h")


def test_assert_timestamp_stamped_unknown_handler_raises():
    cap = _capture([], db_state=[_DB_STATE_REMINDER_STAMPED])
    with pytest.raises(ValueError, match="Unknown handler"):
        assert_timestamp_stamped(cap, appointment_id=APPT_ID, handler="bogus_handler")


# ---------------------------------------------------------------------------
# assert_no_failures
# ---------------------------------------------------------------------------


def test_assert_no_failures_pass():
    cap = _capture([], db_state=[_DB_STATE_REMINDER_STAMPED])
    assert_no_failures(cap, appointment_id=APPT_ID)


def test_assert_no_failures_reminder_failed_raises():
    broken = {**_DB_STATE_REMINDER_STAMPED, "reminder_failed": True}
    cap = _capture([], db_state=[broken])
    with pytest.raises(AssertionError, match="reminder_failed"):
        assert_no_failures(cap, appointment_id=APPT_ID)


def test_assert_no_failures_notification_failed_raises():
    broken = {**_DB_STATE_REMINDER_STAMPED, "notification_failed": True}
    cap = _capture([], db_state=[broken])
    with pytest.raises(AssertionError, match="notification_failed"):
        assert_no_failures(cap, appointment_id=APPT_ID)


def test_assert_no_failures_missing_db_state_raises():
    cap = _capture([], db_state=[])
    with pytest.raises(AssertionError, match="No DB state entry"):
        assert_no_failures(cap, appointment_id=APPT_ID)


# ---------------------------------------------------------------------------
# assert_idempotent
# ---------------------------------------------------------------------------


def test_assert_idempotent_pass():
    """Second fire has no send attempts → idempotency confirmed."""
    first = _capture([_ATTEMPT_REMINDER])
    second = _capture([])
    assert_idempotent(first, second, APPT_ID)


def test_assert_idempotent_violation_raises():
    """Second fire still sent → violation."""
    first = _capture([_ATTEMPT_REMINDER])
    second = _capture([_ATTEMPT_REMINDER])
    with pytest.raises(AssertionError, match="Idempotency violation"):
        assert_idempotent(first, second, APPT_ID)


def test_assert_idempotent_vacuous_first_raises():
    """First capture has no sends → guard raises to prevent false pass."""
    first = _capture([])
    second = _capture([])
    with pytest.raises(AssertionError, match="first capture has no send attempts"):
        assert_idempotent(first, second, APPT_ID)


def test_assert_idempotent_other_appointment_does_not_interfere():
    """Second fire may send for OTHER_ID but not for APPT_ID → still passes."""
    first = _capture([_ATTEMPT_REMINDER])
    second_other = {**_ATTEMPT_REMINDER, "appointment_id": OTHER_ID}
    second = _capture([second_other])
    assert_idempotent(first, second, APPT_ID)
