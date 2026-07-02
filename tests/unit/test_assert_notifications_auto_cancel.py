"""Unit tests for assert_auto_cancelled pure helper.

All tests use fabricated dicts — no DB, Redis, or network required.
"""

from __future__ import annotations

import pytest

from tests.e2e.harness.assert_notifications import assert_auto_cancelled

_APPT_ID = "aaaaaaaa-0000-0000-0000-000000000001"
_OTHER_ID = "bbbbbbbb-0000-0000-0000-000000000002"


def _make_capture(
    appointment_id: str = _APPT_ID,
    status: str = "cancelled",
    cancellation_reason: str = "auto_cancelled_no_confirmation",
    cancelled_at: str | None = "2026-07-01T12:00:00+00:00",
) -> dict:
    return {
        "run_at": "2026-07-01T12:00:00+00:00",
        "handlers_fired": ["auto_cancel"],
        "send_attempts": [
            {
                "handler": "auto_cancel",
                "appointment_id": appointment_id,
                "customer_phone": None,
                "template_name": None,
                "body_params": None,
                "category": None,
                "language": None,
                "success": True,
            }
        ],
        "db_state": [
            {
                "appointment_id": appointment_id,
                "status": status,
                "cancellation_reason": cancellation_reason,
                "cancelled_at": cancelled_at,
                "final_warning_sent_at": "2026-07-01T06:00:00+00:00",
                "reminder_failed": False,
                "notification_failed": False,
            }
        ],
    }


def test_passes_on_valid_auto_cancel_state():
    capture = _make_capture()
    assert_auto_cancelled(capture, _APPT_ID)  # must not raise


def test_fails_when_status_is_not_cancelled():
    capture = _make_capture(status="pending")
    with pytest.raises(AssertionError, match="status='cancelled'"):
        assert_auto_cancelled(capture, _APPT_ID)


def test_fails_when_status_is_confirmed():
    capture = _make_capture(status="confirmed", cancellation_reason="")
    with pytest.raises(AssertionError, match="status='cancelled'"):
        assert_auto_cancelled(capture, _APPT_ID)


def test_fails_when_cancellation_reason_is_operator_cancelled():
    capture = _make_capture(cancellation_reason="operator_cancelled")
    with pytest.raises(AssertionError, match="auto_cancelled_no_confirmation"):
        assert_auto_cancelled(capture, _APPT_ID)


def test_fails_when_cancellation_reason_is_customer_declined():
    capture = _make_capture(cancellation_reason="customer_declined")
    with pytest.raises(AssertionError, match="auto_cancelled_no_confirmation"):
        assert_auto_cancelled(capture, _APPT_ID)


def test_fails_when_cancelled_at_is_none():
    capture = _make_capture(cancelled_at=None)
    with pytest.raises(AssertionError, match="cancelled_at"):
        assert_auto_cancelled(capture, _APPT_ID)


def test_fails_when_no_db_state_entry_for_appointment():
    capture = _make_capture()
    with pytest.raises(AssertionError, match="No DB state entry"):
        assert_auto_cancelled(capture, _OTHER_ID)


def test_fails_when_db_state_is_empty():
    capture = _make_capture()
    capture["db_state"] = []
    with pytest.raises(AssertionError, match="No DB state entry"):
        assert_auto_cancelled(capture, _APPT_ID)
