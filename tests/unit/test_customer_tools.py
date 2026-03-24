"""Unit tests for agent/tools/customer_tools.py — qa-infra-hardening.

Tests REQ-QIH-3: normalize_phone() QA bypass for +34999xxxxxx phones.
Also covers regression tests for valid/invalid Spanish phones.
"""

import pytest

from agent.tools.customer_tools import normalize_phone


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
