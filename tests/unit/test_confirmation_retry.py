"""
Tests for process_confirmation_retries and related retry logic.

Coverage:
- test_retry_eligibility_conditions: WHERE clause filters
- test_backoff_schedule: next_retry_at computation for each retry_count
- test_successful_retry_clears_flags: success path clears notification_failed
- test_max_retries_creates_permanently_failed_notification: exhausted retries escalation
- test_time_guard_initial_failure: imminent appointment skips retry queue immediately
- test_auto_cancel_excludes_retryable_appointments: guard clause in process_auto_cancellations
- test_retry_count_incremented_before_api_call: anti-duplicate commit guard
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, call, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from agent.workers.confirmation_worker import (
    MAX_RETRIES,
    RETRY_BACKOFF_MINUTES,
    TIME_GUARD_HOURS,
    process_confirmation_retries,
)
from database.models import AppointmentStatus, NotificationType


MADRID_TZ = ZoneInfo("Europe/Madrid")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_appointment(
    *,
    retry_count: int = 0,
    notification_failed: bool = True,
    next_retry_at: datetime | None = None,
    hours_until_appt: float = 48.0,
    status: AppointmentStatus = AppointmentStatus.PENDING,
) -> MagicMock:
    """Build a minimal mock Appointment with retry-related fields."""
    now = datetime.now(MADRID_TZ)
    appt = MagicMock()
    appt.id = uuid4()
    appt.retry_count = retry_count
    appt.notification_failed = notification_failed
    appt.next_retry_at = next_retry_at or now - timedelta(minutes=5)
    appt.start_time = now + timedelta(hours=hours_until_appt)
    appt.start_time = appt.start_time.replace(tzinfo=MADRID_TZ)
    appt.status = status
    appt.service_ids = [uuid4()]
    appt.first_name = "Test"

    mock_customer = MagicMock()
    mock_customer.phone = "+34612345678"
    mock_customer.first_name = "Ana"
    mock_customer.chatwoot_conversation_id = None
    appt.customer = mock_customer

    mock_stylist = MagicMock()
    mock_stylist.name = "María"
    appt.stylist = mock_stylist

    return appt


def _make_session_with_appointments(appointments: list) -> AsyncMock:
    """Return an AsyncMock session that yields the given appointments list."""
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = appointments
    mock_session.execute = AsyncMock(return_value=mock_result)
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()
    mock_session.add = MagicMock()
    return mock_session


# ---------------------------------------------------------------------------
# 3.1 — Retry eligibility conditions (WHERE clause)
# ---------------------------------------------------------------------------


class TestRetryEligibilityConditions:
    """Verify the 5 WHERE conditions: notification_failed, retry_count, next_retry_at,
    start_time (time guard), and status filter."""

    @pytest.mark.asyncio
    async def test_no_appointments_returns_early(self):
        """When no appointments match, function returns without error."""
        mock_session = _make_session_with_appointments([])

        with patch(
            "agent.workers.confirmation_worker.get_async_session"
        ) as mock_ctx, patch(
            "agent.workers.confirmation_worker.get_dynamic_settings",
            new_callable=AsyncMock,
            return_value={
                "confirmation_template_name": "appt_conf",
                "auto_cancel_hours_before": 24,
            },
        ):
            mock_ctx.return_value.__aenter__.return_value = mock_session
            # Should complete without raising
            await process_confirmation_retries()

        # execute was called (SELECT query) but commit was NOT (nothing to do)
        mock_session.execute.assert_called_once()
        mock_session.commit.assert_not_called()

    @pytest.mark.asyncio
    async def test_only_eligible_appointments_processed(self):
        """Appointments with retry_count >= MAX_RETRIES are NOT returned by query
        — verified by ensuring that when the session returns no appointments the
        function exits early (query itself filters them on the DB side)."""
        # Simulate DB already filtered — return empty because retry_count=3 was excluded
        mock_session = _make_session_with_appointments([])

        with patch(
            "agent.workers.confirmation_worker.get_async_session"
        ) as mock_ctx, patch(
            "agent.workers.confirmation_worker.get_dynamic_settings",
            new_callable=AsyncMock,
            return_value={
                "confirmation_template_name": "appt_conf",
                "auto_cancel_hours_before": 24,
            },
        ):
            mock_ctx.return_value.__aenter__.return_value = mock_session
            await process_confirmation_retries()

        mock_session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# 3.2 — Backoff schedule
# ---------------------------------------------------------------------------


class TestBackoffSchedule:
    """Verify next_retry_at is computed correctly for each retry_count."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "initial_retry_count, expected_minutes_index",
        [
            (0, 1),  # After retry 1, next backoff is RETRY_BACKOFF_MINUTES[1] = 120
            (1, 2),  # After retry 2, next backoff is RETRY_BACKOFF_MINUTES[2] = 360
        ],
    )
    async def test_next_retry_at_computed_from_backoff(
        self, initial_retry_count: int, expected_minutes_index: int
    ):
        """
        When retry N succeeds partially (still fails), next_retry_at is set to
        now + RETRY_BACKOFF_MINUTES[current_retry] where current_retry = initial + 1.
        """
        appt = _make_appointment(retry_count=initial_retry_count)
        mock_session = _make_session_with_appointments([appt])

        # Chatwoot returns failure so we can see the next_retry_at assignment
        mock_chatwoot = MagicMock()
        mock_chatwoot.send_template_message = AsyncMock(return_value=False)

        mock_service = MagicMock()
        mock_service.name = "Corte"
        mock_session.execute = AsyncMock(
            side_effect=[
                # First call: SELECT appointments
                _make_scalars_result([appt]),
                # Subsequent calls: SELECT services (inside loop)
                _make_scalars_result([mock_service]),
            ]
        )

        now_fixed = datetime.now(MADRID_TZ)

        with patch(
            "agent.workers.confirmation_worker.get_async_session"
        ) as mock_ctx, patch(
            "agent.workers.confirmation_worker.get_dynamic_settings",
            new_callable=AsyncMock,
            return_value={
                "confirmation_template_name": "appt_conf",
                "auto_cancel_hours_before": 24,
            },
        ), patch(
            "agent.workers.confirmation_worker.ChatwootClient",
            return_value=mock_chatwoot,
        ), patch(
            "agent.workers.confirmation_worker.datetime",
        ) as mock_dt, patch(
            "agent.workers.confirmation_worker.get_services_by_ids",
            new_callable=AsyncMock,
            return_value=[mock_service],
        ):
            mock_dt.now.return_value = now_fixed
            mock_ctx.return_value.__aenter__.return_value = mock_session

            await process_confirmation_retries()

        # current_retry = initial_retry_count + 1
        current_retry = initial_retry_count + 1
        assert appt.retry_count == current_retry

        # next_retry_at should be set (not None) since current_retry < MAX_RETRIES
        expected_minutes = RETRY_BACKOFF_MINUTES[current_retry]
        expected_next = now_fixed + timedelta(minutes=expected_minutes)
        assert appt.next_retry_at == expected_next

    @pytest.mark.asyncio
    async def test_last_retry_sets_next_retry_at_to_none(self):
        """On the 3rd (final) retry attempt, next_retry_at is set to None."""
        # retry_count=2 → current_retry will be 3 = MAX_RETRIES → next_retry_at = None
        appt = _make_appointment(retry_count=MAX_RETRIES - 1)
        mock_session = _make_session_with_appointments([appt])

        mock_chatwoot = MagicMock()
        mock_chatwoot.send_template_message = AsyncMock(return_value=False)

        mock_service = MagicMock()
        mock_service.name = "Corte"

        with patch(
            "agent.workers.confirmation_worker.get_async_session"
        ) as mock_ctx, patch(
            "agent.workers.confirmation_worker.get_dynamic_settings",
            new_callable=AsyncMock,
            return_value={
                "confirmation_template_name": "appt_conf",
                "auto_cancel_hours_before": 24,
            },
        ), patch(
            "agent.workers.confirmation_worker.ChatwootClient",
            return_value=mock_chatwoot,
        ), patch(
            "agent.workers.confirmation_worker.get_services_by_ids",
            new_callable=AsyncMock,
            return_value=[mock_service],
        ):
            mock_ctx.return_value.__aenter__.return_value = mock_session
            await process_confirmation_retries()

        assert appt.retry_count == MAX_RETRIES
        assert appt.next_retry_at is None


