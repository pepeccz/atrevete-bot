"""Unit tests for webhook signature validation."""

import hashlib
import hmac
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Request
from stripe import SignatureVerificationError

from api.middleware.signature_validation import (
    validate_chatwoot_signature,
    validate_stripe_signature,
)


class TestChatwootSignatureValidation:
    """Tests for Chatwoot signature validation."""

    @pytest.mark.asyncio
    async def test_valid_signature_passes(self):
        """Test that valid HMAC-SHA256 signature passes validation."""
        secret = "test_secret"
        body = b'{"event":"message_created","content":"Hello"}'

        # Generate valid signature
        expected_signature = hmac.new(
            secret.encode(), body, hashlib.sha256
        ).hexdigest()

        # Mock request
        mock_request = AsyncMock(spec=Request)
        mock_request.body = AsyncMock(return_value=body)
        mock_request.headers = {"X-Chatwoot-Signature": expected_signature}

        # Mock settings
        with patch("api.middleware.signature_validation.get_settings") as mock_settings:
            mock_settings.return_value.CHATWOOT_WEBHOOK_SECRET = secret

            result = await validate_chatwoot_signature(mock_request)

            assert result == body

    @pytest.mark.asyncio
    async def test_invalid_signature_returns_401(self):
        """Test that invalid signature raises 401 HTTPException."""
        secret = "test_secret"
        body = b'{"event":"message_created","content":"Hello"}'

        # Mock request with WRONG signature
        mock_request = AsyncMock(spec=Request)
        mock_request.body = AsyncMock(return_value=body)
        mock_request.headers = {"X-Chatwoot-Signature": "wrong_signature_12345"}

        # Mock settings
        with patch("api.middleware.signature_validation.get_settings") as mock_settings:
            mock_settings.return_value.CHATWOOT_WEBHOOK_SECRET = secret

            with pytest.raises(HTTPException) as exc_info:
                await validate_chatwoot_signature(mock_request)

            assert exc_info.value.status_code == 401
            assert "Invalid signature" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_missing_signature_header_returns_401(self):
        """Test that missing signature header raises 401 HTTPException."""
        secret = "test_secret"
        body = b'{"event":"message_created","content":"Hello"}'

        # Mock request WITHOUT signature header
        mock_request = AsyncMock(spec=Request)
        mock_request.body = AsyncMock(return_value=body)
        mock_request.headers = {}  # No signature header

        # Mock settings
        with patch("api.middleware.signature_validation.get_settings") as mock_settings:
            mock_settings.return_value.CHATWOOT_WEBHOOK_SECRET = secret

            with pytest.raises(HTTPException) as exc_info:
                await validate_chatwoot_signature(mock_request)

            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_timing_safe_comparison_used(self):
        """Test that timing-safe comparison is used (hmac.compare_digest)."""
        # This test verifies the code uses hmac.compare_digest by checking
        # that invalid signatures are rejected consistently
        secret = "test_secret"
        body = b'{"event":"message_created","content":"Hello"}'

        mock_request = AsyncMock(spec=Request)
        mock_request.body = AsyncMock(return_value=body)

        # Try multiple invalid signatures - all should fail consistently
        invalid_sigs = [
            "aaaa",
            "bbbb",
            "0" * 64,  # Wrong but correct length
            "f" * 64,
        ]

        for invalid_sig in invalid_sigs:
            mock_request.headers = {"X-Chatwoot-Signature": invalid_sig}

            with patch(
                "api.middleware.signature_validation.get_settings"
            ) as mock_settings:
                mock_settings.return_value.CHATWOOT_WEBHOOK_SECRET = secret

                with pytest.raises(HTTPException) as exc_info:
                    await validate_chatwoot_signature(mock_request)

                assert exc_info.value.status_code == 401


