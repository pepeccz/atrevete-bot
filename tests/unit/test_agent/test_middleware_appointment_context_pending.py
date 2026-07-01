"""
T5 VERIFY — AppointmentContextMiddleware handles PENDING appointments without errors.

These tests assert that the middleware already renders PENDING appointments correctly
(status label "PENDIENTE", query includes PENDING, block renders without exception).

Expected result: all 3 tests GREEN with ZERO code changes to the middleware.
This is a regression-prevention test, not a new-behavior test (CC-R2).

Spec ref: CC-R2, design R5
"""
from __future__ import annotations

import inspect
from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ---------------------------------------------------------------------------
# T5.1 — _format_lifecycle_line returns "PENDIENTE" for PENDING appointments
# ---------------------------------------------------------------------------


def test_format_lifecycle_line_returns_pendiente_for_pending_status():
    """_format_lifecycle_line must label a PENDING appointment as 'PENDIENTE'.

    Confirms appointment_context.py line ~79: AppointmentStatus.PENDING: "PENDIENTE".
    Expected GREEN before and after T2 (middleware already handles PENDING).
    """
    from agent.middleware.appointment_context import _format_lifecycle_line  # noqa: PLC0415
    from database.models import AppointmentStatus  # noqa: PLC0415

    mock_appt = MagicMock()
    mock_appt.status = AppointmentStatus.PENDING
    mock_appt.confirmation_sent_at = None
    mock_appt.reminder_sent_at = None

    now = datetime.now(UTC)
    result = _format_lifecycle_line(mock_appt, now)

    assert "PENDIENTE" in result, (
        f"Expected 'PENDIENTE' in lifecycle line for PENDING appointment, got: {result!r}"
    )


# ---------------------------------------------------------------------------
# T5.2 — _fetch_upcoming_appointments query includes PENDING status
# ---------------------------------------------------------------------------


def test_fetch_query_includes_pending_status():
    """_fetch_upcoming_appointments must filter on PENDING (and CONFIRMED) appointments.

    Verifies appointment_context.py lines ~148-149 include AppointmentStatus.PENDING
    in the .in_([...]) filter. Inspects source to confirm the constant is present.
    Expected GREEN: middleware already queries PENDING status.
    """
    from agent.middleware import appointment_context  # noqa: PLC0415

    source = inspect.getsource(appointment_context._fetch_upcoming_appointments)
    assert "AppointmentStatus.PENDING" in source, (
        "_fetch_upcoming_appointments must include AppointmentStatus.PENDING in its "
        "status filter so upcoming PENDING appointments appear in context"
    )


# ---------------------------------------------------------------------------
# T5.3 — _format_block renders a PENDING appointment without raising
# ---------------------------------------------------------------------------


def test_format_block_renders_pending_appointment_without_exception():
    """_format_block must render a PENDING appointment and include status in the XML block.

    Expected GREEN: the block renderer delegates to _format_lifecycle_line which
    already handles PENDING (CC-R2 — AppointmentContextMiddleware handles PENDING).
    """
    from agent.middleware.appointment_context import _format_block  # noqa: PLC0415
    from database.models import AppointmentStatus  # noqa: PLC0415

    mock_appt = MagicMock()
    mock_appt.id = uuid4()
    mock_appt.status = AppointmentStatus.PENDING
    mock_appt.start_time = datetime(2026, 8, 1, 10, 0, 0, tzinfo=MADRID_TZ)
    mock_appt.stylist = MagicMock()
    mock_appt.stylist.name = "María"
    mock_appt._injected_service_names = "Corte de Mujer"
    mock_appt.confirmation_sent_at = None
    mock_appt.reminder_sent_at = None

    result = _format_block([mock_appt])

    assert "<upcoming_appointments>" in result, "Block must be wrapped in <upcoming_appointments>"
    assert "PENDIENTE" in result, (
        "Block must include 'PENDIENTE' label for a PENDING appointment status"
    )
    assert "Corte de Mujer" in result, "Block must include the injected service name"
