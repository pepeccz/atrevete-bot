"""
Tests for manage_appointments_tool module.

Verifies the consolidated tool schema:
- ManageAppointmentsSchema has action as Literal["list", "cancel", "reschedule"]
- customer_phone is required
"""

from unittest.mock import AsyncMock, MagicMock, patch
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


# ─────────────────────────────────────────────────────────────────────────────
# Reschedule validator guard tests (T3 RED → T4 GREEN)
#
# These tests verify that _reschedule_appointment calls validate_booking_date
# BEFORE any DB write when new_date is provided.
# ─────────────────────────────────────────────────────────────────────────────

FAKE_APPT_ID = str(uuid4())
CUSTOMER_PHONE = "+34612345678"
OPEN_DATE = "2026-05-05"
SUNDAY_DATE = "2026-05-03"
REF_DATE_STR = "2026-04-28"


def _make_eligibility_ok():
    """Return a mock eligibility result that allows rescheduling."""
    eligible = MagicMock()
    eligible.eligible = True
    return eligible


def _make_execute_reschedule_result():
    """Return a mock reschedule result for the happy path."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    result = MagicMock()
    result.success = True
    result.new_start_time = datetime(2026, 5, 5, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    result.error = None
    result.slot_taken = False
    return result


@pytest.mark.asyncio
async def test_reschedule_g1_unresolvable_relative_text_no_db_write():
    """T3 G1: new_date='mañana' (unresolvable non-ISO) → error_code=invalid_relative_date, no DB write."""
    from agent.tools._booking_validators import DateValidationResult
    from agent.tools.manage_appointments_tool import _reschedule_appointment

    invalid_result = DateValidationResult(
        date_iso=None,
        error_code="invalid_relative_date",
        error_message="No pude entender la fecha. ¿Podés decirme el día y mes?",
        payload={"raw_text": "mañana"},
    )

    execute_reschedule_mock = AsyncMock()

    with (
        patch(
            "agent.services.reschedule_service.validate_reschedule_eligibility",
            new=AsyncMock(return_value=_make_eligibility_ok()),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_booking_date",
            new=AsyncMock(return_value=invalid_result),
        ),
        patch(
            "agent.services.reschedule_service.execute_reschedule",
            new=execute_reschedule_mock,
        ),
    ):
        result = await _reschedule_appointment(
            customer_phone=CUSTOMER_PHONE,
            appointment_id=FAKE_APPT_ID,
            new_date="mañana",
            new_time="10:00",
            reason=None,
        )

    assert result["success"] is False
    assert result["error_code"] == "invalid_relative_date"
    assert result["message"]  # Spanish message present
    execute_reschedule_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_reschedule_g2_sunday_closed_no_db_write():
    """T3 G2: new_date=Sunday ISO → error_code=closed_day, no DB write."""
    from agent.tools._booking_validators import DateValidationResult
    from agent.tools.manage_appointments_tool import _reschedule_appointment

    closed_result = DateValidationResult(
        date_iso=None,
        error_code="closed_day",
        error_message="El salón está cerrado el domingo.",
        payload={"closed_date": SUNDAY_DATE, "reason": "domingo"},
    )

    execute_reschedule_mock = AsyncMock()

    with (
        patch(
            "agent.services.reschedule_service.validate_reschedule_eligibility",
            new=AsyncMock(return_value=_make_eligibility_ok()),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_booking_date",
            new=AsyncMock(return_value=closed_result),
        ),
        patch(
            "agent.services.reschedule_service.execute_reschedule",
            new=execute_reschedule_mock,
        ),
    ):
        result = await _reschedule_appointment(
            customer_phone=CUSTOMER_PHONE,
            appointment_id=FAKE_APPT_ID,
            new_date=SUNDAY_DATE,
            new_time="10:00",
            reason=None,
        )

    assert result["success"] is False
    assert result["error_code"] == "closed_day"
    execute_reschedule_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_reschedule_g3_advance_policy_violated_no_db_write():
    """T3 G3: new_date=tomorrow (within lead-time) → error_code=advance_policy_violated, no DB write."""
    from agent.tools._booking_validators import DateValidationResult
    from agent.tools.manage_appointments_tool import _reschedule_appointment

    violation_result = DateValidationResult(
        date_iso=None,
        error_code="advance_policy_violated",
        error_message="La fecha viola la política de antelación mínima.",
        payload={"min_date": "2026-05-01", "min_days": 3},
    )

    execute_reschedule_mock = AsyncMock()

    with (
        patch(
            "agent.services.reschedule_service.validate_reschedule_eligibility",
            new=AsyncMock(return_value=_make_eligibility_ok()),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_booking_date",
            new=AsyncMock(return_value=violation_result),
        ),
        patch(
            "agent.services.reschedule_service.execute_reschedule",
            new=execute_reschedule_mock,
        ),
    ):
        result = await _reschedule_appointment(
            customer_phone=CUSTOMER_PHONE,
            appointment_id=FAKE_APPT_ID,
            new_date="2026-04-29",  # tomorrow — within lead-time
            new_time="10:00",
            reason=None,
        )

    assert result["success"] is False
    assert result["error_code"] == "advance_policy_violated"
    assert "min_date" in result  # payload spread into result
    execute_reschedule_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_reschedule_happy_path_valid_date_calls_db():
    """T3 happy path: valid future ISO → validator returns ok → execute_reschedule is called."""
    from agent.tools._booking_validators import DateValidationResult
    from agent.tools.manage_appointments_tool import _reschedule_appointment

    ok_result = DateValidationResult(
        date_iso=OPEN_DATE,
        error_code=None,
        error_message=None,
        payload={},
    )

    execute_reschedule_mock = AsyncMock(return_value=_make_execute_reschedule_result())

    with (
        patch(
            "agent.services.reschedule_service.validate_reschedule_eligibility",
            new=AsyncMock(return_value=_make_eligibility_ok()),
        ),
        patch(
            "agent.tools.manage_appointments_tool.validate_booking_date",
            new=AsyncMock(return_value=ok_result),
        ),
        patch(
            "agent.services.reschedule_service.execute_reschedule",
            new=execute_reschedule_mock,
        ),
    ):
        result = await _reschedule_appointment(
            customer_phone=CUSTOMER_PHONE,
            appointment_id=FAKE_APPT_ID,
            new_date=OPEN_DATE,
            new_time="10:00",
            reason=None,
        )

    assert result["success"] is True
    execute_reschedule_mock.assert_awaited_once()
