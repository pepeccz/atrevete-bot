"""Unit tests for AppointmentStatus enum and migration fields."""

import pytest
from database.models import AppointmentStatus, Appointment, Customer


class TestAppointmentStatusEnum:
    """Test AppointmentStatus enum values."""

    def test_enum_has_correct_values(self):
        """AC1: Verify AppointmentStatus has 5 required values."""
        assert hasattr(AppointmentStatus, "PENDING")
        assert hasattr(AppointmentStatus, "CONFIRMED")
        assert hasattr(AppointmentStatus, "COMPLETED")
        assert hasattr(AppointmentStatus, "CANCELLED")
        assert hasattr(AppointmentStatus, "NO_SHOW")

        assert AppointmentStatus.PENDING.value == "pending"
        assert AppointmentStatus.CONFIRMED.value == "confirmed"
        assert AppointmentStatus.COMPLETED.value == "completed"
        assert AppointmentStatus.CANCELLED.value == "cancelled"
        assert AppointmentStatus.NO_SHOW.value == "no_show"

    def test_enum_does_not_have_old_values(self):
        """AC1: Verify old enum values (PROVISIONAL, EXPIRED) are removed from code."""
        assert not hasattr(AppointmentStatus, "PROVISIONAL")
        assert not hasattr(AppointmentStatus, "EXPIRED")

    def test_default_status_is_pending(self):
        """Verify Appointment model default status is PENDING."""
        # This tests the model definition, not DB constraint
        assert Appointment.__table__.columns["status"].default.arg == AppointmentStatus.PENDING


class TestAppointmentNewFields:
    """Test new tracking fields in Appointment model."""

    def test_model_has_confirmation_sent_at_field(self):
        """AC2: Verify confirmation_sent_at field exists."""
        assert "confirmation_sent_at" in Appointment.__table__.columns
        column = Appointment.__table__.columns["confirmation_sent_at"]
        assert column.nullable is True

    def test_model_has_reminder_sent_at_field(self):
        """AC2: Verify reminder_sent_at field exists."""
        assert "reminder_sent_at" in Appointment.__table__.columns
        column = Appointment.__table__.columns["reminder_sent_at"]
        assert column.nullable is True

    def test_model_has_cancelled_at_field(self):
        """AC2: Verify cancelled_at field exists."""
        assert "cancelled_at" in Appointment.__table__.columns
        column = Appointment.__table__.columns["cancelled_at"]
        assert column.nullable is True

    def test_model_has_notification_failed_field(self):
        """AC2: Verify notification_failed field exists with default False."""
        assert "notification_failed" in Appointment.__table__.columns
        column = Appointment.__table__.columns["notification_failed"]
        assert column.nullable is False
        assert column.server_default.arg == "false"


class TestCustomerNewFields:
    """Test new fields in Customer model."""

    def test_model_has_chatwoot_conversation_id_field(self):
        """AC3: Verify chatwoot_conversation_id field exists."""
        assert "chatwoot_conversation_id" in Customer.__table__.columns
        column = Customer.__table__.columns["chatwoot_conversation_id"]
        assert column.nullable is True
        assert column.type.length == 50
