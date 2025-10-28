"""Unit tests for webhook Pydantic models."""

from typing import Any, TypedDict
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from api.models.chatwoot_webhook import (
    ChatwootMessageEvent,
    ChatwootWebhookPayload,
)
from api.models.stripe_webhook import StripePaymentEvent, StripeWebhookEvent


# TypedDict definitions for test fixtures
# Note: These use dict[str, Any] to match Pydantic's flexible input handling
class ChatwootSenderDict(TypedDict, total=False):
    """Type definition for Chatwoot sender test data."""

    phone_number: str | None
    name: str | None


class ChatwootConversationDict(TypedDict):
    """Type definition for Chatwoot conversation test data."""

    id: int
    inbox_id: int


class ChatwootWebhookPayloadDict(TypedDict, total=False):
    """Type definition for Chatwoot webhook payload test data."""

    event: str
    id: int
    content: str | None
    conversation: dict[str, Any]  # Pydantic handles nested conversion
    sender: dict[str, Any]  # Pydantic handles nested conversion
    created_at: str  # Pydantic handles datetime conversion
    message_type: str | None


class StripeWebhookEventDict(TypedDict, total=False):
    """Type definition for Stripe webhook event test data."""

    type: str
    id: str
    created: int
    data: dict[str, Any]  # Pydantic accepts nested dicts


class StripePaymentEventDict(TypedDict):
    """Type definition for Stripe payment event test data."""

    appointment_id: str | UUID  # Pydantic handles string-to-UUID conversion
    stripe_payment_id: str
    event_type: str


class TestChatwootWebhookPayload:
    """Tests for ChatwootWebhookPayload model."""

    def test_valid_payload_parses_correctly(self) -> None:
        """Test that a valid Chatwoot payload is parsed correctly."""
        payload: ChatwootWebhookPayloadDict = {
            "event": "message_created",
            "id": 12345,
            "content": "Hello, I need an appointment",
            "conversation": {"id": 100, "inbox_id": 1},
            "sender": {"phone_number": "+34612345678", "name": "María García"},
            "created_at": "2025-10-27T10:00:00Z",
            "message_type": "incoming",
        }

        # Pydantic validates and converts nested dicts at runtime
        result = ChatwootWebhookPayload(**payload)  # type: ignore[arg-type]

        assert result.event == "message_created"
        assert result.id == 12345
        assert result.content == "Hello, I need an appointment"
        assert result.conversation.id == 100
        assert result.sender.phone_number == "+34612345678"
        assert result.sender.name == "María García"
        assert result.message_type == "incoming"

    def test_missing_required_fields_raises_error(self) -> None:
        """Test that missing required fields raise ValidationError."""
        payload: dict[str, str] = {
            "event": "message_created",
            # Missing 'id', 'conversation', 'sender', 'created_at'
        }

        with pytest.raises(ValidationError) as exc_info:
            ChatwootWebhookPayload(**payload)  # type: ignore[arg-type]  # Intentionally invalid for testing

        errors = exc_info.value.errors()
        assert any(e["loc"] == ("id",) for e in errors)
        assert any(e["loc"] == ("conversation",) for e in errors)
        assert any(e["loc"] == ("sender",) for e in errors)

    def test_optional_fields_can_be_missing(self) -> None:
        """Test that optional fields can be missing without errors."""
        payload: ChatwootWebhookPayloadDict = {
            "event": "message_created",
            "id": 12345,
            "conversation": {"id": 100, "inbox_id": 1},
            "sender": {},  # phone_number and name are optional
            "created_at": "2025-10-27T10:00:00Z",
            # content and message_type are optional
        }

        # Pydantic validates and converts nested dicts at runtime
        result = ChatwootWebhookPayload(**payload)  # type: ignore[arg-type]

        assert result.content is None
        assert result.message_type is None
        assert result.sender.phone_number is None


class ChatwootMessageEventDict(TypedDict, total=False):
    """Type definition for ChatwootMessageEvent test data."""

    conversation_id: str
    customer_phone: str
    message_text: str
    customer_name: str | None


