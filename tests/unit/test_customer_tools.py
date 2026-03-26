"""Unit tests for agent/tools/customer_tools.py — qa-infra-hardening.

Tests REQ-QIH-3: normalize_phone() QA bypass for +34999xxxxxx phones.
Also covers regression tests for valid/invalid Spanish phones.

Also tests T-03/T-04 (REQ-B):
- _derive_confirmation_status() returns correct value for all 5 states
- _derive_reminder_status() returns correct value for both states
- get_customer_history() includes confirmation_status and reminder_status keys
"""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from agent.tools.customer_tools import (
    _derive_confirmation_status,
    _derive_reminder_status,
    normalize_phone,
)


# ============================================================================
# REQ-QIH-3: QA Phone Bypass in normalize_phone()
# ============================================================================


class TestNormalizePhoneQABypass:
    """Tests for the +34999xxxxxx QA safety-prefix bypass."""

    def test_qa_phone_bypass_returns_as_is(self):
        """normalize_phone('+34999000001') returns '+34999000001' unchanged."""
        result = normalize_phone("+34999000001")
        assert result == "+34999000001"

    def test_qa_phone_bypass_different_suffix(self):
        """normalize_phone('+34999123456') returns '+34999123456' unchanged."""
        result = normalize_phone("+34999123456")
        assert result == "+34999123456"

    def test_qa_phone_too_short_does_not_bypass(self):
        """normalize_phone('+34999') is too short — no bypass, returns None."""
        result = normalize_phone("+34999")
        assert result is None

    def test_qa_phone_too_few_suffix_digits_does_not_bypass(self):
        """normalize_phone('+34999000') has only 3 suffix digits — no bypass, returns None."""
        result = normalize_phone("+34999000")
        assert result is None

    def test_qa_phone_too_many_suffix_digits_does_not_bypass(self):
        """+34999 with 7 suffix digits does not match — follows normal path."""
        # +34999 + 7 digits = 13 chars total — does NOT match ^\+34999\d{6}$
        result = normalize_phone("+349991234567")
        # Falls through to phonenumbers validation, which will return None or raise
        # (phonenumbers will treat it as invalid)
        assert result is None

    def test_qa_phone_with_alpha_does_not_bypass(self):
        """+34999abc123 does not match — follows normal path, returns None."""
        result = normalize_phone("+34999abc123")
        assert result is None


# ============================================================================
# Regression: valid Spanish phones still validated normally
# ============================================================================


class TestNormalizePhoneRegression:
    """Regression tests — non-QA phones follow the existing validation path."""

    def test_valid_spanish_mobile_e164(self):
        """Valid Spanish mobile +34600123456 is returned in E.164 format."""
        result = normalize_phone("+34600123456")
        assert result == "+34600123456"

    def test_valid_spanish_mobile_without_prefix(self):
        """Spanish mobile without country code is normalised with +34 prefix."""
        result = normalize_phone("600123456")
        assert result == "+34600123456"

    def test_invalid_phone_returns_none(self):
        """'invalid' returns None."""
        result = normalize_phone("invalid")
        assert result is None

    def test_empty_string_returns_none(self):
        """Empty string returns None."""
        result = normalize_phone("")
        assert result is None


# ============================================================================
# T-03: _derive_confirmation_status() (REQ-B)
# ============================================================================


def _make_mock_appointment(
    *,
    status_value: str = "pending",
    notification_failed: bool = False,
    retry_count: int = 0,
    confirmation_sent_at=None,
    reminder_sent_at=None,
) -> MagicMock:
    """Build a mock Appointment with the given column values."""
    apt = MagicMock()
    apt.status = MagicMock()
    apt.status.value = status_value
    apt.notification_failed = notification_failed
    apt.retry_count = retry_count
    apt.confirmation_sent_at = confirmation_sent_at
    apt.reminder_sent_at = reminder_sent_at
    return apt


