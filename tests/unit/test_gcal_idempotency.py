"""
Unit tests for Google Calendar push idempotency via requestId.

Tests verify that:
- push_appointment_to_gcal passes requestId=str(appointment_id) to events().insert()
- requestId is stable across retries (same value on all attempts)
- push_blocking_event_to_gcal passes requestId=str(blocking_event_id)

All GCal API calls are mocked — no real network or DB access.
asyncio_mode = "auto" (set in pyproject.toml) — no @pytest.mark.asyncio needed.
"""

import contextlib
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from googleapiclient.errors import HttpError

MADRID_TZ = ZoneInfo("Europe/Madrid")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_mock_session():
    """Return an async context manager mock that yields a session mock."""
    mock_session = AsyncMock()

    @contextlib.asynccontextmanager
    async def _mock_ctx():
        yield mock_session

    return _mock_ctx, mock_session


def _make_gcal_service_mock(event_id: str = "gcal-event-abc123") -> MagicMock:
    """
    Build a minimal Google Calendar service mock that returns a fake event on insert().execute().

    Returns the service mock (top-level object passed back from _get_calendar_service()).
    """
    mock_service = MagicMock()
    mock_execute = MagicMock(return_value={"id": event_id, "status": "confirmed"})
    mock_insert_request = MagicMock()
    mock_insert_request.execute = mock_execute
    mock_service.events.return_value.insert.return_value = mock_insert_request
    return mock_service


def _make_http_error(status: int, reason: str = "Service Unavailable") -> HttpError:
    """Create a fake HttpError with the given HTTP status code."""
    mock_resp = MagicMock()
    mock_resp.status = status
    mock_resp.reason = reason
    return HttpError(resp=mock_resp, content=b"error body")


# ---------------------------------------------------------------------------
# Test: Appointment push passes requestId
# ---------------------------------------------------------------------------


class TestAppointmentPushIdempotency:
    """Verify that push_appointment_to_gcal passes the correct requestId."""

    async def test_normal_push_uses_appointment_id_as_request_id(self):
        """
        Normal successful push: requestId must equal str(appointment_id).

        Scenario:
        - GCal service is available, returns a new event on first call
        - events().insert() is called exactly once with requestId=str(appointment_id)
        """
        appointment_id = uuid4()
        stylist_id = uuid4()
        calendar_id = "stylist-cal@group.calendar.google.com"
        start_time = datetime(2026, 5, 10, 11, 0, tzinfo=MADRID_TZ)

        mock_service = _make_gcal_service_mock(event_id="evt-001")
        mock_ctx, mock_session = _make_mock_session()

        # Stub stylist calendar lookup result
        mock_result = MagicMock()
        mock_result.first.return_value = (calendar_id,)
        mock_session.execute = AsyncMock(return_value=mock_result)

        with (
            patch(
                "agent.services.gcal_push_service._get_calendar_service",
                return_value=mock_service,
            ),
            patch(
                "agent.services.gcal_push_service.get_async_session",
                new=mock_ctx,
            ),
            patch(
                "agent.services.gcal_push_service._update_appointment_gcal_id",
                new=AsyncMock(),
            ),
        ):
            from agent.services.gcal_push_service import push_appointment_to_gcal

            result = await push_appointment_to_gcal(
                appointment_id=appointment_id,
                stylist_id=stylist_id,
                customer_name="Ana García",
                service_names="Corte y Color",
                start_time=start_time,
                duration_minutes=90,
                status="confirmed",
            )

        assert result == "evt-001"

        # Verify events().insert() was called with requestId=str(appointment_id)
        insert_call_kwargs = mock_service.events.return_value.insert.call_args
        assert insert_call_kwargs is not None, "events().insert() was never called"
        assert insert_call_kwargs.kwargs.get("requestId") == str(appointment_id), (
            f"Expected requestId={str(appointment_id)!r}, "
            f"got {insert_call_kwargs.kwargs.get('requestId')!r}"
        )
        # calendarId must also be correct
        assert insert_call_kwargs.kwargs.get("calendarId") == calendar_id

    async def test_retry_uses_same_request_id(self):
        """
        Timeout-then-recovery: requestId must be identical on all retry attempts.

        Scenario:
        - First call raises HttpError 503 (transient failure)
        - Second call succeeds and returns the event
        - GCal deduplication guarantees only one event is created because requestId is stable

        Implementation note: _retry_with_backoff wraps create_event_with_retry, which captures
        request_id from the outer scope — so it's the same object across retries.
        """
        appointment_id = uuid4()
        stylist_id = uuid4()
        calendar_id = "stylist-cal@group.calendar.google.com"
        start_time = datetime(2026, 6, 15, 9, 30, tzinfo=MADRID_TZ)

        # Build service mock: first insert fails 503, second succeeds
        mock_service = MagicMock()
        error_503 = _make_http_error(503)
        success_response = {"id": "evt-dedup-002", "status": "confirmed"}

        mock_insert_request = MagicMock()
        mock_insert_request.execute.side_effect = [error_503, success_response]
        mock_service.events.return_value.insert.return_value = mock_insert_request

        mock_ctx, mock_session = _make_mock_session()
        mock_result = MagicMock()
        mock_result.first.return_value = (calendar_id,)
        mock_session.execute = AsyncMock(return_value=mock_result)

        with (
            patch(
                "agent.services.gcal_push_service._get_calendar_service",
                return_value=mock_service,
            ),
            patch(
                "agent.services.gcal_push_service.get_async_session",
                new=mock_ctx,
            ),
            patch(
                "agent.services.gcal_push_service._update_appointment_gcal_id",
                new=AsyncMock(),
            ),
            # Skip actual sleep to keep tests fast
            patch("agent.services.gcal_push_service.asyncio.sleep", new=AsyncMock()),
        ):
            from agent.services.gcal_push_service import push_appointment_to_gcal

            result = await push_appointment_to_gcal(
                appointment_id=appointment_id,
                stylist_id=stylist_id,
                customer_name="María López",
                service_names="Mechas",
                start_time=start_time,
                duration_minutes=120,
                status="pending",
            )

        assert result == "evt-dedup-002"

        # events().insert() was called twice (one failure + one success)
        assert mock_service.events.return_value.insert.call_count == 2, (
            f"Expected 2 insert() calls (1 retry), "
            f"got {mock_service.events.return_value.insert.call_count}"
        )

        # Both calls must use the SAME requestId (idempotency key must be stable)
        all_calls = mock_service.events.return_value.insert.call_args_list
        request_ids = [c.kwargs.get("requestId") for c in all_calls]
        assert len(set(request_ids)) == 1, (
            f"requestId changed between retries: {request_ids}"
        )
        assert request_ids[0] == str(appointment_id), (
            f"Expected requestId={str(appointment_id)!r}, got {request_ids[0]!r}"
        )