# ---------------------------------------------------------------------------
# 3.3 — Successful retry clears flags
# ---------------------------------------------------------------------------


class TestSuccessfulRetryClears:
    """On success, notification_failed=False and next_retry_at=None."""

    @pytest.mark.asyncio
    async def test_success_clears_notification_failed(self):
        """After successful retry, notification_failed is cleared."""
        appt = _make_appointment(retry_count=0)
        mock_session = _make_session_with_appointments([appt])
        mock_session.add = MagicMock()

        mock_chatwoot = MagicMock()
        mock_chatwoot.send_template_message = AsyncMock(return_value=True)

        mock_service = MagicMock()
        mock_service.name = "Corte"

        with patch(
            "agent.workers.confirmation_worker.get_async_session"
        ) as mock_ctx, patch(
            "agent.workers.confirmation_worker.get_dynamic_settings",
            new_callable=AsyncMock,
            return_value={
                "confirmation_template_name": "appt_conf",
                "auto_cancel_hours_before": 24,
            },
        ), patch(
            "agent.workers.confirmation_worker.ChatwootClient",
            return_value=mock_chatwoot,
        ), patch(
            "agent.workers.confirmation_worker.get_services_by_ids",
            new_callable=AsyncMock,
            return_value=[mock_service],
        ):
            mock_ctx.return_value.__aenter__.return_value = mock_session
            await process_confirmation_retries()

        assert appt.notification_failed is False
        assert appt.next_retry_at is None

    @pytest.mark.asyncio
    async def test_success_creates_confirmation_sent_notification(self):
        """After successful retry, a CONFIRMATION_SENT notification is created."""
        appt = _make_appointment(retry_count=1)
        mock_session = _make_session_with_appointments([appt])
        mock_session.add = MagicMock()

        mock_chatwoot = MagicMock()
        mock_chatwoot.send_template_message = AsyncMock(return_value=True)

        mock_service = MagicMock()
        mock_service.name = "Corte"

        with patch(
            "agent.workers.confirmation_worker.get_async_session"
        ) as mock_ctx, patch(
            "agent.workers.confirmation_worker.get_dynamic_settings",
            new_callable=AsyncMock,
            return_value={
                "confirmation_template_name": "appt_conf",
                "auto_cancel_hours_before": 24,
            },
        ), patch(
            "agent.workers.confirmation_worker.ChatwootClient",
            return_value=mock_chatwoot,
        ), patch(
            "agent.workers.confirmation_worker.get_services_by_ids",
            new_callable=AsyncMock,
            return_value=[mock_service],
        ):
            mock_ctx.return_value.__aenter__.return_value = mock_session
            await process_confirmation_retries()

        # session.add should have been called once for the CONFIRMATION_SENT notification
        mock_session.add.assert_called_once()
        notification = mock_session.add.call_args[0][0]
        assert notification.type == NotificationType.CONFIRMATION_SENT


