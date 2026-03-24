"""Unit tests for api/models/chatwoot_webhook.py — qa-infra-hardening.

Tests REQ-QIH-4: validate_phone_e164() QA bypass for +34999xxxxxx phones.
Also covers regression tests for valid/invalid phone validation.
"""

import pytest
from pydantic import ValidationError

from api.models.chatwoot_webhook import ChatwootMessageEvent


def _make_event(phone: str) -> ChatwootMessageEvent:
    """Construct a minimal ChatwootMessageEvent with the given phone."""
    return ChatwootMessageEvent(
        conversation_id="conv-001",
        customer_phone=phone,
        message_text="Hola",
    )


# ============================================================================
# REQ-QIH-4: QA Phone Bypass in validate_phone_e164()
# ============================================================================


class TestValidatePhoneE164QABypass:
    """Tests for the +34999xxxxxx QA safety-prefix bypass."""

    def test_qa_phone_passes_validation(self):
        """validate_phone_e164('+34999000002') stores value unchanged."""
        event = _make_event("+34999000002")
        assert event.customer_phone == "+34999000002"

    def test_qa_phone_different_suffix_passes(self):
        """validate_phone_e164('+34999123456') stores value unchanged."""
        event = _make_event("+34999123456")
        assert event.customer_phone == "+34999123456"

    def test_qa_phone_prefix_only_raises(self):
        """'+34999' alone does not match the pattern — raises ValidationError."""
        with pytest.raises(ValidationError):
            _make_event("+34999")

    def test_qa_phone_too_many_digits_raises(self):
        """+34999 with 7 suffix digits does not match — raises ValidationError."""
        with pytest.raises(ValidationError):
            _make_event("+349991234567")

    def test_qa_phone_with_alpha_raises(self):
        """+34999abc123 does not match pattern — raises ValidationError."""
        with pytest.raises(ValidationError):
            _make_event("+34999abc123")


# ============================================================================
# Regression: non-QA phone validation unchanged
# ============================================================================


class TestValidatePhoneE164Regression:
    """Regression tests — non-QA phones follow the existing validation path."""

    def test_valid_spanish_mobile_passes(self):
        """'+34600000001' is a valid Spanish mobile and passes."""
        event = _make_event("+34600000001")
        assert event.customer_phone == "+34600000001"

    def test_invalid_phone_raises_validation_error(self):
        """'not-a-phone' raises ValidationError."""
        with pytest.raises(ValidationError):
            _make_event("not-a-phone")

    def test_empty_string_raises_validation_error(self):
        """Empty string raises ValidationError."""
        with pytest.raises(ValidationError):
            _make_event("")
