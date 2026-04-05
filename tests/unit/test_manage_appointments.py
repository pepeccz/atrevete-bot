"""
Tests for manage_appointments_tool module.

Verifies the consolidated tool schema:
- ManageAppointmentsSchema has action as Literal["list", "cancel", "reschedule"]
- customer_phone is required
"""

import pytest
from pydantic import ValidationError

from agent.tools.manage_appointments_tool import ManageAppointmentsSchema


def test_schema_has_action_field():
    """ManageAppointmentsSchema has action field."""
    fields = ManageAppointmentsSchema.model_fields
    assert "action" in fields, "action field is missing from ManageAppointmentsSchema"


def test_action_values_list():
    """Schema accepts 'list' as action value."""
    schema = ManageAppointmentsSchema(action="list", customer_phone="+34612345678")
    assert schema.action == "list"


def test_action_values_cancel():
    """Schema accepts 'cancel' as action value."""
    schema = ManageAppointmentsSchema(action="cancel", customer_phone="+34612345678")
    assert schema.action == "cancel"


def test_action_values_reschedule():
    """Schema accepts 'reschedule' as action value."""
    schema = ManageAppointmentsSchema(action="reschedule", customer_phone="+34612345678")
    assert schema.action == "reschedule"


def test_action_rejects_unknown_value():
    """Schema rejects unknown action values via Literal validation."""
    with pytest.raises(ValidationError):
        ManageAppointmentsSchema(action="delete", customer_phone="+34612345678")


def test_customer_phone_required():
    """customer_phone is a required field — omitting it raises ValidationError."""
    with pytest.raises(ValidationError):
        ManageAppointmentsSchema(action="list")