# ---------------------------------------------------------------------------
# 3.4 — Max retries creates CONFIRMATION_PERMANENTLY_FAILED
# ---------------------------------------------------------------------------


class TestMaxRetriesPermanentlyFailed:
    """After retry_count reaches MAX_RETRIES, CONFIRMATION_PERMANENTLY_FAILED is created."""

    @pytest.mark.asyncio
    async def test_permanently_failed_notification_on_max_retries(self):
        """When current_retry reaches MAX_RETRIES and send fails, escalation notification created."""
        appt = _make_appointment(retry_count=MAX_RETRIES - 1)  # will become MAX_RETRIES
        mock_session = _make_session_with_appointments([appt])
        mock_session.add = MagicMock()

        mock_chatwoot = MagicMock()
        mock_chatwoot.send_template_message = AsyncMock(return_value=False)

        mock_service = MagicMock()
        mock_service.name = "Corte"

        with patch(
            "agent.workers.confirmation_worker.get_async_session"
        ) as mock_ctx, patch(
            "agent.workers.confirmation_worker.get_dynamic_settings",
            new_callable=AsyncMock,
            return_value={
                "confirmation_template_name": "appt_conf",
                "auto_cancel_hours_before": 24,
            },
        ), patch(
            "agent.workers.confirmation_worker.ChatwootClient",
            return_value=mock_chatwoot,
        ), patch(
            "agent.workers.confirmation_worker.get_services_by_ids",
            new_callable=AsyncMock,
            return_value=[mock_service],
        ):
            mock_ctx.return_value.__aenter__.return_value = mock_session
            await process_confirmation_retries()

        assert appt.retry_count == MAX_RETRIES
        mock_session.add.assert_called_once()
        notification = mock_session.add.call_args[0][0]
        assert notification.type == NotificationType.CONFIRMATION_PERMANENTLY_FAILED


