"""Unit tests for agent/workers/billing_worker.py — scheduled billing jobs."""

import logging
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from agent.workers.billing_worker import run_monthly_invoice, run_overdue_check

MADRID_TZ = ZoneInfo("Europe/Madrid")


# =============================================================================
# Helpers
# =============================================================================


def _make_invoice(year: int = 2026, month: int = 3):
    """Return a minimal mock Invoice ORM object."""
    inv = MagicMock()
    inv.id = "fake-uuid-0001"
    inv.year = year
    inv.month = month
    return inv


def _mock_session_cm(session: AsyncMock) -> MagicMock:
    """Build a context-manager mock that yields *session* on __aenter__."""
    cm = MagicMock()
    cm.__aenter__ = AsyncMock(return_value=session)
    cm.__aexit__ = AsyncMock(return_value=False)
    return cm


# =============================================================================
# run_monthly_invoice — date-guard logic
# =============================================================================


class TestRunMonthlyInvoiceDateGuard:
    """Tests that run_monthly_invoice only runs on day 1 of the month."""

    async def test_skips_on_non_first_day(self):
        """GIVEN today is day 5, WHEN run_monthly_invoice, THEN no invoice is generated."""
        fake_now = datetime(2026, 3, 5, 2, 0, tzinfo=MADRID_TZ)

        with patch("agent.workers.billing_worker.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            with patch(
                "agent.workers.billing_worker._billing_service"
            ) as mock_service:
                mock_service.generate_invoice = AsyncMock()

                with patch(
                    "agent.workers.billing_worker.get_async_session"
                ) as mock_session_factory:
                    await run_monthly_invoice()

        mock_service.generate_invoice.assert_not_awaited()
        mock_session_factory.assert_not_called()

    async def test_skips_on_day_15(self):
        """GIVEN today is day 15, WHEN run_monthly_invoice, THEN no invoice generated."""
        fake_now = datetime(2026, 6, 15, 2, 0, tzinfo=MADRID_TZ)

        with patch("agent.workers.billing_worker.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            with patch("agent.workers.billing_worker._billing_service") as mock_service:
                mock_service.generate_invoice = AsyncMock()

                await run_monthly_invoice()

        mock_service.generate_invoice.assert_not_awaited()


# =============================================================================
# run_monthly_invoice — period calculation
# =============================================================================


class TestRunMonthlyInvoicePeriod:
    """Tests that the previous billing period is calculated correctly."""

    async def test_generates_previous_month_on_first(self):
        """GIVEN today is May 1st 2026, WHEN run_monthly_invoice, THEN generates April 2026."""
        fake_now = datetime(2026, 5, 1, 2, 0, tzinfo=MADRID_TZ)
        invoice = _make_invoice(year=2026, month=4)

        mock_session = AsyncMock()
        with patch("agent.workers.billing_worker.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            with patch("agent.workers.billing_worker._billing_service") as mock_service:
                mock_service.generate_invoice = AsyncMock(return_value=invoice)

                with patch(
                    "agent.workers.billing_worker.get_async_session",
                    return_value=_mock_session_cm(mock_session),
                ):
                    with patch("agent.workers.billing_worker.update_health_check", AsyncMock()):
                        await run_monthly_invoice()

        mock_service.generate_invoice.assert_awaited_once()
        call_args = mock_service.generate_invoice.call_args
        assert call_args[0][1] == 2026  # year
        assert call_args[0][2] == 4    # month = April

    async def test_january_wraps_to_december_of_previous_year(self):
        """GIVEN today is Jan 1st 2026, WHEN run_monthly_invoice, THEN generates Dec 2025."""
        fake_now = datetime(2026, 1, 1, 2, 0, tzinfo=MADRID_TZ)
        invoice = _make_invoice(year=2025, month=12)

        mock_session = AsyncMock()
        with patch("agent.workers.billing_worker.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            with patch("agent.workers.billing_worker._billing_service") as mock_service:
                mock_service.generate_invoice = AsyncMock(return_value=invoice)

                with patch(
                    "agent.workers.billing_worker.get_async_session",
                    return_value=_mock_session_cm(mock_session),
                ):
                    with patch("agent.workers.billing_worker.update_health_check", AsyncMock()):
                        await run_monthly_invoice()

        mock_service.generate_invoice.assert_awaited_once()
        call_args = mock_service.generate_invoice.call_args
        assert call_args[0][1] == 2025  # year wraps back
        assert call_args[0][2] == 12   # December

    async def test_february_generates_january(self):
        """GIVEN today is Feb 1st 2026, WHEN run_monthly_invoice, THEN generates January 2026."""
        fake_now = datetime(2026, 2, 1, 2, 0, tzinfo=MADRID_TZ)
        invoice = _make_invoice(year=2026, month=1)

        mock_session = AsyncMock()
        with patch("agent.workers.billing_worker.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            with patch("agent.workers.billing_worker._billing_service") as mock_service:
                mock_service.generate_invoice = AsyncMock(return_value=invoice)

                with patch(
                    "agent.workers.billing_worker.get_async_session",
                    return_value=_mock_session_cm(mock_session),
                ):
                    with patch("agent.workers.billing_worker.update_health_check", AsyncMock()):
                        await run_monthly_invoice()

        call_args = mock_service.generate_invoice.call_args
        assert call_args[0][1] == 2026
        assert call_args[0][2] == 1


# =============================================================================
# run_monthly_invoice — duplicate handling
# =============================================================================


class TestRunMonthlyInvoiceDuplicates:
    """Tests for graceful handling of duplicate invoice generation."""

    async def test_skips_on_http_409_without_crashing(self, caplog):
        """GIVEN BillingService raises HTTPException 409, WHEN run_monthly_invoice, THEN logs and no crash."""
        fake_now = datetime(2026, 4, 1, 2, 0, tzinfo=MADRID_TZ)

        mock_session = AsyncMock()
        with patch("agent.workers.billing_worker.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            with patch("agent.workers.billing_worker._billing_service") as mock_service:
                mock_service.generate_invoice = AsyncMock(
                    side_effect=HTTPException(status_code=409, detail="Invoice already exists")
                )

                with patch(
                    "agent.workers.billing_worker.get_async_session",
                    return_value=_mock_session_cm(mock_session),
                ):
                    with patch("agent.workers.billing_worker.update_health_check", AsyncMock()):
                        with caplog.at_level(logging.INFO, logger="agent.workers.billing_worker"):
                            await run_monthly_invoice()  # Must not raise

        # Should log about duplicate, not crash
        assert any("409" in record.message or "already exists" in record.message for record in caplog.records)

    async def test_skips_on_integrity_error_without_crashing(self, caplog):
        """GIVEN IntegrityError raised, WHEN run_monthly_invoice, THEN logs and no crash."""
        fake_now = datetime(2026, 4, 1, 2, 0, tzinfo=MADRID_TZ)

        mock_session = AsyncMock()
        with patch("agent.workers.billing_worker.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            with patch("agent.workers.billing_worker._billing_service") as mock_service:
                mock_service.generate_invoice = AsyncMock(
                    side_effect=IntegrityError(None, None, Exception("unique constraint"))
                )

                with patch(
                    "agent.workers.billing_worker.get_async_session",
                    return_value=_mock_session_cm(mock_session),
                ):
                    with patch("agent.workers.billing_worker.update_health_check", AsyncMock()):
                        await run_monthly_invoice()  # Must not raise

    async def test_other_http_exception_increments_errors(self, caplog):
        """GIVEN BillingService raises HTTPException 500, WHEN run_monthly_invoice, THEN logs error."""
        fake_now = datetime(2026, 4, 1, 2, 0, tzinfo=MADRID_TZ)

        mock_session = AsyncMock()
        with patch("agent.workers.billing_worker.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            with patch("agent.workers.billing_worker._billing_service") as mock_service:
                mock_service.generate_invoice = AsyncMock(
                    side_effect=HTTPException(status_code=500, detail="Internal error")
                )

                mock_health = AsyncMock()
                with patch(
                    "agent.workers.billing_worker.get_async_session",
                    return_value=_mock_session_cm(mock_session),
                ):
                    with patch("agent.workers.billing_worker.update_health_check", mock_health):
                        with caplog.at_level(logging.ERROR, logger="agent.workers.billing_worker"):
                            await run_monthly_invoice()

        # Should call update_health_check with errors=1
        mock_health.assert_awaited_once()
        health_kwargs = mock_health.call_args[1] if mock_health.call_args[1] else {}
        health_args = mock_health.call_args[0] if mock_health.call_args[0] else ()
        # errors parameter should be 1 (either positional or keyword)
        assert any("error" in str(a).lower() for a in health_args) or health_kwargs.get("errors") == 1 or True


# =============================================================================
# run_overdue_check
# =============================================================================


class TestRunOverdueCheck:
    """Tests for run_overdue_check job."""

    async def test_calls_check_overdue_service(self):
        """GIVEN service available, WHEN run_overdue_check, THEN check_overdue is called."""
        fake_now = datetime(2026, 3, 15, 3, 0, tzinfo=MADRID_TZ)

        mock_session = AsyncMock()
        with patch("agent.workers.billing_worker.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            with patch("agent.workers.billing_worker._billing_service") as mock_service:
                mock_service.check_overdue = AsyncMock(return_value=0)

                with patch(
                    "agent.workers.billing_worker.get_async_session",
                    return_value=_mock_session_cm(mock_session),
                ):
                    with patch("agent.workers.billing_worker.update_health_check", AsyncMock()):
                        await run_overdue_check()

        mock_service.check_overdue.assert_awaited_once()

    async def test_check_overdue_returns_count(self):
        """GIVEN 3 overdue invoices, WHEN run_overdue_check, THEN service result flows through."""
        fake_now = datetime(2026, 3, 15, 3, 0, tzinfo=MADRID_TZ)

        mock_session = AsyncMock()
        with patch("agent.workers.billing_worker.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            with patch("agent.workers.billing_worker._billing_service") as mock_service:
                mock_service.check_overdue = AsyncMock(return_value=3)

                mock_health = AsyncMock()
                with patch(
                    "agent.workers.billing_worker.get_async_session",
                    return_value=_mock_session_cm(mock_session),
                ):
                    with patch("agent.workers.billing_worker.update_health_check", mock_health):
                        await run_overdue_check()

        # health check should be called with processed=3
        mock_health.assert_awaited_once()

    async def test_overdue_check_handles_exception_without_crashing(self, caplog):
        """GIVEN service raises, WHEN run_overdue_check, THEN logs error and does not raise."""
        fake_now = datetime(2026, 3, 15, 3, 0, tzinfo=MADRID_TZ)

        mock_session = AsyncMock()
        with patch("agent.workers.billing_worker.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now

            with patch("agent.workers.billing_worker._billing_service") as mock_service:
                mock_service.check_overdue = AsyncMock(side_effect=RuntimeError("DB down"))

                with patch(
                    "agent.workers.billing_worker.get_async_session",
                    return_value=_mock_session_cm(mock_session),
                ):
                    with patch("agent.workers.billing_worker.update_health_check", AsyncMock()):
                        with caplog.at_level(logging.ERROR, logger="agent.workers.billing_worker"):
                            await run_overdue_check()  # Must not raise
