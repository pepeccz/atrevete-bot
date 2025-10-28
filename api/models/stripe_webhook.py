"""Pydantic models for Stripe webhook payloads."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, field_validator


class StripeWebhookEvent(BaseModel):
    """Stripe webhook event structure."""

    type: str
    data: dict[str, Any]
    id: str
    created: int


class StripePaymentEvent(BaseModel):
    """Parsed Stripe payment event for Redis pub/sub."""

    appointment_id: UUID
    stripe_payment_id: str
    event_type: str

    @field_validator("appointment_id", mode="before")
    @classmethod
    def validate_uuid(cls, v: Any) -> UUID:
        """Validate appointment_id is a valid UUID."""
        if isinstance(v, UUID):
            return v
        if isinstance(v, str):
            try:
                return UUID(v)
            except ValueError as exc:
                raise ValueError(f"Invalid UUID format: {v}") from exc
        raise ValueError(f"appointment_id must be UUID or string, got {type(v)}")
