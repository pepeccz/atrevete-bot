"""Unit tests for hold_tools.py — Pydantic schema validation.

Covers:
- CreateHoldSchema: valid and invalid inputs
- ConfirmFromHoldSchema: valid and invalid inputs
"""

import pytest
from pydantic import ValidationError

from agent.tools.hold_tools import (
    HOLD_TTL_MINUTES,
    ConfirmFromHoldSchema,
    CreateHoldSchema,
)


# ============================================================================
# CreateHoldSchema
# ============================================================================


class TestCreateHoldSchema:
    """Pydantic validation tests for CreateHoldSchema."""

    def test_valid_schema_accepts_all_fields(self):
        """All required fields provided → no validation error."""
        schema = CreateHoldSchema(
            stylist_id="a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
            service_ids=["b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12"],
            start_time="2026-04-15T10:00:00+02:00",
            customer_id="c0eebc99-9c0b-4ef8-bb6d-6bb9bd380a13",
            duration_minutes=60,
            idempotency_key="conv-123:stylist-abc:2026-04-15T10:00:00",
            first_name="María",
        )
        assert schema.stylist_id == "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"
        assert schema.duration_minutes == 60
        assert schema.first_name == "María"

    def test_valid_schema_multiple_service_ids(self):
        """Multiple service IDs are accepted."""
        schema = CreateHoldSchema(
            stylist_id="a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
            service_ids=[
                "b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12",
                "d0eebc99-9c0b-4ef8-bb6d-6bb9bd380a14",
            ],
            start_time="2026-04-15T11:00:00+02:00",
            customer_id="c0eebc99-9c0b-4ef8-bb6d-6bb9bd380a13",
            duration_minutes=90,
            idempotency_key="conv-456:key",
            first_name="Ana",
        )
        assert len(schema.service_ids) == 2

    def test_missing_stylist_id_raises(self):
        """Missing stylist_id → ValidationError."""
        with pytest.raises(ValidationError):
            CreateHoldSchema(
                service_ids=["b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12"],
                start_time="2026-04-15T10:00:00+02:00",
                customer_id="c0eebc99-9c0b-4ef8-bb6d-6bb9bd380a13",
                duration_minutes=60,
                idempotency_key="key",
                first_name="María",
            )

    def test_missing_customer_id_raises(self):
        """Missing customer_id → ValidationError."""
        with pytest.raises(ValidationError):
            CreateHoldSchema(
                stylist_id="a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
                service_ids=["b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12"],
                start_time="2026-04-15T10:00:00+02:00",
                duration_minutes=60,
                idempotency_key="key",
                first_name="María",
            )

    def test_missing_start_time_raises(self):
        """Missing start_time → ValidationError."""
        with pytest.raises(ValidationError):
            CreateHoldSchema(
                stylist_id="a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
                service_ids=["b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12"],
                customer_id="c0eebc99-9c0b-4ef8-bb6d-6bb9bd380a13",
                duration_minutes=60,
                idempotency_key="key",
                first_name="María",
            )

    def test_missing_duration_minutes_raises(self):
        """Missing duration_minutes → ValidationError."""
        with pytest.raises(ValidationError):
            CreateHoldSchema(
                stylist_id="a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
                service_ids=["b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12"],
                start_time="2026-04-15T10:00:00+02:00",
                customer_id="c0eebc99-9c0b-4ef8-bb6d-6bb9bd380a13",
                idempotency_key="key",
                first_name="María",
            )

    def test_missing_idempotency_key_raises(self):
        """Missing idempotency_key → ValidationError."""
        with pytest.raises(ValidationError):
            CreateHoldSchema(
                stylist_id="a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
                service_ids=["b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12"],
                start_time="2026-04-15T10:00:00+02:00",
                customer_id="c0eebc99-9c0b-4ef8-bb6d-6bb9bd380a13",
                duration_minutes=60,
                first_name="María",
            )

    def test_missing_first_name_raises(self):
        """Missing first_name → ValidationError."""
        with pytest.raises(ValidationError):
            CreateHoldSchema(
                stylist_id="a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
                service_ids=["b0eebc99-9c0b-4ef8-bb6d-6bb9bd380a12"],
                start_time="2026-04-15T10:00:00+02:00",
                customer_id="c0eebc99-9c0b-4ef8-bb6d-6bb9bd380a13",
                duration_minutes=60,
                idempotency_key="key",
            )

    def test_empty_service_ids_accepted(self):
        """Empty service_ids list is structurally valid (business rules validate elsewhere)."""
        schema = CreateHoldSchema(
            stylist_id="a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11",
            service_ids=[],
            start_time="2026-04-15T10:00:00+02:00",
            customer_id="c0eebc99-9c0b-4ef8-bb6d-6bb9bd380a13",
            duration_minutes=60,
            idempotency_key="key",
            first_name="María",
        )
        assert schema.service_ids == []


# ============================================================================
# ConfirmFromHoldSchema
# ============================================================================


class TestConfirmFromHoldSchema:
    """Pydantic validation tests for ConfirmFromHoldSchema."""

    def test_valid_uuid_string(self):
        """Valid UUID string → schema accepted."""
        schema = ConfirmFromHoldSchema(hold_id="a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11")
        assert schema.hold_id == "a0eebc99-9c0b-4ef8-bb6d-6bb9bd380a11"

    def test_non_uuid_string_accepted_as_str(self):
        """Any string is accepted (UUID validation happens at DB level, not schema)."""
        schema = ConfirmFromHoldSchema(hold_id="not-a-real-uuid-but-string")
        assert schema.hold_id == "not-a-real-uuid-but-string"

    def test_missing_hold_id_raises(self):
        """Missing hold_id → ValidationError."""
        with pytest.raises(ValidationError):
            ConfirmFromHoldSchema()

    def test_none_hold_id_raises(self):
        """None hold_id → ValidationError (field is required)."""
        with pytest.raises(ValidationError):
            ConfirmFromHoldSchema(hold_id=None)


# ============================================================================
# Constants
# ============================================================================


def test_hold_ttl_minutes_is_five():
    """HOLD_TTL_MINUTES should be 5 (business-agreed TTL for WhatsApp context)."""
    assert HOLD_TTL_MINUTES == 5
