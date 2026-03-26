"""
Unit tests for Google Calendar push parameters.

Tests verify that:
- push_appointment_to_gcal does NOT pass requestId to events().insert()
- requestId is absent on all retry attempts
- push_blocking_event_to_gcal does NOT pass requestId to events().insert()

All GCal API calls are mocked — no real network or DB access.
asyncio_mode = "auto" (set in pyproject.toml) — no @pytest.mark.asyncio needed.
"""

import contextlib
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

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
# Test: Appointment push does NOT pass requestId
# ---------------------------------------------------------------------------


class TestAppointmentPushParams:
    """Verify that push_appointment_to_gcal does not pass requestId to events().insert()."""

    async def test_appointment_push_does_not_pass_request_id(self):
        """
        Normal successful push: requestId must NOT be present in events().insert() kwargs.

        Scenario:
        - GCal service is available, returns a new event on first call
        - events().insert() is called exactly once, without requestId
        - calendarId and body ARE passed (core parameters must remain)
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

        insert_call_kwargs = mock_service.events.return_value.insert.call_args
        assert insert_call_kwargs is not None, "events().insert() was never called"

        # requestId must NOT be present — it is not a valid GCal REST API parameter
        assert "requestId" not in insert_call_kwargs.kwargs, (
            f"requestId should not be passed to events().insert(), "
            f"got kwargs={insert_call_kwargs.kwargs!r}"
        )

        # Core parameters must still be present
        assert insert_call_kwargs.kwargs.get("calendarId") == calendar_id
        assert "body" in insert_call_kwargs.kwargs

    async def test_appointment_push_retry_does_not_pass_request_id(self):
        """
        Timeout-then-recovery: requestId must be absent on all retry attempts.

        Scenario:
        - First call raises HttpError 503 (transient failure)
        - Second call succeeds and returns the event
        - Neither attempt should pass requestId to events().insert()
        """
        appointment_id = uuid4()
        stylist_id = uuid4()
        calendar_id = "stylist-cal@group.calendar.google.com"
        start_time = datetime(2026, 6, 15, 9, 30, tzinfo=MADRID_TZ)

        # Build service mock: first insert fails 503, second succeeds
        mock_service = MagicMock()
        error_503 = _make_http_error(503)
        success_response = {"id": "evt-retry-002", "status": "confirmed"}

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

        assert result == "evt-retry-002"

        # events().insert() was called twice (one failure + one success)
        assert mock_service.events.return_value.insert.call_count == 2, (
            f"Expected 2 insert() calls (1 retry), "
            f"got {mock_service.events.return_value.insert.call_count}"
        )

        # Neither call must pass requestId
        all_calls = mock_service.events.return_value.insert.call_args_list
        for i, c in enumerate(all_calls):
            assert "requestId" not in c.kwargs, (
                f"Call {i + 1} should not pass requestId, got kwargs={c.kwargs!r}"
            )


# ---------------------------------------------------------------------------
# Test: Blocking event push does NOT pass requestId
# ---------------------------------------------------------------------------


class TestBlockingEventPushParams:
    """Verify that push_blocking_event_to_gcal does not pass requestId to events().insert()."""

    async def test_blocking_event_push_does_not_pass_request_id(self):
        """
        Normal blocking event push: requestId must NOT be present in events().insert() kwargs.

        Scenario:
        - GCal service is available, returns a new event on first call
        - events().insert() is called without requestId
        - calendarId and body ARE passed (core parameters must remain)
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

        insert_call_kwargs = mock_service.events.return_value.insert.call_args
        assert insert_call_kwargs is not None, "events().insert() was never called"

        # requestId must NOT be present — it is not a valid GCal REST API parameter
        assert "requestId" not in insert_call_kwargs.kwargs, (
            f"requestId should not be passed to events().insert(), "
            f"got kwargs={insert_call_kwargs.kwargs!r}"
        )

        # Core parameters must still be present
        assert insert_call_kwargs.kwargs.get("calendarId") == calendar_id
        assert "body" in insert_call_kwargs.kwargs