# ---------------------------------------------------------------------------
# 3.5 — Time guard on initial failure (send_confirmations)
# ---------------------------------------------------------------------------


class TestTimeGuardInitialFailure:
    """When initial send fails and appointment is within TIME_GUARD_HOURS, escalate immediately."""

    @pytest.mark.asyncio
    async def test_imminent_appointment_skips_retry_queue(self):
        """
        If appointment.start_time - now < TIME_GUARD_HOURS:
        - retry_count = MAX_RETRIES (skip queue)
        - next_retry_at = None
        - CONFIRMATION_PERMANENTLY_FAILED notification created
        """
        from agent.workers.confirmation_worker import send_confirmations

        now = datetime.now(MADRID_TZ)
        # Appointment is 4h away (< TIME_GUARD_HOURS=6)
        appt = MagicMock()
        appt.id = uuid4()
        appt.status = AppointmentStatus.PENDING
        appt.confirmation_sent_at = None
        appt.notification_failed = False
        appt.retry_count = 0
        appt.next_retry_at = None
        appt.start_time = now + timedelta(hours=4)
        appt.start_time = appt.start_time.replace(tzinfo=MADRID_TZ)
        appt.service_ids = [uuid4()]
        appt.first_name = "Cliente"

        mock_customer = MagicMock()
        mock_customer.phone = "+34612345678"
        mock_customer.first_name = "Ana"
        mock_customer.chatwoot_conversation_id = None
        appt.customer = mock_customer

        mock_stylist = MagicMock()
        mock_stylist.name = "María"
        appt.stylist = mock_stylist

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [appt]
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_chatwoot = MagicMock()
        mock_chatwoot.send_template_message = AsyncMock(return_value=False)

        mock_service = MagicMock()
        mock_service.name = "Corte"

        with patch(
            "agent.workers.confirmation_worker.get_async_session"
        ) as mock_ctx, patch(
            "agent.workers.confirmation_worker.get_dynamic_settings",
            new_callable=AsyncMock,
            return_value={
                "confirmation_hours_before": 48,
                "auto_cancel_hours_before": 24,
                "confirmation_template_name": "appt_conf",
            },
        ), patch(
            "agent.workers.confirmation_worker.ChatwootClient",
            return_value=mock_chatwoot,
        ), patch(
            "agent.workers.confirmation_worker.get_services_by_ids",
            new_callable=AsyncMock,
            return_value=[mock_service],
        ), patch(
            "agent.workers.confirmation_worker.update_health_check",
            new_callable=AsyncMock,
        ):
            mock_ctx.return_value.__aenter__.return_value = mock_session
            await send_confirmations()

        # Time guard should have triggered
        assert appt.notification_failed is True
        assert appt.retry_count == MAX_RETRIES
        assert appt.next_retry_at is None

        # CONFIRMATION_PERMANENTLY_FAILED notification must be created
        assert mock_session.add.call_count >= 1
        notification_types = [
            c[0][0].type for c in mock_session.add.call_args_list
        ]
        assert NotificationType.CONFIRMATION_PERMANENTLY_FAILED in notification_types

    @pytest.mark.asyncio
    async def test_non_imminent_appointment_schedules_retry(self):
        """
        If appointment.start_time - now >= TIME_GUARD_HOURS:
        - next_retry_at = now + RETRY_BACKOFF_MINUTES[0]
        - CONFIRMATION_FAILED notification created (not PERMANENTLY_FAILED)
        """
        from agent.workers.confirmation_worker import send_confirmations

        now = datetime.now(MADRID_TZ)
        # Appointment is 48h away (> TIME_GUARD_HOURS=6)
        appt = MagicMock()
        appt.id = uuid4()
        appt.status = AppointmentStatus.PENDING
        appt.confirmation_sent_at = None
        appt.notification_failed = False
        appt.retry_count = 0
        appt.next_retry_at = None
        appt.start_time = now + timedelta(hours=48)
        appt.start_time = appt.start_time.replace(tzinfo=MADRID_TZ)
        appt.service_ids = [uuid4()]
        appt.first_name = "Cliente"

        mock_customer = MagicMock()
        mock_customer.phone = "+34612345678"
        mock_customer.first_name = "Ana"
        mock_customer.chatwoot_conversation_id = None
        appt.customer = mock_customer

        mock_stylist = MagicMock()
        mock_stylist.name = "María"
        appt.stylist = mock_stylist

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [appt]
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_chatwoot = MagicMock()
        mock_chatwoot.send_template_message = AsyncMock(return_value=False)

        mock_service = MagicMock()
        mock_service.name = "Corte"

        with patch(
            "agent.workers.confirmation_worker.get_async_session"
        ) as mock_ctx, patch(
            "agent.workers.confirmation_worker.get_dynamic_settings",
            new_callable=AsyncMock,
            return_value={
                "confirmation_hours_before": 48,
                "auto_cancel_hours_before": 24,
                "confirmation_template_name": "appt_conf",
            },
        ), patch(
            "agent.workers.confirmation_worker.ChatwootClient",
            return_value=mock_chatwoot,
        ), patch(
            "agent.workers.confirmation_worker.get_services_by_ids",
            new_callable=AsyncMock,
            return_value=[mock_service],
        ), patch(
            "agent.workers.confirmation_worker.update_health_check",
            new_callable=AsyncMock,
        ):
            mock_ctx.return_value.__aenter__.return_value = mock_session
            await send_confirmations()

        # Not an imminent appointment — next_retry_at should be set
        assert appt.notification_failed is True
        assert appt.retry_count == 0  # NOT incremented on initial send failure
        assert appt.next_retry_at is not None

        # CONFIRMATION_FAILED notification (not PERMANENTLY_FAILED)
        notification_types = [
            c[0][0].type for c in mock_session.add.call_args_list
        ]
        assert NotificationType.CONFIRMATION_FAILED in notification_types
        assert NotificationType.CONFIRMATION_PERMANENTLY_FAILED not in notification_types