# ---------------------------------------------------------------------------
# Test: Blocking event push passes requestId
# ---------------------------------------------------------------------------


class TestBlockingEventPushIdempotency:
    """Verify that push_blocking_event_to_gcal passes the correct requestId."""

    async def test_blocking_event_push_uses_blocking_event_id_as_request_id(self):
        """
        Normal blocking event push: requestId must equal str(blocking_event_id).

        Scenario:
        - GCal service is available, returns a new event on first call
        - events().insert() is called with requestId=str(blocking_event_id)
        """
        blocking_event_id = uuid4()
        stylist_id = uuid4()
        calendar_id = "stylist2-cal@group.calendar.google.com"
        start_time = datetime(2026, 7, 20, 8, 0, tzinfo=MADRID_TZ)
        end_time = datetime(2026, 7, 25, 20, 0, tzinfo=MADRID_TZ)

        mock_service = _make_gcal_service_mock(event_id="blocking-evt-xyz")

        mock_ctx, mock_session = _make_mock_session()
        mock_result = MagicMock()
        mock_result.first.return_value = (calendar_id,)
        mock_session.execute = AsyncMock(return_value=mock_result)

        with (
            patch(
                "agent.services.gcal_push_service._get_calendar_service",
                return_value=mock_service,
            ),
            patch(
                "agent.services.gcal_push_service.get_async_session",
                new=mock_ctx,
            ),
            patch(
                "agent.services.gcal_push_service._update_blocking_event_gcal_id",
                new=AsyncMock(),
            ),
        ):
            from agent.services.gcal_push_service import push_blocking_event_to_gcal

            result = await push_blocking_event_to_gcal(
                blocking_event_id=blocking_event_id,
                stylist_id=stylist_id,
                title="Vacaciones de verano",
                description="Cerrado por vacaciones",
                start_time=start_time,
                end_time=end_time,
                event_type="vacation",
            )

        assert result == "blocking-evt-xyz"

        # Verify events().insert() was called with requestId=str(blocking_event_id)
        insert_call_kwargs = mock_service.events.return_value.insert.call_args
        assert insert_call_kwargs is not None, "events().insert() was never called"
        assert insert_call_kwargs.kwargs.get("requestId") == str(blocking_event_id), (
            f"Expected requestId={str(blocking_event_id)!r}, "
            f"got {insert_call_kwargs.kwargs.get('requestId')!r}"
        )
        # Also check calendarId is correct
        assert insert_call_kwargs.kwargs.get("calendarId") == calendar_id
