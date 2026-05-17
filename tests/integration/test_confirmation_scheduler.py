"""
Integration test: confirmation scheduler loop (REQ-C).

Verifies that send_confirmations() is called on EVERY hourly interval cycle,
not just once per day. Also verifies send_reminders() and
process_confirmation_retries() run in each cycle.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

MADRID_TZ = ZoneInfo("Europe/Madrid")


async def _run_two_cycles(
    mock_reminders: AsyncMock,
    mock_confirmations: AsyncMock,
    mock_retries: AsyncMock,
) -> None:
    """
    Drive async_main() through exactly two hourly interval cycles, then shut it down.
    Each cycle corresponds to should_run_reminders becoming True.
    """
    import agent.workers.confirmation_worker as worker_module

    worker_module.shutdown_requested = False

    cycle_count = 0

    async def fake_sleep(_duration: float) -> None:
        nonlocal cycle_count
        cycle_count += 1
        if cycle_count >= 2:
            # Stop after 2 sleep calls (2 complete loop iterations)
            worker_module.shutdown_requested = True

    dynamic_settings = {
        # Job schedule settings
        "confirmation_job_time": "23:59",  # Irrelevant time — won't trigger daily jobs
        "auto_cancel_job_time": "23:59",
        "reminder_job_interval": "hourly",
        # Hours-before settings
        "confirmation_hours_before": 48,
        "auto_cancel_hours_before": 24,
        "reminder_hours_before": 2,
        # Template name settings
        "confirmation_template_name": "appointment_confirmation_48h",
        "auto_cancel_template_name": "appointment_auto_cancelled",
        "reminder_template_name": "appointment_reminder_2h",
    }

    # Advancing datetimes: each call to datetime.now() returns 61 minutes later,
    # so the reminder interval check (>= 60 min) triggers on every loop iteration.
    base_now = datetime(2026, 3, 26, 14, 0, 0, tzinfo=MADRID_TZ)
    call_count_dt = 0

    def advancing_now(_tz=None):
        nonlocal call_count_dt
        result = base_now + timedelta(minutes=61 * call_count_dt)
        call_count_dt += 1
        return result

    mock_reminder_retries = AsyncMock()

    with (
        patch.object(worker_module, "send_reminders", mock_reminders),
        patch.object(worker_module, "send_confirmations", mock_confirmations),
        patch.object(worker_module, "process_confirmation_retries", mock_retries),
        patch.object(worker_module, "process_reminder_retries", mock_reminder_retries),
        patch.object(worker_module, "process_auto_cancellations", new_callable=AsyncMock),
        patch.object(worker_module.asyncio, "sleep", fake_sleep),
        patch(
            "agent.workers.confirmation_worker.get_dynamic_settings",
            new_callable=AsyncMock,
            return_value=dynamic_settings,
        ),
        patch("agent.workers.confirmation_worker.datetime") as mock_dt,
    ):
        mock_dt.now.side_effect = advancing_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        await worker_module.async_main()


@pytest.mark.asyncio
async def test_send_confirmations_called_in_both_cycles():
    """send_confirmations() must be called in both scheduler cycles (not gated by day)."""
    mock_reminders = AsyncMock()
    mock_confirmations = AsyncMock()
    mock_retries = AsyncMock()

    await _run_two_cycles(mock_reminders, mock_confirmations, mock_retries)

    assert mock_confirmations.call_count >= 2, (
        f"Expected send_confirmations() called at least 2 times (once per cycle), "
        f"got {mock_confirmations.call_count}"
    )


@pytest.mark.asyncio
async def test_send_reminders_called_in_both_cycles():
    """send_reminders() must run in both scheduler cycles."""
    mock_reminders = AsyncMock()
    mock_confirmations = AsyncMock()
    mock_retries = AsyncMock()

    await _run_two_cycles(mock_reminders, mock_confirmations, mock_retries)

    assert mock_reminders.call_count >= 2, (
        f"Expected send_reminders() called at least 2 times, got {mock_reminders.call_count}"
    )


@pytest.mark.asyncio
async def test_process_confirmation_retries_called_in_both_cycles():
    """process_confirmation_retries() must run in both scheduler cycles."""
    mock_reminders = AsyncMock()
    mock_confirmations = AsyncMock()
    mock_retries = AsyncMock()

    await _run_two_cycles(mock_reminders, mock_confirmations, mock_retries)

    assert mock_retries.call_count >= 2, (
        f"Expected process_confirmation_retries() called at least 2 times, "
        f"got {mock_retries.call_count}"
    )


@pytest.mark.asyncio
async def test_send_confirmations_runs_alongside_reminders():
    """All three jobs (reminders, confirmations, retries) run together in each cycle."""
    mock_reminders = AsyncMock()
    mock_confirmations = AsyncMock()
    mock_retries = AsyncMock()

    await _run_two_cycles(mock_reminders, mock_confirmations, mock_retries)

    # All three must have been called — they are co-located in the same block
    assert mock_reminders.called, "send_reminders() was not called"
    assert mock_confirmations.called, "send_confirmations() was not called"
    assert mock_retries.called, "process_confirmation_retries() was not called"