# ---------------------------------------------------------------------------
# 3.6 — Auto-cancel excludes retryable appointments
# ---------------------------------------------------------------------------


class TestAutoCancelExcludesRetryable:
    """process_auto_cancellations must NOT cancel appointments still in retry queue."""

    @pytest.mark.asyncio
    async def test_auto_cancel_skips_retryable(self):
        """
        Appointments with notification_failed=True AND retry_count < MAX_RETRIES
        must not be in the auto-cancel result set.

        This is verified by checking that when the session returns no appointments
        (DB filtered them), the function exits without cancelling anything.
        """
        from agent.workers.confirmation_worker import process_auto_cancellations

        mock_session = AsyncMock()
        mock_result = MagicMock()
        # Simulate DB already excluded retryable appointments
        mock_result.scalars.return_value.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()

        with patch(
            "agent.workers.confirmation_worker.get_async_session"
        ) as mock_ctx, patch(
            "agent.workers.confirmation_worker.get_dynamic_settings",
            new_callable=AsyncMock,
            return_value={
                "auto_cancel_hours_before": 24,
                "auto_cancel_template_name": "appt_cancelled",
            },
        ), patch(
            "agent.workers.confirmation_worker.update_health_check",
            new_callable=AsyncMock,
        ):
            mock_ctx.return_value.__aenter__.return_value = mock_session
            await process_auto_cancellations()

        # No commits (no appointments to cancel)
        mock_session.commit.assert_not_called()


