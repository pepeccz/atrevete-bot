"""
Tests for manage_appointments_tool module.

Verifies the consolidated tool schema:
- ManageAppointmentsSchema has action as Literal["list", "cancel", "reschedule"]
- customer_phone is required
"""

from unittest.mock import AsyncMock, patch
from uuid import uuid4

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


def test_action_accepts_confirm():
    schema = ManageAppointmentsSchema(action="confirm", customer_phone="+34612345678")
    assert schema.action == "confirm"


def test_action_accepts_decline():
    schema = ManageAppointmentsSchema(action="decline", customer_phone="+34612345678")
    assert schema.action == "decline"


# ─────────────────────────────────────────────────────────────────────────────
# Tool dispatch tests for confirm/decline actions
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_confirm_action_happy():
    """confirm action delegates to handle_tool_action with CONFIRM_APPOINTMENT."""
    from agent.routing.intent_types import IntentType
    from agent.services.confirmation_service import ConfirmationResult
    from agent.tools.manage_appointments_tool import manage_appointments

    appt_id = uuid4()
    fake_result = ConfirmationResult(
        success=True,
        appointment_id=appt_id,
        response_text="¡Perfecto! Tu cita queda confirmada.",
    )
    with patch(
        "agent.services.confirmation_service.handle_tool_action",
        new=AsyncMock(return_value=fake_result),
    ) as mock_handler:
        out = await manage_appointments.ainvoke(
            {
                "action": "confirm",
                "customer_phone": "+34612345678",
                "appointment_id": str(appt_id),
            }
        )
    assert "confirmada" in out.lower()
    mock_handler.assert_awaited_once()
    args, kwargs = mock_handler.call_args
    # Accept either positional or keyword form
    passed = list(args) + list(kwargs.values())
    assert IntentType.CONFIRM_APPOINTMENT in passed


@pytest.mark.asyncio
async def test_decline_action_happy():
    """decline action delegates to handle_tool_action with DECLINE_APPOINTMENT."""
    from agent.routing.intent_types import IntentType
    from agent.services.confirmation_service import ConfirmationResult
    from agent.tools.manage_appointments_tool import manage_appointments

    appt_id = uuid4()
    fake_result = ConfirmationResult(
        success=True,
        appointment_id=appt_id,
        response_text="Entendido. Tu cita ha sido cancelada.",
    )
    with patch(
        "agent.services.confirmation_service.handle_tool_action",
        new=AsyncMock(return_value=fake_result),
    ) as mock_handler:
        out = await manage_appointments.ainvoke(
            {
                "action": "decline",
                "customer_phone": "+34612345678",
                "appointment_id": str(appt_id),
            }
        )
    assert "cancelada" in out.lower()
    mock_handler.assert_awaited_once()
    passed = list(mock_handler.call_args.args) + list(mock_handler.call_args.kwargs.values())
    assert IntentType.DECLINE_APPOINTMENT in passed


@pytest.mark.asyncio
async def test_confirm_invalid_uuid():
    from agent.tools.manage_appointments_tool import manage_appointments

    out = await manage_appointments.ainvoke(
        {
            "action": "confirm",
            "customer_phone": "+34612345678",
            "appointment_id": "not-a-uuid",
        }
    )
    assert "no es válido" in out.lower() or "inválido" in out.lower()


@pytest.mark.asyncio
async def test_confirm_missing_appointment_id():
    from agent.tools.manage_appointments_tool import manage_appointments

    out = await manage_appointments.ainvoke(
        {
            "action": "confirm",
            "customer_phone": "+34612345678",
        }
    )
    assert "id" in out.lower()