class TestChatwootMessageEvent:
    """Tests for ChatwootMessageEvent model."""

    def test_phone_normalization_to_e164(self) -> None:
        """Test that phone numbers are normalized to E.164 format."""
        event: ChatwootMessageEventDict = {
            "conversation_id": "123",
            "customer_phone": "612345678",  # Spanish number without country code
            "message_text": "Hello",
            "customer_name": "María",
        }

        result = ChatwootMessageEvent(**event)

        assert result.customer_phone == "+34612345678"  # Normalized to E.164

    def test_valid_e164_phone_unchanged(self) -> None:
        """Test that already E.164 formatted phones are unchanged."""
        event: ChatwootMessageEventDict = {
            "conversation_id": "123",
            "customer_phone": "+34612345678",
            "message_text": "Hello",
        }

        result = ChatwootMessageEvent(**event)

        assert result.customer_phone == "+34612345678"

    def test_invalid_phone_raises_error(self) -> None:
        """Test that invalid phone numbers raise ValidationError."""
        event: ChatwootMessageEventDict = {
            "conversation_id": "123",
            "customer_phone": "invalid_phone",
            "message_text": "Hello",
        }

        with pytest.raises(ValidationError) as exc_info:
            ChatwootMessageEvent(**event)

        errors = exc_info.value.errors()
        assert any("phone" in str(e).lower() for e in errors)


class TestStripeWebhookEvent:
    """Tests for StripeWebhookEvent model."""

    def test_valid_stripe_event_parses_correctly(self) -> None:
        """Test that a valid Stripe event is parsed correctly."""
        payload: StripeWebhookEventDict = {
            "type": "checkout.session.completed",
            "id": "evt_test_12345",
            "created": 1698412800,
            "data": {
                "object": {
                    "id": "cs_test_abc123",
                    "metadata": {"appointment_id": str(uuid4())},
                }
            },
        }

        result = StripeWebhookEvent(**payload)

        assert result.type == "checkout.session.completed"
        assert result.id == "evt_test_12345"
        assert result.created == 1698412800
        assert "object" in result.data

    def test_missing_required_fields_raises_error(self) -> None:
        """Test that missing required fields raise ValidationError."""
        payload: dict[str, str] = {
            "type": "checkout.session.completed",
            # Missing 'id', 'created', 'data'
        }

        with pytest.raises(ValidationError) as exc_info:
            StripeWebhookEvent(**payload)  # type: ignore[arg-type]  # Intentionally invalid for testing

        errors = exc_info.value.errors()
        assert any(e["loc"] == ("id",) for e in errors)
        assert any(e["loc"] == ("created",) for e in errors)


class TestStripePaymentEvent:
    """Tests for StripePaymentEvent model."""

    def test_valid_uuid_string_parses_correctly(self) -> None:
        """Test that valid UUID strings are parsed correctly."""
        appointment_id = uuid4()
        event: StripePaymentEventDict = {
            "appointment_id": str(appointment_id),
            "stripe_payment_id": "ch_abc123",
            "event_type": "checkout.session.completed",
        }

        # Pydantic validator converts string to UUID at runtime
        result = StripePaymentEvent(**event)  # type: ignore[arg-type]

        assert result.appointment_id == appointment_id
        assert result.stripe_payment_id == "ch_abc123"

    def test_uuid_object_accepted(self) -> None:
        """Test that UUID objects are accepted directly."""
        appointment_id = uuid4()
        event: StripePaymentEventDict = {
            "appointment_id": appointment_id,
            "stripe_payment_id": "ch_abc123",
            "event_type": "checkout.session.completed",
        }

        # Pydantic validator accepts UUID objects directly
        result = StripePaymentEvent(**event)  # type: ignore[arg-type]

        assert result.appointment_id == appointment_id

    def test_invalid_uuid_raises_error(self) -> None:
        """Test that invalid UUID strings raise ValidationError."""
        event: StripePaymentEventDict = {
            "appointment_id": "not-a-uuid",
            "stripe_payment_id": "ch_abc123",
            "event_type": "checkout.session.completed",
        }

        # Pydantic validator will raise error for invalid UUID
        with pytest.raises(ValidationError) as exc_info:
            StripePaymentEvent(**event)  # type: ignore[arg-type]

        errors = exc_info.value.errors()
        assert any("uuid" in str(e).lower() or "appointment" in str(e).lower() for e in errors)