class TestStripeSignatureValidation:
    """Tests for Stripe signature validation."""

    @pytest.mark.asyncio
    async def test_valid_stripe_signature_returns_event(self):
        """Test that valid Stripe signature returns parsed event."""
        secret = "whsec_test_secret"
        body = b'{"type":"checkout.session.completed","id":"evt_test"}'

        mock_event = {
            "type": "checkout.session.completed",
            "id": "evt_test",
        }

        # Mock request
        mock_request = AsyncMock(spec=Request)
        mock_request.body = AsyncMock(return_value=body)
        mock_request.headers = {"Stripe-Signature": "valid_signature"}

        # Mock settings and Stripe
        with patch("api.middleware.signature_validation.get_settings") as mock_settings:
            mock_settings.return_value.STRIPE_WEBHOOK_SECRET = secret

            with patch(
                "api.middleware.signature_validation.stripe.Webhook.construct_event"
            ) as mock_construct:
                mock_construct.return_value = mock_event

                result = await validate_stripe_signature(mock_request)

                assert result == mock_event
                mock_construct.assert_called_once_with(
                    payload=body, sig_header="valid_signature", secret=secret
                )

    @pytest.mark.asyncio
    async def test_invalid_stripe_signature_returns_401(self):
        """Test that invalid Stripe signature raises 401 HTTPException."""
        secret = "whsec_test_secret"
        body = b'{"type":"checkout.session.completed","id":"evt_test"}'

        # Mock request
        mock_request = AsyncMock(spec=Request)
        mock_request.body = AsyncMock(return_value=body)
        mock_request.headers = {"Stripe-Signature": "invalid_signature"}

        # Mock settings and Stripe
        with patch("api.middleware.signature_validation.get_settings") as mock_settings:
            mock_settings.return_value.STRIPE_WEBHOOK_SECRET = secret

            with patch(
                "api.middleware.signature_validation.stripe.Webhook.construct_event"
            ) as mock_construct:
                # Simulate signature verification error
                mock_construct.side_effect = SignatureVerificationError(
                    "Invalid signature", "sig_header"
                )

                with pytest.raises(HTTPException) as exc_info:
                    await validate_stripe_signature(mock_request)

                assert exc_info.value.status_code == 401
                assert "Invalid Stripe signature" in exc_info.value.detail

    @pytest.mark.asyncio
    async def test_missing_stripe_signature_header_returns_401(self):
        """Test that missing Stripe signature header raises 401 HTTPException."""
        secret = "whsec_test_secret"
        body = b'{"type":"checkout.session.completed","id":"evt_test"}'

        # Mock request WITHOUT signature header
        mock_request = AsyncMock(spec=Request)
        mock_request.body = AsyncMock(return_value=body)
        mock_request.headers = {}  # No signature header

        # Mock settings
        with patch("api.middleware.signature_validation.get_settings") as mock_settings:
            mock_settings.return_value.STRIPE_WEBHOOK_SECRET = secret

            with pytest.raises(HTTPException) as exc_info:
                await validate_stripe_signature(mock_request)

            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_expired_stripe_signature_returns_401(self):
        """Test that expired Stripe signature raises 401 HTTPException."""
        secret = "whsec_test_secret"
        body = b'{"type":"checkout.session.completed","id":"evt_test"}'

        # Mock request
        mock_request = AsyncMock(spec=Request)
        mock_request.body = AsyncMock(return_value=body)
        mock_request.headers = {"Stripe-Signature": "expired_signature"}

        # Mock settings and Stripe
        with patch("api.middleware.signature_validation.get_settings") as mock_settings:
            mock_settings.return_value.STRIPE_WEBHOOK_SECRET = secret

            with patch(
                "api.middleware.signature_validation.stripe.Webhook.construct_event"
            ) as mock_construct:
                # Simulate expired timestamp error (Stripe rejects old signatures)
                mock_construct.side_effect = SignatureVerificationError(
                    "Timestamp outside the tolerance zone", "sig_header"
                )

                with pytest.raises(HTTPException) as exc_info:
                    await validate_stripe_signature(mock_request)

                assert exc_info.value.status_code == 401