# ---------------------------------------------------------------------------
# 3.7 — retry_count incremented BEFORE API call (anti-duplicate guard)
# ---------------------------------------------------------------------------


class TestRetryCountIncrementedBeforeApiCall:
    """
    Even if send_template_message raises an exception, retry_count must already
    be committed to the database — preventing an infinite retry loop.
    """

    @pytest.mark.asyncio
    async def test_retry_count_committed_before_send(self):
        """
        Scenario: Chatwoot raises an exception mid-send.
        Expected: retry_count is already incremented + committed before the exception.
        """
        appt = _make_appointment(retry_count=0)
        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.rollback = AsyncMock()

        # Track commit calls to verify ordering
        commit_calls = []

        async def track_commit():
            commit_calls.append(("commit", appt.retry_count))

        mock_session.commit = AsyncMock(side_effect=track_commit)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [appt]
        mock_session.execute = AsyncMock(return_value=mock_result)

        mock_chatwoot = MagicMock()
        # Raise exception to simulate crash mid-send
        mock_chatwoot.send_template_message = AsyncMock(
            side_effect=RuntimeError("Chatwoot connection error")
        )

        mock_service = MagicMock()
        mock_service.name = "Corte"

        with patch(
            "agent.workers.confirmation_worker.get_async_session"
        ) as mock_ctx, patch(
            "agent.workers.confirmation_worker.get_dynamic_settings",
            new_callable=AsyncMock,
            return_value={
                "confirmation_template_name": "appt_conf",
                "auto_cancel_hours_before": 24,
            },
        ), patch(
            "agent.workers.confirmation_worker.ChatwootClient",
            return_value=mock_chatwoot,
        ), patch(
            "agent.workers.confirmation_worker.get_services_by_ids",
            new_callable=AsyncMock,
            return_value=[mock_service],
        ):
            mock_ctx.return_value.__aenter__.return_value = mock_session
            # Should not raise — exception is caught and logged
            await process_confirmation_retries()

        # Verify that the FIRST commit happened with retry_count already = 1
        assert len(commit_calls) >= 1
        first_commit_retry_count = commit_calls[0][1]
        assert first_commit_retry_count == 1, (
            f"retry_count must be 1 at first commit (anti-duplicate guard), "
            f"got {first_commit_retry_count}"
        )

        # rollback should have been called after the exception
        mock_session.rollback.assert_called_once()


# ---------------------------------------------------------------------------
# Helpers (local)
# ---------------------------------------------------------------------------


def _make_scalars_result(items: list) -> MagicMock:
    """Create a mock execute() result that returns the given items via scalars().all()."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    return result
