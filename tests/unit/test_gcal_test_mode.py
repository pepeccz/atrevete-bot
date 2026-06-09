"""Unit tests for GCal push service TEST_MODE_GCAL_SKIP bypass (AS1, AS1b, AS2).

Covers:
- All 5 push functions early-return when TEST_MODE_GCAL_SKIP=True
- No Google API calls are made (mock confirms zero invocations)
- _write_gcal_status is called with 'not_applicable' for appointment-scoped functions
- push_blocking_event_to_gcal and the no-appointment-id path of delete_gcal_event
  only log and return without writing status
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_uuid() -> uuid.UUID:
    return uuid.uuid4()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# push_appointment_to_gcal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_appointment_gcal_skip_returns_none() -> None:
    """AS1: push_appointment_to_gcal returns None when TEST_MODE_GCAL_SKIP=True."""
    with (
        patch("agent.services.gcal_push_service.get_settings") as mock_settings,
        patch("agent.services.gcal_push_service._write_gcal_status", new_callable=AsyncMock) as mock_write,
        patch("agent.services.gcal_push_service._get_calendar_service") as mock_gcal,
    ):
        mock_settings.return_value = MagicMock(TEST_MODE_GCAL_SKIP=True)

        from agent.services.gcal_push_service import push_appointment_to_gcal

        result = await push_appointment_to_gcal(
            appointment_id=_make_uuid(),
            stylist_id=_make_uuid(),
            customer_name="Test User",
            service_names="Corte",
            start_time=_utcnow(),
            duration_minutes=30,
        )

    assert result is None
    mock_gcal.assert_not_called()
    mock_write.assert_called_once()
    args = mock_write.call_args.args
    # signature: (appointment_id, status, operation, error)
    assert args[1] == "not_applicable"
    assert args[2] == "push_appointment"


# ---------------------------------------------------------------------------
# push_blocking_event_to_gcal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_blocking_event_gcal_skip_returns_none() -> None:
    """AS1b: push_blocking_event_to_gcal returns None when TEST_MODE_GCAL_SKIP=True (log only, no status write)."""
    with (
        patch("agent.services.gcal_push_service.get_settings") as mock_settings,
        patch("agent.services.gcal_push_service._write_gcal_status", new_callable=AsyncMock) as mock_write,
        patch("agent.services.gcal_push_service._get_calendar_service") as mock_gcal,
    ):
        mock_settings.return_value = MagicMock(TEST_MODE_GCAL_SKIP=True)

        from agent.services.gcal_push_service import push_blocking_event_to_gcal

        result = await push_blocking_event_to_gcal(
            blocking_event_id=_make_uuid(),
            stylist_id=_make_uuid(),
            title="Block",
            description=None,
            start_time=_utcnow(),
            end_time=_utcnow(),
        )

    assert result is None
    mock_gcal.assert_not_called()
    mock_write.assert_not_called()


# ---------------------------------------------------------------------------
# update_appointment_in_gcal
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_appointment_gcal_skip_returns_none() -> None:
    """AS1: update_appointment_in_gcal returns None when TEST_MODE_GCAL_SKIP=True."""
    with (
        patch("agent.services.gcal_push_service.get_settings") as mock_settings,
        patch("agent.services.gcal_push_service._write_gcal_status", new_callable=AsyncMock) as mock_write,
        patch("agent.services.gcal_push_service._get_calendar_service") as mock_gcal,
    ):
        mock_settings.return_value = MagicMock(TEST_MODE_GCAL_SKIP=True)

        from agent.services.gcal_push_service import update_appointment_in_gcal

        result = await update_appointment_in_gcal(
            appointment_id=_make_uuid(),
            stylist_id=_make_uuid(),
            event_id="fake_event_id",
            customer_name="Test User",
            service_names="Corte",
            start_time=_utcnow(),
            duration_minutes=30,
        )

    assert result is None
    mock_gcal.assert_not_called()
    mock_write.assert_called_once()
    args = mock_write.call_args.args
    assert args[1] == "not_applicable"
    assert args[2] == "update_appointment"


# ---------------------------------------------------------------------------
# update_gcal_event_status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_gcal_event_status_skip_returns_none() -> None:
    """AS1: update_gcal_event_status returns None when TEST_MODE_GCAL_SKIP=True (log only — no appointment_id)."""
    with (
        patch("agent.services.gcal_push_service.get_settings") as mock_settings,
        patch("agent.services.gcal_push_service._write_gcal_status", new_callable=AsyncMock) as mock_write,
        patch("agent.services.gcal_push_service._get_calendar_service") as mock_gcal,
    ):
        mock_settings.return_value = MagicMock(TEST_MODE_GCAL_SKIP=True)

        from agent.services.gcal_push_service import update_gcal_event_status

        result = await update_gcal_event_status(
            stylist_id=_make_uuid(),
            event_id="fake_event_id",
            new_status="confirmed",
            customer_name="Test User",
            service_names="Corte",
        )

    assert result is None
    mock_gcal.assert_not_called()
    # update_gcal_event_status has no appointment_id — no status write expected
    mock_write.assert_not_called()


# ---------------------------------------------------------------------------
# delete_gcal_event — with appointment_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_gcal_event_skip_with_appointment_id() -> None:
    """AS1: delete_gcal_event writes not_applicable status when appointment_id provided and skip active."""
    appt_id = _make_uuid()

    with (
        patch("agent.services.gcal_push_service.get_settings") as mock_settings,
        patch("agent.services.gcal_push_service._write_gcal_status", new_callable=AsyncMock) as mock_write,
        patch("agent.services.gcal_push_service._get_calendar_service") as mock_gcal,
    ):
        mock_settings.return_value = MagicMock(TEST_MODE_GCAL_SKIP=True)

        from agent.services.gcal_push_service import delete_gcal_event

        result = await delete_gcal_event(
            stylist_id=_make_uuid(),
            event_id="fake_event_id",
            appointment_id=appt_id,
        )

    assert result is None
    mock_gcal.assert_not_called()
    mock_write.assert_called_once()
    args = mock_write.call_args.args
    assert args[0] == appt_id
    assert args[1] == "not_applicable"
    assert args[2] == "delete_event"


# ---------------------------------------------------------------------------
# delete_gcal_event — without appointment_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_delete_gcal_event_skip_without_appointment_id() -> None:
    """AS1b: delete_gcal_event logs only (no status write) when no appointment_id and skip active."""
    with (
        patch("agent.services.gcal_push_service.get_settings") as mock_settings,
        patch("agent.services.gcal_push_service._write_gcal_status", new_callable=AsyncMock) as mock_write,
        patch("agent.services.gcal_push_service._get_calendar_service") as mock_gcal,
    ):
        mock_settings.return_value = MagicMock(TEST_MODE_GCAL_SKIP=True)

        from agent.services.gcal_push_service import delete_gcal_event

        result = await delete_gcal_event(
            stylist_id=_make_uuid(),
            event_id="fake_event_id",
        )

    assert result is None
    mock_gcal.assert_not_called()
    mock_write.assert_not_called()


# ---------------------------------------------------------------------------
# Sanity: bypass does NOT activate when TEST_MODE_GCAL_SKIP=False
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_push_appointment_no_skip_calls_gcal() -> None:
    """AS2: When TEST_MODE_GCAL_SKIP=False, function proceeds normally (attempts GCal call)."""
    with (
        patch("agent.services.gcal_push_service.get_settings") as mock_settings,
        patch("agent.services.gcal_push_service._get_stylist_calendar_id", new_callable=AsyncMock) as mock_cal_id,
    ):
        mock_settings.return_value = MagicMock(TEST_MODE_GCAL_SKIP=False)
        mock_cal_id.return_value = None  # No calendar configured — function returns early but it TRIED

        from agent.services.gcal_push_service import push_appointment_to_gcal

        await push_appointment_to_gcal(
            appointment_id=_make_uuid(),
            stylist_id=_make_uuid(),
            customer_name="Test User",
            service_names="Corte",
            start_time=_utcnow(),
            duration_minutes=30,
        )

    # The function tried to get the calendar (didn't bypass)
    mock_cal_id.assert_called_once()
