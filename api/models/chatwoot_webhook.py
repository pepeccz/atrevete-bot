"""Pydantic models for Chatwoot webhook payloads."""

import phonenumbers
from pydantic import BaseModel, field_validator


class ChatwootSender(BaseModel):
    """Chatwoot message sender information."""

    phone_number: str | None = None
    name: str | None = None


class ChatwootMessage(BaseModel):
    """Single message within a Chatwoot conversation."""

    id: int
    content: str | None = None
    message_type: int  # 0 = incoming, 1 = outgoing
    sender: ChatwootSender
    created_at: int  # Unix timestamp
    conversation_id: int


class ChatwootWebhookPayload(BaseModel):
    """
    Chatwoot webhook payload - contains full conversation with messages.

    Note: Chatwoot sends the entire conversation object, not individual message events.
    Messages are in the 'messages' array, with the most recent message last.
    """

    id: int  # conversation_id
    inbox_id: int
    messages: list[ChatwootMessage]


class ChatwootMessageEvent(BaseModel):
    """Parsed Chatwoot message event for Redis pub/sub."""

    conversation_id: str
    customer_phone: str
    message_text: str
    customer_name: str | None = None

    @field_validator("customer_phone")
    @classmethod
    def validate_phone_e164(cls, v: str) -> str:
        """Validate and normalize phone number to E.164 format."""
        try:
            # Parse with default region Spain
            parsed = phonenumbers.parse(v, "ES")
            if not phonenumbers.is_valid_number(parsed):
                raise ValueError(f"Invalid phone number: {v}")
            # Format to E.164 standard
            return phonenumbers.format_number(
                parsed, phonenumbers.PhoneNumberFormat.E164
            )
        except phonenumbers.NumberParseException as e:
            raise ValueError(f"Cannot parse phone number {v}: {e}") from e
