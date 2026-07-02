"""Unit tests for Appointment.final_warning_sent_at column (T3 — RED before T4 adds it).

Verifies the ORM attribute exists on the Appointment model, defaults to None,
and that no new AppointmentStatus enum value was added (spec S3-R3, S3-R4, D-R7).

RED contract: attribute-existence assertions fail BEFORE T4 adds the column.
GREEN contract: all assertions pass AFTER T4 is applied.
"""

from __future__ import annotations

from datetime import UTC, datetime

from database.models import Appointment, AppointmentStatus

# ---------------------------------------------------------------------------
# T3-A: final_warning_sent_at attribute exists and defaults to None
# ---------------------------------------------------------------------------


def test_final_warning_sent_at_attribute_exists() -> None:
    """Appointment must have final_warning_sent_at attribute (S3-R3).

    This assertion fails (AttributeError or missing attr) before T4 adds
    the column to database/models.py.
    """
    appt = Appointment()
    assert hasattr(appt, "final_warning_sent_at"), (
        "Appointment must have final_warning_sent_at attribute "
        "(missing — add it to database/models.py in T4)"
    )


def test_final_warning_sent_at_defaults_none() -> None:
    """Appointment.final_warning_sent_at must default to None (nullable, S3-R3)."""
    appt = Appointment()
    assert appt.final_warning_sent_at is None, (
        f"final_warning_sent_at must default to None, got {appt.final_warning_sent_at!r}"
    )


def test_final_warning_sent_at_accepts_datetime() -> None:
    """Appointment.final_warning_sent_at must accept a timezone-aware datetime."""
    now = datetime.now(UTC)
    appt = Appointment()
    appt.final_warning_sent_at = now
    assert appt.final_warning_sent_at == now


def test_final_warning_sent_at_accepts_none_after_set() -> None:
    """Appointment.final_warning_sent_at must be resettable to None."""
    appt = Appointment()
    appt.final_warning_sent_at = datetime.now(UTC)
    appt.final_warning_sent_at = None
    assert appt.final_warning_sent_at is None


# ---------------------------------------------------------------------------
# T3-B: No new AppointmentStatus enum value (spec S3-R4, design D-R7)
# ---------------------------------------------------------------------------


def test_appointment_status_has_no_auto_cancelled_value() -> None:
    """AppointmentStatus must NOT contain AUTO_CANCELLED or auto_cancelled (S3-R4, D-R7).

    Auto-cancel reuses CANCELLED + cancellation_reason='auto_cancelled_no_confirmation'.
    Adding a new enum value would require a non-transactional ALTER TYPE in Postgres
    and would require editing the GiST EXCLUDE constraint. Spec explicitly forbids it.
    """
    status_values = {e.value for e in AppointmentStatus}
    status_names = {e.name for e in AppointmentStatus}

    assert "auto_cancelled" not in status_values, (
        "AppointmentStatus must NOT have value 'auto_cancelled' — use CANCELLED + reason"
    )
    assert "AUTO_CANCELLED" not in status_names, (
        "AppointmentStatus must NOT have member AUTO_CANCELLED — use CANCELLED + reason"
    )


def test_appointment_status_existing_values_unchanged() -> None:
    """AppointmentStatus must still contain all pre-existing values (regression guard)."""
    expected = {"hold", "pending", "confirmed", "completed", "cancelled", "no_show"}
    actual = {e.value for e in AppointmentStatus}
    assert expected.issubset(actual), (
        f"AppointmentStatus is missing expected values: {expected - actual}"
    )


# ---------------------------------------------------------------------------
# T3-C: final_warning_sent_at column position relative to confirmation_sent_at
# ---------------------------------------------------------------------------


def test_final_warning_sent_at_is_independent_from_confirmation_sent_at() -> None:
    """Both timestamp columns must be independently settable (no aliasing)."""
    appt = Appointment()
    now = datetime.now(UTC)

    appt.confirmation_sent_at = now
    # final_warning_sent_at is still None (independent column)
    assert appt.final_warning_sent_at is None

    appt.final_warning_sent_at = now
    assert appt.final_warning_sent_at == now
    assert appt.confirmation_sent_at == now  # unchanged