class TestDeriveConfirmationStatus:
    """Parametrized tests for _derive_confirmation_status() covering all 5 states."""

    @pytest.mark.parametrize(
        "kwargs,expected",
        [
            # State 1: confirmed — status.value == "confirmed" takes priority
            (
                {"status_value": "confirmed", "confirmation_sent_at": object()},
                "confirmed",
            ),
            # State 2: permanently_failed — notification_failed + retry_count >= 3
            (
                {"notification_failed": True, "retry_count": 3},
                "permanently_failed",
            ),
            # State 3: failed_awaiting_retry — notification_failed but retry_count < 3
            (
                {"notification_failed": True, "retry_count": 1},
                "failed_awaiting_retry",
            ),
            # State 4: sent_awaiting_reply — confirmation_sent_at set, not failed
            (
                {"confirmation_sent_at": object()},
                "sent_awaiting_reply",
            ),
            # State 5: pending — default, nothing set
            (
                {},
                "pending",
            ),
        ],
    )
    def test_derive_confirmation_status(self, kwargs, expected):
        apt = _make_mock_appointment(**kwargs)
        result = _derive_confirmation_status(apt)
        assert result == expected, f"Expected '{expected}', got '{result}' for kwargs={kwargs}"

    def test_permanently_failed_at_exactly_3_retries(self):
        """retry_count == 3 (MAX_RETRIES) is permanently_failed."""
        apt = _make_mock_appointment(notification_failed=True, retry_count=3)
        assert _derive_confirmation_status(apt) == "permanently_failed"

    def test_permanently_failed_above_3_retries(self):
        """retry_count > 3 is also permanently_failed."""
        apt = _make_mock_appointment(notification_failed=True, retry_count=5)
        assert _derive_confirmation_status(apt) == "permanently_failed"


# ============================================================================
# T-03: _derive_reminder_status() (REQ-B)
# ============================================================================


class TestDeriveReminderStatus:
    """Tests for _derive_reminder_status()."""

    def test_pending_when_reminder_not_sent(self):
        apt = _make_mock_appointment(reminder_sent_at=None)
        assert _derive_reminder_status(apt) == "pending"

    def test_sent_when_reminder_sent(self):
        from datetime import datetime

        apt = _make_mock_appointment(reminder_sent_at=datetime(2026, 3, 26, 10, 0))
        assert _derive_reminder_status(apt) == "sent"


# ============================================================================
# T-04/T-05: get_customer_history() includes new keys (REQ-B)
# ============================================================================


class TestGetCustomerHistoryNewKeys:
    """Assert get_customer_history() output includes confirmation_status and reminder_status."""

    @pytest.mark.asyncio
    async def test_history_includes_confirmation_and_reminder_status(self):
        customer_id = str(uuid4())
        apt_id = uuid4()

        mock_apt = MagicMock()
        mock_apt.id = apt_id
        mock_apt.start_time = MagicMock()
        mock_apt.start_time.isoformat.return_value = "2026-04-01T10:00:00+02:00"
        mock_apt.duration_minutes = 60
        mock_apt.total_price = 25.0
        mock_apt.status = MagicMock()
        mock_apt.status.value = "pending"
        mock_apt.stylist_id = uuid4()
        mock_apt.service_ids = []
        mock_apt.notification_failed = False
        mock_apt.retry_count = 0
        mock_apt.confirmation_sent_at = None
        mock_apt.reminder_sent_at = None

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_apt]

        mock_session = AsyncMock()
        mock_session.execute = AsyncMock(return_value=mock_result)

        with patch("agent.tools.customer_tools.get_async_session") as mock_get_session:
            mock_get_session.return_value.__aenter__.return_value = mock_session

            from agent.tools.customer_tools import get_customer_history

            result = await get_customer_history.ainvoke({"customer_id": customer_id, "limit": 5})

        assert "appointments" in result
        assert len(result["appointments"]) == 1
        apt_dict = result["appointments"][0]
        assert "confirmation_status" in apt_dict, "confirmation_status key missing"
        assert "reminder_status" in apt_dict, "reminder_status key missing"
        assert apt_dict["confirmation_status"] == "pending"
        assert apt_dict["reminder_status"] == "pending"
